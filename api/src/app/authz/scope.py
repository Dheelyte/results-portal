"""Row visibility (ARCHITECTURE.md §5.2).

> "Route guards alone are not enough. A subject teacher hitting another
> class's results must get a 404, and the filtering must happen where the data
> is fetched."

Every function here returns a `Select` that is **already filtered** — by
`school_id` always, and by the caller's scope. A router that builds its query
from one of these cannot forget the filter, because there is no unfiltered
query to forget it from.

Teacher scope is not derived from `users.role`. "Class teacher" and "subject
teacher" are both `UserRole.TEACHER`; what separates them is a row in
`class_teachers` or in `teaching_assignments`. One teacher is frequently both,
in different classes, and §5.2 requires the **union** of those scopes and
nothing wider.
"""

import uuid
from typing import Any

from sqlalchemy import Select, select

from app.models import (
    AcademicSession,
    AssessmentPeriod,
    AttendanceRecord,
    Class,
    ClassSubject,
    ClassTeacher,
    ClassTermStatus,
    CommentBank,
    Enrollment,
    GradeBand,
    GradingScale,
    GrowthRecord,
    GuardianPupil,
    House,
    MarksObtainable,
    NarrativeEntry,
    NarrativeSection,
    NarrativeSectionAssignment,
    PublicationState,
    Pupil,
    ResultEntry,
    Subject,
    TeachingAssignment,
    Term,
    TermReport,
    User,
    UserRole,
)

# Roles that see every row in their own school. Not a shortcut: §5.2 gives the
# admin the whole setup surface and the head teacher the whole review queue.
SCHOOL_WIDE_ROLES = frozenset({UserRole.ADMIN, UserRole.HEAD_TEACHER})


def current_session_id(school_id: uuid.UUID):
    """Scalar subquery for the school's current academic session.

    A subquery rather than a fetched value, so scope resolution stays one
    round trip. The current session is a row an admin sets (§2.3), never a
    constant and never derived from the clock.
    """
    return (
        select(AcademicSession.id)
        .where(
            AcademicSession.school_id == school_id,
            AcademicSession.is_current.is_(True),
        )
        .limit(1)
        .scalar_subquery()
    )


def _session_filter(user: User, academic_session_id: uuid.UUID | None):
    return (
        academic_session_id
        if academic_session_id is not None
        else current_session_id(user.school_id)
    )


def class_ids_taught_by(user: User, academic_session_id: uuid.UUID | None = None):
    """Every class this teacher touches, by either route.

    The union of §5.2: classes they are class teacher of, plus classes where
    they hold a teaching assignment. A teacher who is class teacher of 4A and
    French teacher in 5B gets both — and nothing wider.
    """
    session_id = _session_filter(user, academic_session_id)

    as_class_teacher = select(ClassTeacher.class_id).where(
        ClassTeacher.school_id == user.school_id,
        ClassTeacher.teacher_user_id == user.id,
        ClassTeacher.academic_session_id == session_id,
    )
    as_subject_teacher = (
        select(ClassSubject.class_id)
        .join(TeachingAssignment, TeachingAssignment.class_subject_id == ClassSubject.id)
        .where(
            ClassSubject.school_id == user.school_id,
            TeachingAssignment.teacher_user_id == user.id,
            ClassSubject.academic_session_id == session_id,
        )
    )
    return as_class_teacher.union(as_subject_teacher)


def class_ids_where_class_teacher(user: User, academic_session_id: uuid.UUID | None = None):
    """Classes where this user is *the class teacher*.

    Narrower than `class_ids_taught_by`, and the right scope for the pastoral
    work §5.2 gives only to the class teacher: attendance, growth, comments,
    and submitting the class for review.
    """
    return select(ClassTeacher.class_id).where(
        ClassTeacher.school_id == user.school_id,
        ClassTeacher.teacher_user_id == user.id,
        ClassTeacher.academic_session_id == _session_filter(user, academic_session_id),
    )


def pupil_ids_of_guardian(user: User):
    return select(GuardianPupil.pupil_id).where(GuardianPupil.guardian_user_id == user.id)


# ---------------------------------------------------------------------------
# Resource scopes
# ---------------------------------------------------------------------------


def scoped_classes(user: User, academic_session_id: uuid.UUID | None = None) -> Select:
    """Classes this user may see."""
    stmt = select(Class).where(Class.school_id == user.school_id)

    if user.role in SCHOOL_WIDE_ROLES:
        return stmt

    if user.role is UserRole.TEACHER:
        return stmt.where(Class.id.in_(class_ids_taught_by(user, academic_session_id)))

    if user.role is UserRole.PARENT:
        return stmt.where(
            Class.id.in_(
                select(Enrollment.class_id).where(
                    Enrollment.pupil_id.in_(pupil_ids_of_guardian(user)),
                    Enrollment.academic_session_id == _session_filter(user, academic_session_id),
                )
            )
        )

    return stmt.where(False)  # pragma: no cover - every role is handled above


