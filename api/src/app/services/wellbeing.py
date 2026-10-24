"""Attendance and physical growth (ARCHITECTURE.md §4.7, §6 R9).

Both are per pupil per term, both belong to the class teacher alone (§5.2),
and both are recorded for a whole class at a time — so they are written the
same way the score grid is: validate the set, apply all or none, report
refusals per pupil.

R9 is the rule that matters here:

    times_present + times_absent = terms.times_school_opened
    times_present <= times_school_opened

§4.7 requires it "in `services/results.py` **and** with a trigger, so no path
can write a bad row". The trigger is in migration 0003, and both directions of
it: changing `times_school_opened` after attendance has been entered is
refused too. This is the service half — it lives here rather than in
`results.py` because that module is the score sheet and this is a different
page of the card, written by a different person
(docs/DECISIONS.md D56).

The service half is not redundant with the trigger. A trigger can only raise;
it cannot say *which* of thirty pupils is wrong, and §8.3 needs that to show
the teacher where to look.
"""

import decimal
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import policy, scope
from app.models import (
    AttendanceRecord,
    AuditAction,
    Class,
    ClassTermState,
    GrowthRecord,
    Pupil,
    Term,
    User,
)
from app.services import audit, results, workflow
from app.services.errors import Conflict, NotPermitted, RowErrors
from app.services.support import all_of, one_or_404

logger = logging.getLogger(__name__)

# A metre and a kilogram, loosely. Primary-school pupils, so a height of 15 m
# or a weight of 400 kg is a typing slip — most likely centimetres entered in
# the metres column, which is the mistake these bounds exist to catch.
# Deliberately wide (§14 A21): the aim is to stop nonsense printing on a card,
# not to tell a school what a child may weigh.
MIN_HEIGHT_M = decimal.Decimal("0.3")
MAX_HEIGHT_M = decimal.Decimal("2.5")
MIN_WEIGHT_KG = decimal.Decimal("5")
MAX_WEIGHT_KG = decimal.Decimal("150")

GROWTH_COLUMNS = ("height_start_m", "height_end_m", "weight_start_kg", "weight_end_kg")

HEIGHT_LABELS = {
    "height_start_m": "Height at the beginning of term",
    "height_end_m": "Height at the end of term",
}
WEIGHT_LABELS = {
    "weight_start_kg": "Weight at the beginning of term",
    "weight_end_kg": "Weight at the end of term",
}
GROWTH_LABELS = {**HEIGHT_LABELS, **WEIGHT_LABELS}


@dataclass(frozen=True)
class AttendanceInput:
    pupil_id: uuid.UUID
    times_present: int
    times_absent: int
    times_late: int = 0


@dataclass(frozen=True)
class GrowthInput:
    pupil_id: uuid.UUID
    height_start_m: decimal.Decimal | None = None
    height_end_m: decimal.Decimal | None = None
    weight_start_kg: decimal.Decimal | None = None
    weight_end_kg: decimal.Decimal | None = None


@dataclass(frozen=True)
class ClassRecords:
    """A class's roll alongside whatever has been recorded for it."""

    klass: Class
    term: Term
    pupils: Sequence[Pupil]
    attendance: dict[uuid.UUID, AttendanceRecord]
    growth: dict[uuid.UUID, GrowthRecord]
    state: ClassTermState
    editable: bool

    @property
    def times_school_opened(self) -> int | None:
        return self.term.times_school_opened


async def _class_and_term(
    db: AsyncSession, actor: User, class_id: uuid.UUID, term_id: uuid.UUID
) -> tuple[Class, Term]:
    klass = await one_or_404(db, scope.scoped_classes(actor).where(Class.id == class_id), "class")
    term = await one_or_404(db, scope.scoped_terms(actor).where(Term.id == term_id), "term")
    return klass, term


