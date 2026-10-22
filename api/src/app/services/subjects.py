"""Subjects, what each class offers, and who teaches it
(ARCHITECTURE.md §1.5, §4.3).

R7 lives here: a subject with `is_group = true` is a heading on the card and
can never carry a score, so it can never be offered to a class. The spec says
to enforce that in the service layer and test it, which is what the two guards
below do — one when a subject is offered, one when an existing subject is
turned into a group.
"""

import logging
import uuid
from collections.abc import Sequence

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import scope
from app.models import (
    AuditAction,
    Class,
    ClassSubject,
    ClassTeacher,
    ResultEntry,
    Subject,
    TeachingAssignment,
    User,
    UserRole,
)
from app.services import academic, audit
from app.services.errors import Conflict, Invalid
from app.services.support import all_of, integrity_guard, one_or_404

logger = logging.getLogger(__name__)

SUBJECT_FIELDS = (
    "name",
    "parent_subject_id",
    "is_group",
    "is_specialist",
    "display_order",
    "is_active",
)

# Fields `update_subject` will act on. A whitelist, so a future schema column
# cannot be written through this endpoint by accident.
SUBJECT_UPDATABLE = frozenset(
    {"name", "parent_subject_id", "is_group", "is_specialist", "display_order", "is_active"}
)


async def list_subjects(
    db: AsyncSession, actor: User, *, include_inactive: bool = False
) -> Sequence[Subject]:
    stmt = scope.scoped_subjects(actor)
    if not include_inactive:
        stmt = stmt.where(Subject.is_active.is_(True))
    return await all_of(db, stmt.order_by(Subject.display_order, Subject.name))


async def get_subject(db: AsyncSession, actor: User, subject_id: uuid.UUID) -> Subject:
    return await one_or_404(
        db, scope.scoped_subjects(actor).where(Subject.id == subject_id), "subject"
    )


async def _check_parent(
    db: AsyncSession, actor: User, parent_subject_id: uuid.UUID | None, *, is_group: bool
) -> None:
    if parent_subject_id is None:
        return
    if is_group:
        # Also a database CHECK (group_has_no_parent); checked here so the
        # admin gets a sentence rather than a constraint name.
        raise Invalid("A group heading cannot sit under another subject.")

    parent = await get_subject(db, actor, parent_subject_id)
    if not parent.is_group:
        raise Invalid(
            f"{parent.name} is not a group heading, so a subject cannot sit under it. "
            "English is the only grouping on the card."
        )