def scoped_class_subjects(user: User, academic_session_id: uuid.UUID | None = None) -> Select:
    """Class-subjects this user may see.

    For a teacher this is only what they are assigned to teach — being class
    teacher of 4A does not grant sight of another teacher's scores for 4A
    Mathematics.
    """
    stmt = select(ClassSubject).where(ClassSubject.school_id == user.school_id)

    if user.role in SCHOOL_WIDE_ROLES:
        return stmt

    if user.role is UserRole.TEACHER:
        return stmt.where(
            ClassSubject.id.in_(
                select(TeachingAssignment.class_subject_id).where(
                    TeachingAssignment.school_id == user.school_id,
                    TeachingAssignment.teacher_user_id == user.id,
                )
            )
        )

    return stmt.where(False)  # parents never see a class-subject


def scoped_pupils(user: User, academic_session_id: uuid.UUID | None = None) -> Select:
    """Pupils this user may see.

    A parent sees their own children and no others — the single most important
    filter in the system.
    """
    stmt = select(Pupil).where(Pupil.school_id == user.school_id)

    if user.role in SCHOOL_WIDE_ROLES:
        return stmt

    if user.role is UserRole.TEACHER:
        return stmt.where(
            Pupil.id.in_(
                select(Enrollment.pupil_id).where(
                    Enrollment.class_id.in_(class_ids_taught_by(user, academic_session_id)),
                    Enrollment.academic_session_id == _session_filter(user, academic_session_id),
                )
            )
        )

    if user.role is UserRole.PARENT:
        return stmt.where(Pupil.id.in_(pupil_ids_of_guardian(user)))

    return stmt.where(False)  # pragma: no cover


def scoped_term_reports(user: User, academic_session_id: uuid.UUID | None = None) -> Select:
    """Term reports this user may see.

    A parent sees a report **only once published** (R12). A draft or withheld
    report is invisible rather than forbidden: the endpoint returns the
    school-contact message, and a 403 would confirm the report exists.
    """
    stmt = select(TermReport).where(TermReport.school_id == user.school_id)

    if user.role in SCHOOL_WIDE_ROLES:
        return stmt

    if user.role is UserRole.TEACHER:
        return stmt.where(TermReport.class_id.in_(class_ids_taught_by(user, academic_session_id)))

    if user.role is UserRole.PARENT:
        return stmt.where(
            TermReport.pupil_id.in_(pupil_ids_of_guardian(user)),
            TermReport.state == PublicationState.PUBLISHED,
        )

    return stmt.where(False)  # pragma: no cover


def narrative_section_ids_assigned_to(
    user: User, class_id: uuid.UUID, academic_session_id: uuid.UUID | None = None
):
    """Narrative sections this user is explicitly assigned for one class.

    Absence of a row means the class teacher writes it (D15), so this is only
    half the answer; `policy.can_write_narrative` combines both halves.
    """
    return select(NarrativeSectionAssignment.section_id).where(
        NarrativeSectionAssignment.school_id == user.school_id,
        NarrativeSectionAssignment.class_id == class_id,
        NarrativeSectionAssignment.teacher_user_id == user.id,
        NarrativeSectionAssignment.academic_session_id
        == _session_filter(user, academic_session_id),
    )


# ---------------------------------------------------------------------------
# Setup resources (milestone 5)
# ---------------------------------------------------------------------------
#
# §5.2's first three rows give the whole setup surface to the admin and nothing
# to anyone else. These resolvers are the visibility half of that: they filter
# by `school_id`, and they return nothing at all to a teacher or a parent.
#
# Deliberately narrow. Milestone 6 widens the ones §7 requires a teacher to
# read — `/my/assignments` needs subject names — and widening one of these on
# purpose is a decision with a test, where starting wide would be an accident
# nobody notices.


def _school_wide_only(stmt: Select, user: User) -> Select:
    """School rows for a school-wide role; nothing for anyone else."""
    if user.role in SCHOOL_WIDE_ROLES:
        return stmt
    return stmt.where(False)