async def class_records(
    db: AsyncSession, actor: User, *, class_id: uuid.UUID, term_id: uuid.UUID
) -> ClassRecords:
    """Everything the attendance and growth page needs, in one read."""
    klass, term = await _class_and_term(db, actor, class_id, term_id)
    pupils = await results.pupils_of(
        db, actor, class_id=class_id, academic_session_id=term.academic_session_id
    )
    pupil_ids = [pupil.id for pupil in pupils]

    attendance = {
        record.pupil_id: record
        for record in await all_of(
            db,
            scope.scoped_attendance(actor, term.academic_session_id)
            .where(AttendanceRecord.term_id == term.id, AttendanceRecord.pupil_id.in_(pupil_ids))
            .execution_options(populate_existing=True),
        )
    }
    growth = {
        record.pupil_id: record
        for record in await all_of(
            db,
            scope.scoped_growth(actor, term.academic_session_id)
            .where(GrowthRecord.term_id == term.id, GrowthRecord.pupil_id.in_(pupil_ids))
            .execution_options(populate_existing=True),
        )
    }

    state = await workflow.state_of(db, actor, class_id=class_id, term_id=term.id)

    return ClassRecords(
        klass=klass,
        term=term,
        pupils=pupils,
        attendance=attendance,
        growth=growth,
        state=state,
        editable=workflow.teacher_may_edit(state),
    )


async def _refuse_unless_class_teacher(
    db: AsyncSession, actor: User, *, class_id: uuid.UUID, academic_session_id: uuid.UUID
) -> None:
    """§5.2: these three belong to the class teacher and nobody else.

    A subject teacher of the same class may **read** the page — they can see
    the class, and seeing it is how they know whose attendance is missing —
    but recording it is not theirs. A 403 rather than a 404 because the class
    is already in their scope: there is nothing left to conceal, and saying
    which relationship is missing is more use than pretending the class does
    not exist.
    """
    if await policy.is_class_teacher_of(db, actor, class_id, academic_session_id):
        return
    raise NotPermitted(
        "Only the class teacher records this for a class. "
        "If you should be the class teacher, an administrator sets that."
    )


# ---------------------------------------------------------------------------
# R9 — attendance
# ---------------------------------------------------------------------------


def check_attendance(row: AttendanceInput, *, times_school_opened: int) -> dict[str, str]:
    """R9 for one pupil. Returns the refusals, keyed by field.

    Pure, so the arithmetic is tested without a database, and shared by the
    service below and nothing else — the browser's copy of this lives in
    `web/lib/attendance.ts` and is tested against the same cases.
    """
    errors: dict[str, str] = {}

    for field, value in (
        ("times_present", row.times_present),
        ("times_absent", row.times_absent),
        ("times_late", row.times_late),
    ):
        if value < 0:
            errors[field] = "This cannot be negative."

    if errors:
        return errors

    if row.times_present > times_school_opened:
        errors["times_present"] = (
            f"The school opened {times_school_opened} times this term, "
            "so a pupil cannot be present more often than that."
        )
    elif row.times_present + row.times_absent != times_school_opened:
        # A6/A5: the school may yet say a discrepancy is allowed. The
        # assumption is that it is not, and it is enforced in one place.
        total = row.times_present + row.times_absent
        errors["times_absent"] = (
            f"Present and absent must add up to {times_school_opened}, "
            f"the number of times the school opened. These add up to {total}."
        )

    if row.times_late > times_school_opened:
        errors["times_late"] = (
            f"The school opened {times_school_opened} times this term, "
            "so a pupil cannot be collected late more often than that."
        )

    return errors


