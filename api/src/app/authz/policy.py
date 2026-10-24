"""Capability: may this caller perform this action (ARCHITECTURE.md §5.2).

The §5.2 matrix, encoded once. Routers ask these questions; they do not
re-derive the answers, and no answer appears in two places.

Actions split into two kinds:

- **Unscoped** — "may an admin manage subjects at all". A role question,
  answered by `can`.
- **Scoped** — "may *this* teacher enter scores for *that* class-subject".
  These need the database, because the teacher/class relationship lives in
  `class_teachers` and `teaching_assignments` rather than in `users.role`.
"""

import enum
import uuid

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import scope
from app.models import (
    ClassSubject,
    ClassTeacher,
    NarrativeSection,
    NarrativeSectionAssignment,
    TeachingAssignment,
    User,
    UserRole,
)


class Action(enum.StrEnum):
    """One member per row of the §5.2 matrix."""

    # Admin setup
    MANAGE_ACADEMIC_STRUCTURE = "manage_academic_structure"
    MANAGE_USERS = "manage_users"
    MANAGE_ASSESSMENT_CONFIG = "manage_assessment_config"

    # Teaching
    ENTER_SCORES = "enter_scores"
    WRITE_NARRATIVE = "write_narrative"
    RECORD_ATTENDANCE_AND_GROWTH = "record_attendance_and_growth"
    SUBMIT_CLASS = "submit_class"

    # Head teacher
    REVIEW_CLASS = "review_class"
    SET_HEAD_TEACHER_REMARK = "set_head_teacher_remark"

    # Admin publication
    PUBLISH = "publish"
    EDIT_AFTER_PUBLICATION = "edit_after_publication"

    # Parent
    VIEW_OWN_CHILDREN_REPORTS = "view_own_children_reports"
    ACKNOWLEDGE_REPORT = "acknowledge_report"

    # Shared by everyone who writes about a pupil
    #
    # §5.2's third row gives the comment bank to the admin, and that row is
    # about *managing* it. §4.6 and §8.2 require a class teacher to **use** it:
    # "treat the comment bank as core, not optional", with a phrase-bank button
    # beside every one of the sixteen sections. Reading the phrases and editing
    # them are different actions, so they are two entries here
    # (docs/DECISIONS.md D55).
    USE_COMMENT_BANK = "use_comment_bank"

    # Audit
    VIEW_AUDIT_LOG = "view_audit_log"


# The matrix, as data. A role may perform an action only if it appears here —
# and for the scoped actions, only if the matching `can_*` check also passes.
#
# Read this table against §5.2 directly; it is deliberately the same shape.
ROLE_ACTIONS: dict[UserRole, frozenset[Action]] = {
    UserRole.ADMIN: frozenset(
        {
            Action.MANAGE_ACADEMIC_STRUCTURE,
            Action.MANAGE_USERS,
            Action.MANAGE_ASSESSMENT_CONFIG,
            Action.PUBLISH,
            Action.EDIT_AFTER_PUBLICATION,
            Action.USE_COMMENT_BANK,
            Action.VIEW_AUDIT_LOG,
        }
    ),
    UserRole.HEAD_TEACHER: frozenset(
        {
            Action.REVIEW_CLASS,
            Action.SET_HEAD_TEACHER_REMARK,
            # The bank carries 'head_teacher'-scoped phrases for the remark.
            Action.USE_COMMENT_BANK,
            # Read-only; the admin's is the full surface.
            Action.VIEW_AUDIT_LOG,
        }
    ),
    UserRole.TEACHER: frozenset(
        {
            Action.ENTER_SCORES,
            Action.WRITE_NARRATIVE,
            Action.RECORD_ATTENDANCE_AND_GROWTH,
            Action.SUBMIT_CLASS,
            Action.USE_COMMENT_BANK,
        }
    ),
    UserRole.PARENT: frozenset(
        {
            Action.VIEW_OWN_CHILDREN_REPORTS,
            Action.ACKNOWLEDGE_REPORT,
        }
    ),
}

