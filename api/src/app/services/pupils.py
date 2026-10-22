"""Pupils and their enrolment (ARCHITECTURE.md §4.1, §4.2).

Entered by hand in the platform — N8, answered: there is no CSV import. That
makes this the slowest part of go-live, roughly five hundred records typed
once, and it is why the list below supports search and paging rather than
returning the whole roll.
"""

import datetime as dt
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import scope
from app.models import AuditAction, Class, Enrollment, House, Pupil, User
from app.services import academic, audit
from app.services.errors import Invalid
from app.services.support import all_of, integrity_guard, one_or_404

logger = logging.getLogger(__name__)

# No names and no admission number: CLAUDE.md keeps a pupil's identity out of
# the audit log, and the id in `entity_id` resolves for anyone entitled to.
PUPIL_AUDIT_FIELDS = ("house_id", "sex", "is_active")

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


@dataclass(frozen=True)
class PupilPage:
    items: Sequence[Pupil]
    total: int
    limit: int
    offset: int


async def list_pupils(
    db: AsyncSession,
    actor: User,
    *,
    class_id: uuid.UUID | None = None,
    academic_session_id: uuid.UUID | None = None,
    search: str | None = None,
    include_inactive: bool = False,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> PupilPage:
    """Pupils this caller may see, filtered and paged.

    `class_id` filters through `enrollments`, because a pupil's class is a
    property of their enrolment in a session, not of the pupil (§4.2) — which
    is what makes last year's cards still say last year's class.
    """
    limit = max(1, min(limit, MAX_PAGE_SIZE))
    offset = max(0, offset)

    stmt = scope.scoped_pupils(actor)
    if not include_inactive:
        stmt = stmt.where(Pupil.is_active.is_(True))

    if class_id is not None:
        await academic.get_class(db, actor, class_id)
        session_id = await academic.resolve_session_id(db, actor, academic_session_id)
        stmt = stmt.where(
            Pupil.id.in_(
                scope.scoped_enrollments(actor)
                .with_only_columns(Enrollment.pupil_id)
                .where(
                    Enrollment.class_id == class_id,
                    Enrollment.academic_session_id == session_id,
                )
            )
        )

    if search:
        needle = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                Pupil.first_name.ilike(needle),
                Pupil.last_name.ilike(needle),
                Pupil.middle_name.ilike(needle),
                Pupil.admission_number.ilike(needle),
            )
        )

    total = await db.scalar(stmt.with_only_columns(func.count(Pupil.id)).order_by(None)) or 0
    items = await all_of(
        db,
        stmt.order_by(Pupil.last_name, Pupil.first_name).limit(limit).offset(offset),
    )
    return PupilPage(items=items, total=total, limit=limit, offset=offset)


async def get_pupil(db: AsyncSession, actor: User, pupil_id: uuid.UUID) -> Pupil:
    return await one_or_404(db, scope.scoped_pupils(actor).where(Pupil.id == pupil_id), "pupil")