def _reference_data(stmt: Select, user: User, school_column: Any) -> Select:
    """Rows every member of the school may read, filtered to their school.

    The distinction this draws is the one §5.2 is really about. Managing the
    calendar, the subject list, the grading scale and the Marks Obtainable row
    belongs to the admin alone — and the capability gates in
    `authz/dependencies.py` enforce exactly that, so no teacher or parent can
    reach a verb that changes any of it.

    *Reading* them is a different question. A teacher cannot enter scores
    without knowing which half's sheet is open and what each column is marked
    out of; a parent's card prints the subject names, the grade key and the
    Marks Obtainable row. None of these tables holds a pupil, a score or a
    comment, so widening sight of them reveals nothing about any child.

    Tables that do carry something personal — `users`, `enrollments`,
    `comment_bank` — keep `_school_wide_only` (docs/DECISIONS.md D50).
    """
    return stmt.where(school_column == user.school_id)


def scoped_academic_sessions(user: User) -> Select:
    return _reference_data(select(AcademicSession), user, AcademicSession.school_id)


def scoped_terms(user: User) -> Select:
    return _reference_data(select(Term), user, Term.school_id)


def scoped_assessment_periods(user: User) -> Select:
    return _reference_data(select(AssessmentPeriod), user, AssessmentPeriod.school_id)


def scoped_houses(user: User) -> Select:
    """Printed on the card, so a parent sees it too."""
    return _reference_data(select(House), user, House.school_id)


def scoped_subjects(user: User) -> Select:
    return _reference_data(select(Subject), user, Subject.school_id)


def scoped_grading_scales(user: User) -> Select:
    """The grade key, which the card prints at the foot of the sheet."""
    return _reference_data(select(GradingScale), user, GradingScale.school_id)


def scoped_grade_bands(user: User) -> Select:
    """Bands reached through their scale.

    `grade_bands` has no `school_id` of its own (§4.5) — it hangs off the
    scale — so the tenant filter has to come through the join rather than from
    a column on the row.
    """
    return _reference_data(
        select(GradeBand).join(GradingScale, GradingScale.id == GradeBand.scale_id),
        user,
        GradingScale.school_id,
    )


def scoped_narrative_sections(user: User) -> Select:
    """The card's section labels, which a teacher writes into (§4.6)."""
    return _reference_data(select(NarrativeSection), user, NarrativeSection.school_id)


def scoped_narrative_section_assignments(user: User) -> Select:
    return _school_wide_only(
        select(NarrativeSectionAssignment).where(
            NarrativeSectionAssignment.school_id == user.school_id
        ),
        user,
    )


def scoped_comment_bank(user: User) -> Select:
    """The phrase bank, readable by every member of staff.

    Milestone 6's D50 left this with `_school_wide_only`, on the grounds that
    a phrase bank is not reference data. Milestone 7 showed that to be wrong
    in practice: §8.2 puts a phrase-bank button beside every one of the
    sixteen sections, and §4.6 calls the bank "core, not optional" precisely
    because one teacher writes 480 passages a term. A teacher who cannot read
    it cannot use it.

    Parents are still excluded — the phrases are staff drafting material, and
    a parent reads only the finished passage on a published report
    (docs/DECISIONS.md D55).
    """
    stmt = select(CommentBank).where(CommentBank.school_id == user.school_id)
    if user.role is UserRole.PARENT:
        return stmt.where(False)
    return stmt


def scoped_marks_obtainable(user: User) -> Select:
    """R1 validates against this row and §8.1 pins it to the top of the grid,
    so a teacher must be able to read it. Only an admin may set it."""
    return _reference_data(select(MarksObtainable), user, MarksObtainable.school_id)


def scoped_enrollments(user: User) -> Select:
    """Enrolments this user may see.

    A teacher sees the enrolments of the classes they touch and a parent only
    their own children's, because this is the table that says which class a
    named child is in.
    """
    stmt = select(Enrollment).where(Enrollment.school_id == user.school_id)

    if user.role in SCHOOL_WIDE_ROLES:
        return stmt

    if user.role is UserRole.TEACHER:
        return stmt.where(Enrollment.class_id.in_(class_ids_taught_by(user)))

    if user.role is UserRole.PARENT:
        return stmt.where(Enrollment.pupil_id.in_(pupil_ids_of_guardian(user)))

    return stmt.where(False)  # pragma: no cover


def scoped_teaching_assignments(user: User) -> Select:
    """Teaching assignments this user may see.

    A teacher sees their own. Who else teaches what is the admin's business,
    and a staff directory of assignments is not something §5.2 grants.
    """
    stmt = select(TeachingAssignment).where(TeachingAssignment.school_id == user.school_id)

    if user.role in SCHOOL_WIDE_ROLES:
        return stmt

    if user.role is UserRole.TEACHER:
        return stmt.where(TeachingAssignment.teacher_user_id == user.id)

    return stmt.where(False)