# Actions whose role grant is necessary but not sufficient: a teacher may
# enter scores, but only for their own class-subjects. Listing them here means
# a new scoped action cannot be added without deciding what scopes it.
SCOPED_ACTIONS = frozenset(
    {
        Action.ENTER_SCORES,
        Action.WRITE_NARRATIVE,
        Action.RECORD_ATTENDANCE_AND_GROWTH,
        Action.SUBMIT_CLASS,
        Action.VIEW_OWN_CHILDREN_REPORTS,
        Action.ACKNOWLEDGE_REPORT,
    }
)


def can(user: User, action: Action) -> bool:
    """Whether the user's role permits the action at all.

    For a scoped action this is only the first half of the question; the
    matching `can_*` below answers the rest. Never use this alone to authorise
    a scoped action.
    """
    if not user.is_active:
        return False
    return action in ROLE_ACTIONS.get(user.role, frozenset())


def audit_log_is_read_only(user: User) -> bool:
    """§5.2 gives the head teacher the audit log read-only."""
    return user.role is UserRole.HEAD_TEACHER


# ---------------------------------------------------------------------------
# Scoped checks
# ---------------------------------------------------------------------------


async def can_enter_scores(db: AsyncSession, user: User, class_subject_id: uuid.UUID) -> bool:
    """§5.2: own class-subjects, for class teacher and subject teacher alike.

    Being class teacher of 4A does **not** grant score entry for 4A
    Mathematics — that belongs to whoever is assigned to teach it. The table
    reads "own class-subjects" for both columns, not "own class".
    """
    if not can(user, Action.ENTER_SCORES):
        return False

    return bool(
        await db.scalar(
            select(
                exists().where(
                    TeachingAssignment.class_subject_id == class_subject_id,
                    TeachingAssignment.teacher_user_id == user.id,
                    TeachingAssignment.school_id == user.school_id,
                )
            )
        )
    )


async def is_class_teacher_of(
    db: AsyncSession,
    user: User,
    class_id: uuid.UUID,
    academic_session_id: uuid.UUID | None = None,
) -> bool:
    session_id = (
        academic_session_id
        if academic_session_id is not None
        else scope.current_session_id(user.school_id)
    )
    return bool(
        await db.scalar(
            select(
                exists().where(
                    ClassTeacher.class_id == class_id,
                    ClassTeacher.teacher_user_id == user.id,
                    ClassTeacher.school_id == user.school_id,
                    ClassTeacher.academic_session_id == session_id,
                )
            )
        )
    )


async def can_write_narrative(
    db: AsyncSession,
    user: User,
    class_id: uuid.UUID,
    section_id: uuid.UUID,
    academic_session_id: uuid.UUID | None = None,
) -> bool:
    """B1 as settled in docs/DECISIONS.md D15.

    A section may be assigned to a specialist for a given class. Where an
    assignment exists, only that teacher writes it. Where none exists, the
    class teacher does — which covers the behavioural sections B-J and every
    curriculum area the school has not handed to a specialist.

    Note this needs no knowledge of *which* sections are specialist. Absence
    of an assignment is the rule, so the common case needs no configuration
    and the school can change its mind without a code change.
    """
    if not can(user, Action.WRITE_NARRATIVE):
        return False

    session_id = (
        academic_session_id
        if academic_session_id is not None
        else scope.current_session_id(user.school_id)
    )

    assignee = await db.scalar(
        select(NarrativeSectionAssignment.teacher_user_id).where(
            NarrativeSectionAssignment.school_id == user.school_id,
            NarrativeSectionAssignment.class_id == class_id,
            NarrativeSectionAssignment.section_id == section_id,
            NarrativeSectionAssignment.academic_session_id == session_id,
        )
    )

    if assignee is not None:
        return assignee == user.id

    return await is_class_teacher_of(db, user, class_id, academic_session_id)


async def can_record_attendance_and_growth(
    db: AsyncSession,
    user: User,
    class_id: uuid.UUID,
    academic_session_id: uuid.UUID | None = None,
) -> bool:
    """§5.2: own class, and only as class teacher.

    A subject teacher who happens to teach the class does not record its
    attendance.
    """
    if not can(user, Action.RECORD_ATTENDANCE_AND_GROWTH):
        return False
    return await is_class_teacher_of(db, user, class_id, academic_session_id)