async def create_subject(
    db: AsyncSession,
    actor: User,
    *,
    name: str,
    parent_subject_id: uuid.UUID | None = None,
    is_group: bool = False,
    is_specialist: bool = False,
    display_order: int = 0,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> Subject:
    if is_group and is_specialist:
        raise Invalid("A group heading carries no scores, so it has no teacher to specialise.")

    await _check_parent(db, actor, parent_subject_id, is_group=is_group)

    record = Subject(
        school_id=actor.school_id,
        name=name.strip(),
        parent_subject_id=parent_subject_id,
        is_group=is_group,
        is_specialist=is_specialist,
        display_order=display_order,
    )
    db.add(record)

    async with integrity_guard(db, "A subject with that name already exists."):
        await db.flush()

    await audit.record(
        db,
        school_id=actor.school_id,
        actor_id=actor.id,
        action=AuditAction.SUBJECT_CREATED,
        entity_type="subject",
        entity_id=record.id,
        after=audit.snapshot(record, SUBJECT_FIELDS),
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()
    await db.refresh(record)
    return record


async def update_subject(
    db: AsyncSession,
    actor: User,
    subject_id: uuid.UUID,
    *,
    changes: dict[str, object],
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> Subject:
    """Rename, reorder, retire or regroup a subject.

    §1.5 requires this: "the list must be admin-editable and the display order
    must be configurable". The card leaves blank rows for additions, so the
    school will use it.
    """
    record = await get_subject(db, actor, subject_id)
    before = audit.snapshot(record, SUBJECT_FIELDS)

    unknown = set(changes) - SUBJECT_UPDATABLE
    if unknown:
        raise Invalid(f"Cannot change {', '.join(sorted(unknown))} on a subject.")

    for field, value in changes.items():
        setattr(record, field, value.strip() if field == "name" else value)

    if record.is_group and record.is_specialist:
        raise Invalid("A group heading carries no scores, so it has no teacher to specialise.")
    await _check_parent(db, actor, record.parent_subject_id, is_group=record.is_group)

    if record.is_group and not before["is_group"]:
        # R7 in the other direction: turning a scored subject into a heading
        # would orphan every score already entered against it.
        offered = await db.scalar(
            select(
                exists().where(
                    ClassSubject.subject_id == record.id,
                    ClassSubject.school_id == actor.school_id,
                )
            )
        )
        if offered:
            raise Conflict(
                f"{record.name} is offered to at least one class, so it cannot become a "
                "group heading. Remove it from those classes first."
            )

    if record.parent_subject_id is not None:
        parent_is_self = record.parent_subject_id == record.id
        if parent_is_self:
            raise Invalid("A subject cannot sit under itself.")

    async with integrity_guard(db, "A subject with that name already exists."):
        await db.flush()

    await audit.record(
        db,
        school_id=actor.school_id,
        actor_id=actor.id,
        action=AuditAction.SUBJECT_UPDATED,
        entity_type="subject",
        entity_id=record.id,
        before=before,
        after=audit.snapshot(record, SUBJECT_FIELDS),
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()
    await db.refresh(record)
    return record


# ---------------------------------------------------------------------------
# What a class offers
# ---------------------------------------------------------------------------


async def list_class_subjects(
    db: AsyncSession,
    actor: User,
    class_id: uuid.UUID,
    *,
    academic_session_id: uuid.UUID | None = None,
) -> Sequence[ClassSubject]:
    await academic.get_class(db, actor, class_id)
    session_id = await academic.resolve_session_id(db, actor, academic_session_id)

    return await all_of(
        db,
        scope.scoped_class_subjects(actor)
        .where(
            ClassSubject.class_id == class_id,
            ClassSubject.academic_session_id == session_id,
        )
        .order_by(ClassSubject.display_order),
    )


async def set_class_subjects(
    db: AsyncSession,
    actor: User,
    class_id: uuid.UUID,
    *,
    subject_ids: Sequence[uuid.UUID],
    academic_session_id: uuid.UUID | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> Sequence[ClassSubject]:
    """Replace the set of subjects a class is taught this session.

    A whole-set PUT rather than add/remove calls, because the admin screen is
    a list of checkboxes and a partial save is how a class ends up offering a
    subject nobody noticed.
    """
    klass = await academic.get_class(db, actor, class_id)
    session_id = await academic.resolve_session_id(db, actor, academic_session_id)

    wanted = list(dict.fromkeys(subject_ids))  # de-duplicate, keep order

    subjects = {
        subject.id: subject
        for subject in await all_of(db, scope.scoped_subjects(actor).where(Subject.id.in_(wanted)))
    }
    missing = [sid for sid in wanted if sid not in subjects]
    if missing:
        raise Invalid("One or more of those subjects does not exist.")

    for subject in subjects.values():
        if subject.is_group:
            # R7. The card prints English as a heading over its five
            # sub-subjects; a heading has no scores and so no entry row.
            raise Invalid(
                f"{subject.name} is a group heading and carries no scores, "
                "so it cannot be offered to a class. Offer its sub-subjects instead."
            )
        if not subject.is_active:
            raise Invalid(f"{subject.name} is retired and cannot be offered to a class.")

    existing = {
        row.subject_id: row
        for row in await all_of(
            db,
            scope.scoped_class_subjects(actor).where(
                ClassSubject.class_id == class_id,
                ClassSubject.academic_session_id == session_id,
            ),
        )
    }

    for subject_id, row in existing.items():
        if subject_id in subjects:
            continue
        if await _has_result_entries(db, row.id):
            name = await db.scalar(
                scope.scoped_subjects(actor)
                .with_only_columns(Subject.name)
                .where(Subject.id == subject_id)
            )
            raise Conflict(
                f"Scores have already been entered for {name} in {klass.name}, so it "
                "cannot be removed. Retire the subject instead to keep the record."
            )
        await db.delete(row)

    for position, subject_id in enumerate(wanted):
        row = existing.get(subject_id)
        if row is None:
            row = ClassSubject(
                school_id=actor.school_id,
                class_id=class_id,
                subject_id=subject_id,
                academic_session_id=session_id,
            )
            db.add(row)
        row.display_order = position

    async with integrity_guard(db, "That subject is already offered to this class."):
        await db.flush()

    await audit.record(
        db,
        school_id=actor.school_id,
        actor_id=actor.id,
        action=AuditAction.CLASS_SUBJECTS_SET,
        entity_type="class",
        entity_id=class_id,
        before={"subject_ids": [str(sid) for sid in existing]},
        after={"subject_ids": [str(sid) for sid in wanted]},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()

    return await list_class_subjects(db, actor, class_id, academic_session_id=session_id)


async def _has_result_entries(db: AsyncSession, class_subject_id: uuid.UUID) -> bool:
    return bool(
        await db.scalar(select(exists().where(ResultEntry.class_subject_id == class_subject_id)))
    )


# ---------------------------------------------------------------------------
# Who teaches it
# ---------------------------------------------------------------------------


async def _teacher(db: AsyncSession, actor: User, teacher_user_id: uuid.UUID) -> User:
    record = await one_or_404(
        db, scope.scoped_users(actor).where(User.id == teacher_user_id), "user"
    )
    if record.role is not UserRole.TEACHER:
        raise Invalid(f"{record.full_name} is not a teacher, so cannot be assigned a class.")
    if not record.is_active:
        raise Invalid(f"{record.full_name}'s account is deactivated.")
    return record


async def set_class_subject_teacher(
    db: AsyncSession,
    actor: User,
    class_subject_id: uuid.UUID,
    *,
    teacher_user_id: uuid.UUID,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> TeachingAssignment:
    """Assign the one teacher who enters scores for this class-subject (§4.3)."""
    class_subject = await one_or_404(
        db,
        scope.scoped_class_subjects(actor).where(ClassSubject.id == class_subject_id),
        "class subject",
    )
    teacher = await _teacher(db, actor, teacher_user_id)

    record = await db.scalar(
        scope.scoped_teaching_assignments(actor).where(
            TeachingAssignment.class_subject_id == class_subject.id
        )
    )
    before = None if record is None else {"teacher_user_id": str(record.teacher_user_id)}

    if record is None:
        record = TeachingAssignment(
            school_id=actor.school_id,
            class_subject_id=class_subject.id,
            teacher_user_id=teacher.id,
        )
        db.add(record)
    else:
        record.teacher_user_id = teacher.id

    async with integrity_guard(db, "That class subject already has a teacher."):
        await db.flush()

    await audit.record(
        db,
        school_id=actor.school_id,
        actor_id=actor.id,
        action=AuditAction.CLASS_SUBJECT_TEACHER_SET,
        entity_type="class_subject",
        entity_id=class_subject.id,
        before=before,
        after={"teacher_user_id": str(teacher.id)},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()
    await db.refresh(record)
    return record


async def set_class_teacher(
    db: AsyncSession,
    actor: User,
    class_id: uuid.UUID,
    *,
    teacher_user_id: uuid.UUID,
    academic_session_id: uuid.UUID | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> ClassTeacher:
    """Set the class teacher for one class this session (§4.3).

    Consequential beyond its size: §5.2 hands this person the narrative, the
    attendance and growth records, the class teacher's comment and the
    submission gate for every pupil in the class.
    """
    await academic.get_class(db, actor, class_id)
    session_id = await academic.resolve_session_id(db, actor, academic_session_id)
    teacher = await _teacher(db, actor, teacher_user_id)

    record = await db.scalar(
        scope.scoped_class_teachers(actor).where(
            ClassTeacher.class_id == class_id,
            ClassTeacher.academic_session_id == session_id,
        )
    )
    before = None if record is None else {"teacher_user_id": str(record.teacher_user_id)}

    if record is None:
        record = ClassTeacher(
            school_id=actor.school_id,
            class_id=class_id,
            academic_session_id=session_id,
            teacher_user_id=teacher.id,
        )
        db.add(record)
    else:
        record.teacher_user_id = teacher.id

    async with integrity_guard(db, "That class already has a class teacher this session."):
        await db.flush()

    await audit.record(
        db,
        school_id=actor.school_id,
        actor_id=actor.id,
        action=AuditAction.CLASS_TEACHER_SET,
        entity_type="class",
        entity_id=class_id,
        before=before,
        after={"teacher_user_id": str(teacher.id), "academic_session_id": str(session_id)},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()
    await db.refresh(record)
    return record


async def count_class_subjects(db: AsyncSession, actor: User, *, academic_session_id: uuid.UUID):
    """Offered subjects per class, for the setup checklist."""
    stmt = (
        scope.scoped_class_subjects(actor)
        .with_only_columns(ClassSubject.class_id, func.count(ClassSubject.id))
        .where(ClassSubject.academic_session_id == academic_session_id)
        .group_by(ClassSubject.class_id)
    )
    return {row[0]: row[1] for row in (await db.execute(stmt)).all()}


async def class_subjects_without_a_teacher(
    db: AsyncSession, actor: User, *, academic_session_id: uuid.UUID
) -> Sequence[tuple[str, str]]:
    """(class name, subject name) for every offering nobody is assigned to.

    The scope filter arrives as a subquery of ids rather than by replacing the
    columns of `scoped_class_subjects`: `with_only_columns` on columns of
    other tables drops `class_subjects` from the FROM clause, which turns the
    joins into a cartesian product. Keeping the scoped query intact and
    filtering on its ids is both correct and obviously correct.
    """
    scoped_ids = scope.scoped_class_subjects(actor).with_only_columns(ClassSubject.id)

    stmt = (
        select(Class.name, Subject.name)
        .select_from(ClassSubject)
        .join(Class, Class.id == ClassSubject.class_id)
        .join(Subject, Subject.id == ClassSubject.subject_id)
        .where(
            ClassSubject.id.in_(scoped_ids),
            ClassSubject.academic_session_id == academic_session_id,
            ~exists().where(TeachingAssignment.class_subject_id == ClassSubject.id),
        )
        .order_by(Class.level_order, Class.name, Subject.display_order)
    )
    return [(row[0], row[1]) for row in (await db.execute(stmt)).all()]
