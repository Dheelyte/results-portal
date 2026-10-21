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

from sqlalchemy import Select, select

from app.models import (
    AcademicSession,
    Class,
    ClassSubject,
    ClassTeacher,
    Enrollment,
    GuardianPupil,
    NarrativeSectionAssignment,
    PublicationState,
    Pupil,
    TeachingAssignment,
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