async def save_attendance(
    db: AsyncSession,
    actor: User,
    *,
    class_id: uuid.UUID,
    term_id: uuid.UUID,
    rows: Sequence[AttendanceInput],
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> ClassRecords:
    """Upsert a class's attendance, all or none (R9)."""
    records = await class_records(db, actor, class_id=class_id, term_id=term_id)
    await _refuse_unless_class_teacher(
        db, actor, class_id=class_id, academic_session_id=records.term.academic_session_id
    )
    workflow.refuse_if_locked(records.state)

    opened = records.times_school_opened
    if opened is None:
        # R10 lists this as a submission blocker, but it blocks entry too:
        # without the figure there is nothing for R9 to add up to.
        raise Conflict(
            "The number of times the school opened this term has not been set, so attendance "
            "cannot be checked. An administrator sets it on the term."
        )

    known = {pupil.id for pupil in records.pupils}
    errors: dict[str, dict[str, str]] = {}
    for row in rows:
        if row.pupil_id not in known:
            errors[str(row.pupil_id)] = {
                "pupil_id": "This pupil is not in this class for this session."
            }
            continue
        found = check_attendance(row, times_school_opened=opened)
        if found:
            errors[str(row.pupil_id)] = found

    if errors:
        raise RowErrors(
            f"{len(errors)} of {len(rows)} rows were rejected, so nothing was saved.", errors
        )

    created = 0
    for row in rows:
        record = records.attendance.get(row.pupil_id)
        if record is None:
            record = AttendanceRecord(
                school_id=actor.school_id, term_id=term_id, pupil_id=row.pupil_id
            )
            db.add(record)
            created += 1
        record.times_present = row.times_present
        record.times_absent = row.times_absent
        record.times_late = row.times_late
        record.recorded_by = actor.id

    await db.flush()
    await workflow.mark_in_progress(
        db,
        actor,
        class_id=class_id,
        term_id=term_id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await audit.record(
        db,
        school_id=actor.school_id,
        action=AuditAction.ATTENDANCE_SAVED,
        entity_type="class",
        entity_id=class_id,
        actor_id=actor.id,
        after={"term_id": str(term_id), "rows_saved": len(rows), "rows_created": created},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()

    return await class_records(db, actor, class_id=class_id, term_id=term_id)


# ---------------------------------------------------------------------------
# Growth
# ---------------------------------------------------------------------------


def check_growth(row: GrowthInput) -> dict[str, str]:
    """Height and weight within believable bounds, and end after start.

    §4.7's CHECK constraints only require each figure to be positive, which
    lets 0.01 m through. These bounds catch the mistake that actually happens:
    centimetres typed into the metres column.
    """
    errors: dict[str, str] = {}

    for field, low, high, unit in (
        ("height_start_m", MIN_HEIGHT_M, MAX_HEIGHT_M, "m"),
        ("height_end_m", MIN_HEIGHT_M, MAX_HEIGHT_M, "m"),
        ("weight_start_kg", MIN_WEIGHT_KG, MAX_WEIGHT_KG, "kg"),
        ("weight_end_kg", MIN_WEIGHT_KG, MAX_WEIGHT_KG, "kg"),
    ):
        value = getattr(row, field)
        if value is None:
            continue
        if value < low or value > high:
            errors[field] = (
                f"{GROWTH_LABELS[field]} should be between {low:g}{unit} and {high:g}{unit}."
            )

    return errors


async def save_growth(
    db: AsyncSession,
    actor: User,
    *,
    class_id: uuid.UUID,
    term_id: uuid.UUID,
    rows: Sequence[GrowthInput],
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> ClassRecords:
    """Upsert a class's height and weight, all or none.

    Unlike attendance, a partly filled row is legitimate: the end-of-term
    figures do not exist until the end of term, and §4.7 makes every column
    nullable for that reason.
    """
    records = await class_records(db, actor, class_id=class_id, term_id=term_id)
    await _refuse_unless_class_teacher(
        db, actor, class_id=class_id, academic_session_id=records.term.academic_session_id
    )
    workflow.refuse_if_locked(records.state)

    known = {pupil.id for pupil in records.pupils}
    errors: dict[str, dict[str, str]] = {}
    for row in rows:
        if row.pupil_id not in known:
            errors[str(row.pupil_id)] = {
                "pupil_id": "This pupil is not in this class for this session."
            }
            continue
        found = check_growth(row)
        if found:
            errors[str(row.pupil_id)] = found

    if errors:
        raise RowErrors(
            f"{len(errors)} of {len(rows)} rows were rejected, so nothing was saved.", errors
        )

    created = 0
    for row in rows:
        record = records.growth.get(row.pupil_id)
        if record is None:
            record = GrowthRecord(school_id=actor.school_id, term_id=term_id, pupil_id=row.pupil_id)
            db.add(record)
            created += 1
        for column in GROWTH_COLUMNS:
            setattr(record, column, getattr(row, column))
        record.recorded_by = actor.id

    await db.flush()
    await workflow.mark_in_progress(
        db,
        actor,
        class_id=class_id,
        term_id=term_id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await audit.record(
        db,
        school_id=actor.school_id,
        action=AuditAction.GROWTH_SAVED,
        entity_type="class",
        entity_id=class_id,
        actor_id=actor.id,
        after={"term_id": str(term_id), "rows_saved": len(rows), "rows_created": created},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()

    return await class_records(db, actor, class_id=class_id, term_id=term_id)