async def create_pupil(
    db: AsyncSession,
    actor: User,
    *,
    admission_number: str,
    first_name: str,
    last_name: str,
    middle_name: str | None = None,
    sex: str | None = None,
    date_of_birth: dt.date | None = None,
    house_id: uuid.UUID | None = None,
    class_id: uuid.UUID | None = None,
    joined_on: dt.date | None = None,
    academic_session_id: uuid.UUID | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> Pupil:
    """Add a pupil, optionally enrolling them into a class at the same time.

    `class_id` is optional so a roll can be typed before the classes are
    finalised, but a pupil with no enrolment appears in nothing — no class
    list, no score grid, no report. `setup.term_readiness` reports them.
    """
    admission_number = admission_number.strip()
    if not admission_number:
        raise Invalid("Give an admission number. It identifies the pupil on every card.")
    if not first_name.strip() or not last_name.strip():
        raise Invalid("Give the pupil's first and last name.")
    if sex is not None and sex not in ("M", "F"):
        raise Invalid("Sex must be M or F, as the card records it.")

    if house_id is not None:
        await one_or_404(db, scope.scoped_houses(actor).where(House.id == house_id), "house")

    record = Pupil(
        school_id=actor.school_id,
        admission_number=admission_number,
        first_name=first_name.strip(),
        middle_name=(middle_name or "").strip() or None,
        last_name=last_name.strip(),
        sex=sex,
        date_of_birth=date_of_birth,
        house_id=house_id,
    )
    db.add(record)

    # The number, not the name: a collision message must not confirm which
    # child already holds it.
    async with integrity_guard(db, "A pupil with that admission number already exists."):
        await db.flush()

    await audit.record(
        db,
        school_id=actor.school_id,
        actor_id=actor.id,
        action=AuditAction.PUPIL_CREATED,
        entity_type="pupil",
        entity_id=record.id,
        after=audit.snapshot(record, PUPIL_AUDIT_FIELDS),
        ip_address=ip_address,
        user_agent=user_agent,
    )

    if class_id is not None:
        await _enrol(
            db,
            actor,
            record,
            class_id=class_id,
            joined_on=joined_on,
            academic_session_id=academic_session_id,
        )

    await db.commit()
    await db.refresh(record)
    return record


async def set_enrollment(
    db: AsyncSession,
    actor: User,
    pupil_id: uuid.UUID,
    *,
    class_id: uuid.UUID,
    joined_on: dt.date | None = None,
    academic_session_id: uuid.UUID | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> Enrollment:
    """Place a pupil in a class for a session, or move them to another.

    Not in §7's list, which assumed enrolment happened with pupil creation.
    It has to exist: a pupil typed in before the classes were settled needs
    placing, and pupils move class mid-year. Recorded in docs/DECISIONS.md.
    """
    pupil = await get_pupil(db, actor, pupil_id)
    record = await _enrol(
        db,
        actor,
        pupil,
        class_id=class_id,
        joined_on=joined_on,
        academic_session_id=academic_session_id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()
    await db.refresh(record)
    return record


async def _enrol(
    db: AsyncSession,
    actor: User,
    pupil: Pupil,
    *,
    class_id: uuid.UUID,
    joined_on: dt.date | None,
    academic_session_id: uuid.UUID | None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> Enrollment:
    klass = await academic.get_class(db, actor, class_id)
    if not klass.is_active:
        raise Invalid(f"{klass.name} is not an active class.")

    session_id = await academic.resolve_session_id(db, actor, academic_session_id)
    academic_record = await academic.get_session_record(db, actor, session_id)

    joined = joined_on or academic_record.starts_on
    if not (academic_record.starts_on <= joined <= academic_record.ends_on):
        raise Invalid(
            f"The joining date must fall inside {academic_record.name}, which runs from "
            f"{academic_record.starts_on.isoformat()} to {academic_record.ends_on.isoformat()}."
        )

    record = await db.scalar(
        scope.scoped_enrollments(actor).where(
            Enrollment.pupil_id == pupil.id,
            Enrollment.academic_session_id == session_id,
        )
    )
    before = None if record is None else {"class_id": str(record.class_id)}

    if record is None:
        record = Enrollment(
            school_id=actor.school_id,
            pupil_id=pupil.id,
            class_id=class_id,
            academic_session_id=session_id,
            joined_on=joined,
        )
        db.add(record)
    else:
        record.class_id = class_id
        record.joined_on = joined

    async with integrity_guard(db, "That pupil is already enrolled for this session."):
        await db.flush()

    await audit.record(
        db,
        school_id=actor.school_id,
        actor_id=actor.id,
        action="enrollment.set",
        entity_type="pupil",
        entity_id=pupil.id,
        before=before,
        after={"class_id": str(class_id), "academic_session_id": str(session_id)},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    return record


async def count_enrolled_per_class(
    db: AsyncSession, actor: User, *, academic_session_id: uuid.UUID
) -> dict[uuid.UUID, int]:
    """Pupils per class, for the checklist and the card's "No. in Class"."""
    stmt = (
        scope.scoped_enrollments(actor)
        .with_only_columns(Enrollment.class_id, func.count(Enrollment.id))
        .where(Enrollment.academic_session_id == academic_session_id)
        .group_by(Enrollment.class_id)
    )
    return {row[0]: row[1] for row in (await db.execute(stmt)).all()}


async def count_unenrolled(db: AsyncSession, actor: User, *, academic_session_id: uuid.UUID) -> int:
    """Active pupils with no place in the session — invisible to everything."""
    enrolled = (
        scope.scoped_enrollments(actor)
        .with_only_columns(Enrollment.pupil_id)
        .where(Enrollment.academic_session_id == academic_session_id)
    )
    return (
        await db.scalar(
            scope.scoped_pupils(actor)
            .with_only_columns(func.count(Pupil.id))
            .where(Pupil.is_active.is_(True), Pupil.id.notin_(enrolled))
        )
        or 0
    )


async def classes_with_no_pupils(
    db: AsyncSession, actor: User, *, academic_session_id: uuid.UUID
) -> Sequence[str]:
    enrolled = (
        scope.scoped_enrollments(actor)
        .with_only_columns(Enrollment.class_id)
        .where(Enrollment.academic_session_id == academic_session_id)
    )
    rows = await all_of(
        db,
        scope.scoped_classes(actor)
        .with_only_columns(Class.name)
        .where(Class.is_active.is_(True), Class.id.notin_(enrolled))
        .order_by(Class.level_order),
    )
    return list(rows)