def scoped_class_teachers(user: User) -> Select:
    stmt = select(ClassTeacher).where(ClassTeacher.school_id == user.school_id)

    if user.role in SCHOOL_WIDE_ROLES:
        return stmt

    if user.role is UserRole.TEACHER:
        return stmt.where(ClassTeacher.teacher_user_id == user.id)

    return stmt.where(False)


def scoped_narrative_entries(user: User, academic_session_id: uuid.UUID | None = None) -> Select:
    """Written passages this user may see.

    A teacher sees the narrative of every pupil in a class they teach into,
    not only the sections they write. That is deliberate: §8.2 lets a teacher
    copy a section from the previous pupil, and a specialist writing one
    curriculum area needs to see what the class teacher wrote about the same
    child to avoid contradicting it.

    Note what this does **not** grant. Seeing a passage and being allowed to
    write it are different questions, and `policy.writable_narrative_sections`
    answers the second one per section (D15).
    """
    stmt = select(NarrativeEntry).where(NarrativeEntry.school_id == user.school_id)

    if user.role in SCHOOL_WIDE_ROLES:
        return stmt

    if user.role is UserRole.TEACHER:
        return stmt.where(
            NarrativeEntry.pupil_id.in_(
                scoped_pupils(user, academic_session_id).with_only_columns(Pupil.id)
            )
        )

    # A parent reads the narrative off the published report (§9), never here.
    return stmt.where(False)


def scoped_attendance(user: User, academic_session_id: uuid.UUID | None = None) -> Select:
    """Attendance rows this user may see.

    Scoped through the pupil rather than through `class_teachers`: a subject
    teacher may read a class's attendance, and only the class teacher may
    write it (§5.2, `policy.can_record_attendance_and_growth`).
    """
    stmt = select(AttendanceRecord).where(AttendanceRecord.school_id == user.school_id)

    if user.role in SCHOOL_WIDE_ROLES:
        return stmt

    if user.role is UserRole.TEACHER:
        return stmt.where(
            AttendanceRecord.pupil_id.in_(
                scoped_pupils(user, academic_session_id).with_only_columns(Pupil.id)
            )
        )

    return stmt.where(False)


def scoped_growth(user: User, academic_session_id: uuid.UUID | None = None) -> Select:
    """Height and weight rows this user may see (§4.7)."""
    stmt = select(GrowthRecord).where(GrowthRecord.school_id == user.school_id)

    if user.role in SCHOOL_WIDE_ROLES:
        return stmt

    if user.role is UserRole.TEACHER:
        return stmt.where(
            GrowthRecord.pupil_id.in_(
                scoped_pupils(user, academic_session_id).with_only_columns(Pupil.id)
            )
        )

    return stmt.where(False)


def scoped_result_entries(user: User, academic_session_id: uuid.UUID | None = None) -> Select:
    """Score rows this user may see.

    A teacher sees the rows of the class-subjects they are assigned to teach,
    and no others — being class teacher of 4A does not reveal 4A Mathematics.
    A parent reaches scores through their child's published report (§9), never
    through this table, so the filter here is `false` rather than a join.
    """
    stmt = select(ResultEntry).where(ResultEntry.school_id == user.school_id)

    if user.role in SCHOOL_WIDE_ROLES:
        return stmt

    if user.role is UserRole.TEACHER:
        return stmt.where(
            ResultEntry.class_subject_id.in_(
                scoped_class_subjects(user, academic_session_id).with_only_columns(ClassSubject.id)
            )
        )

    return stmt.where(False)


def scoped_class_term_status(user: User, academic_session_id: uuid.UUID | None = None) -> Select:
    """Workflow state this user may see.

    A teacher sees the state of any class they teach into, not only the one
    they are class teacher of: a subject teacher needs to know the sheet has
    been submitted, or the grid would offer them cells that will not save.
    """
    stmt = select(ClassTermStatus).where(ClassTermStatus.school_id == user.school_id)

    if user.role in SCHOOL_WIDE_ROLES:
        return stmt

    if user.role is UserRole.TEACHER:
        return stmt.where(
            ClassTermStatus.class_id.in_(class_ids_taught_by(user, academic_session_id))
        )

    return stmt.where(False)


def scoped_users(user: User) -> Select:
    """Accounts this user may see.

    `users` is the one tenant table the router scan exempts, because the auth
    layer scopes it rather than a row filter. The admin surface still needs a
    school-filtered query, and it belongs here with the others rather than
    inline in a service.
    """
    stmt = select(User).where(User.school_id == user.school_id)

    if user.role in SCHOOL_WIDE_ROLES:
        return stmt

    # Everyone else sees exactly themselves, which /auth/me already serves.
    return stmt.where(User.id == user.id)