async def can_submit_class(
    db: AsyncSession,
    user: User,
    class_id: uuid.UUID,
    academic_session_id: uuid.UUID | None = None,
) -> bool:
    """§5.2: own class. R10's completeness gate is a separate question — this
    answers only who is allowed to press the button."""
    if not can(user, Action.SUBMIT_CLASS):
        return False
    return await is_class_teacher_of(db, user, class_id, academic_session_id)


async def can_view_pupil(db: AsyncSession, user: User, pupil_id: uuid.UUID) -> bool:
    """Whether this pupil is inside the caller's scope at all."""
    visible = scope.scoped_pupils(user).subquery()
    return bool(await db.scalar(select(exists().where(visible.c.id == pupil_id))))


async def can_view_class_subject(db: AsyncSession, user: User, class_subject_id: uuid.UUID) -> bool:
    visible = scope.scoped_class_subjects(user).subquery()
    return bool(await db.scalar(select(exists().where(visible.c.id == class_subject_id))))


async def can_acknowledge_report(db: AsyncSession, user: User, term_report_id: uuid.UUID) -> bool:
    """A parent acknowledges their own child's **published** report.

    `scoped_term_reports` already carries the published filter, so a withheld
    report is simply not there to acknowledge.
    """
    if not can(user, Action.ACKNOWLEDGE_REPORT):
        return False

    visible = scope.scoped_term_reports(user).subquery()
    return bool(await db.scalar(select(exists().where(visible.c.id == term_report_id))))


async def writable_narrative_sections(
    db: AsyncSession,
    user: User,
    class_id: uuid.UUID,
    academic_session_id: uuid.UUID | None = None,
) -> set[uuid.UUID]:
    """Every section of one class this user may write (B1, D15).

    `can_write_narrative` answers the same question one section at a time, and
    the narrative screen needs all sixteen answers at once — sixteen round
    trips to render one page would be absurd. The two must agree, so this is
    the same two rules in the same order:

    - a section assigned to this user, they write;
    - every section with no assignment falls to the class teacher.

    A section assigned to *somebody else* is writable by neither the class
    teacher nor anyone but that person, which is the whole point of the
    assignment.
    """
    if not can(user, Action.WRITE_NARRATIVE):
        return set()

    session_id = (
        academic_session_id
        if academic_session_id is not None
        else scope.current_session_id(user.school_id)
    )

    mine = set(
        (
            await db.execute(
                scope.narrative_section_ids_assigned_to(user, class_id, academic_session_id)
            )
        )
        .scalars()
        .all()
    )

    if not await is_class_teacher_of(db, user, class_id, academic_session_id):
        return mine

    assigned_to_anyone = set(
        (
            await db.execute(
                select(NarrativeSectionAssignment.section_id).where(
                    NarrativeSectionAssignment.school_id == user.school_id,
                    NarrativeSectionAssignment.class_id == class_id,
                    NarrativeSectionAssignment.academic_session_id == session_id,
                )
            )
        )
        .scalars()
        .all()
    )

    unassigned = (
        set(
            (
                await db.execute(
                    scope.scoped_narrative_sections(user)
                    .where(NarrativeSection.is_active.is_(True))
                    .with_only_columns(NarrativeSection.id)
                )
            )
            .scalars()
            .all()
        )
        - assigned_to_anyone
    )

    return mine | unassigned


async def teaches_any_class_subject(db: AsyncSession, user: User) -> bool:
    """Whether this teacher has any assignment at all.

    Useful for the empty state: a teacher with no assignments should be told
    so, not shown an empty grid with no explanation.
    """
    return bool(
        await db.scalar(
            select(
                exists().where(
                    TeachingAssignment.teacher_user_id == user.id,
                    TeachingAssignment.school_id == user.school_id,
                )
            )
        )
    )


async def class_subject_belongs_to_class(
    db: AsyncSession, class_subject_id: uuid.UUID, class_id: uuid.UUID
) -> bool:
    """Guards the path where a caller supplies both and they disagree."""
    return bool(
        await db.scalar(
            select(
                exists().where(
                    ClassSubject.id == class_subject_id,
                    ClassSubject.class_id == class_id,
                )
            )
        )
    )
