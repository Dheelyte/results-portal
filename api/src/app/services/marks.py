"""The "Marks Obtainable" row — each score column's maximum
(ARCHITECTURE.md §4.4).

Configuration, never a constant (§2.3). **N2 is still open**: the requirements
gathered in September said CA 40 / exam 60, but the card has five separate CA
test columns plus a mid term test or an exam, and the row is blank on both
photographed sheets. Nothing in this module assumes a value, and nothing
anywhere else may either — R1 reads the school's numbers from here.
"""

import decimal
import logging
import uuid
from collections.abc import Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import scope
from app.models import (
    AssessmentPeriod,
    AuditAction,
    ClassSubject,
    MarksObtainable,
    ResultEntry,
    TermHalf,
    User,
)
from app.services import academic, audit
from app.services.errors import Conflict, Invalid
from app.services.support import all_of, integrity_guard, one_or_404

logger = logging.getLogger(__name__)

CA_COLUMNS = ("ca_test_1", "ca_test_2", "ca_test_3", "ca_test_4", "ca_test_5")

# Which columns each sheet carries (§1.2). The first-half sheet ends in Mid
# Term Test, the second-half sheet in Exam; neither has the other's column, so
# a value for it would print nowhere and validate nothing.
COLUMNS_BY_HALF: dict[TermHalf, tuple[str, ...]] = {
    TermHalf.FIRST_HALF: (*CA_COLUMNS, "mid_term_test"),
    TermHalf.SECOND_HALF: (*CA_COLUMNS, "exam"),
}

ALL_COLUMNS = (*CA_COLUMNS, "mid_term_test", "exam")

FIELDS = ("assessment_period_id", "class_id", *ALL_COLUMNS)


async def get_assessment_period(
    db: AsyncSession, actor: User, assessment_period_id: uuid.UUID
) -> AssessmentPeriod:
    return await one_or_404(
        db,
        scope.scoped_assessment_periods(actor).where(AssessmentPeriod.id == assessment_period_id),
        "assessment period",
    )


async def list_marks_obtainable(
    db: AsyncSession, actor: User, assessment_period_id: uuid.UUID
) -> Sequence[MarksObtainable]:
    """Every row for one sheet: the school-wide one first, then overrides."""
    await get_assessment_period(db, actor, assessment_period_id)
    return await all_of(
        db,
        scope.scoped_marks_obtainable(actor)
        .where(MarksObtainable.assessment_period_id == assessment_period_id)
        .order_by(MarksObtainable.class_id.is_(None).desc(), MarksObtainable.class_id),
    )


async def save_marks_obtainable(
    db: AsyncSession,
    actor: User,
    assessment_period_id: uuid.UUID,
    *,
    values: dict[str, decimal.Decimal | None],
    class_id: uuid.UUID | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> MarksObtainable:
    """Set one sheet's column maxima, school-wide or for a single class.

    `class_id = None` is the school-wide row. A per-class row overrides it
    entirely for that class — R1 resolves "per-class row if present, otherwise
    the school-wide row", so a partial override is not a thing.
    """
    period = await get_assessment_period(db, actor, assessment_period_id)
    if class_id is not None:
        await academic.get_class(db, actor, class_id)

    allowed = COLUMNS_BY_HALF[period.half]
    supplied = {column: value for column, value in values.items() if value is not None}

    wrong_half = sorted(set(supplied) - set(allowed))
    if wrong_half:
        other = "Exam" if period.half is TermHalf.FIRST_HALF else "Mid Term Test"
        raise Invalid(
            f"The {_half_label(period.half)} sheet has no {', '.join(wrong_half)} column. "
            f"{other} belongs to the other half of the term (§1.2)."
        )

    for column, value in supplied.items():
        if value <= 0:
            raise Invalid(
                f"{column} must be greater than zero. A column with a maximum of nought "
                "cannot be scored."
            )

    if not supplied:
        raise Invalid(
            "Give at least one column's maximum. An empty Marks Obtainable row would "
            "leave every score unvalidated."
        )

    await _refuse_if_it_would_invalidate_entered_scores(
        db, actor, period, class_id=class_id, supplied=supplied
    )

    record = await db.scalar(
        scope.scoped_marks_obtainable(actor).where(
            MarksObtainable.assessment_period_id == assessment_period_id,
            MarksObtainable.class_id.is_(None)
            if class_id is None
            else MarksObtainable.class_id == class_id,
        )
    )
    before = None if record is None else audit.snapshot(record, FIELDS)

    if record is None:
        record = MarksObtainable(
            school_id=actor.school_id,
            assessment_period_id=assessment_period_id,
            class_id=class_id,
        )
        db.add(record)

    # Every column is written, including the ones left out, so a cleared value
    # clears. A half-updated maxima row is worse than none.
    for column in ALL_COLUMNS:
        setattr(record, column, supplied.get(column))

    async with integrity_guard(db, "Marks obtainable are already set for that sheet."):
        await db.flush()

    # Read the row back before snapshotting it. The values just assigned are
    # Python Decimals as typed — `Decimal("50")` — while `before` came from a
    # numeric(5,2) column as `Decimal("50.00")`. Without this the audit log
    # compares "50" against "50.00" and a no-op edit reads as a change.
    await db.refresh(record)

    # §4.9 names this explicitly: "every grading-scale or marks-obtainable
    # change" is audited. Changing a maximum changes what every score means.
    await audit.record(
        db,
        school_id=actor.school_id,
        actor_id=actor.id,
        action=AuditAction.MARKS_OBTAINABLE_SAVED,
        entity_type="marks_obtainable",
        entity_id=record.id,
        before=before,
        after=audit.snapshot(record, FIELDS),
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()
    await db.refresh(record)
    return record


async def _refuse_if_it_would_invalidate_entered_scores(
    db: AsyncSession,
    actor: User,
    period: AssessmentPeriod,
    *,
    class_id: uuid.UUID | None,
    supplied: dict[str, decimal.Decimal | None],
) -> None:
    """Refuse a maximum that is already below a score somebody entered.

    §4.4 lets the school change these numbers, and this does not stop that —
    it stops the one change that silently makes stored data invalid. Lowering
    Mid Term Test to 20 when a teacher has already entered 35 leaves a row
    that R1 would have rejected on entry and that prints on a card as-is.

    The count is reported; the scores are not. CLAUDE.md forbids a score in an
    error message, and "nine entries exceed that maximum" is enough for the
    admin to decide.
    """
    conditions = []
    for column, maximum in supplied.items():
        conditions.append(getattr(ResultEntry, column) > maximum)
    if not conditions:
        return

    stmt = (
        select(func.count())
        .select_from(ResultEntry)
        .where(
            ResultEntry.school_id == actor.school_id,
            ResultEntry.assessment_period_id == period.id,
            or_(*conditions),
        )
    )
    if class_id is not None:
        stmt = stmt.where(
            ResultEntry.class_subject_id.in_(
                select(ClassSubject.id).where(ClassSubject.class_id == class_id)
            )
        )

    offending = await db.scalar(stmt) or 0
    if offending:
        raise Conflict(
            f"{offending} score{'s' if offending != 1 else ''} already entered for this "
            "sheet exceed the maxima you have given. Raise the maxima, or correct those "
            "entries first."
        )


def _half_label(half: TermHalf) -> str:
    return "First Half Term" if half is TermHalf.FIRST_HALF else "Second Half Term"


async def applicable_maxima(
    db: AsyncSession,
    actor: User,
    *,
    assessment_period_id: uuid.UUID,
    class_id: uuid.UUID,
) -> MarksObtainable | None:
    """The row R1 validates against: the class override, else the school row.

    One place, because the resolution order is a rule and R1 must not restate
    it. Returns `None` when the school has configured neither — which the
    setup checklist reports and score entry refuses to proceed without.
    """
    rows = await all_of(
        db,
        scope.scoped_marks_obtainable(actor).where(
            MarksObtainable.assessment_period_id == assessment_period_id,
            or_(MarksObtainable.class_id == class_id, MarksObtainable.class_id.is_(None)),
        ),
    )
    override = next((row for row in rows if row.class_id == class_id), None)
    if override is not None:
        return override
    return next((row for row in rows if row.class_id is None), None)


def is_configured(record: MarksObtainable | None, half: TermHalf) -> bool:
    """Whether a Marks Obtainable row is usable for its sheet.

    "Configured" means the sheet's terminal column — Mid Term Test or Exam —
    has a maximum, and at least one CA test does. Not all five: N2 is open and
    the school may well use fewer than five CA tests in a given half, so
    demanding all five would block a term on a number nobody has.
    """
    if record is None:
        return False

    terminal = COLUMNS_BY_HALF[half][-1]
    if getattr(record, terminal) is None:
        return False
    return any(getattr(record, column) is not None for column in CA_COLUMNS)


async def school_wide_maxima(
    db: AsyncSession, actor: User, assessment_period_id: uuid.UUID
) -> MarksObtainable | None:
    """The row that applies to every class unless a class overrides it."""
    return await db.scalar(
        scope.scoped_marks_obtainable(actor).where(
            MarksObtainable.assessment_period_id == assessment_period_id,
            MarksObtainable.class_id.is_(None),
        )
    )


async def sheet_configuration(
    db: AsyncSession, actor: User, period: AssessmentPeriod
) -> tuple[bool, list[str]]:
    """Whether one sheet's maxima are usable, and for which classes they are not.

    The school-wide row covers everything, so it is checked first. Where it is
    absent or incomplete, a per-class override still counts — a school that
    marks Primary 1 out of different numbers can configure only the overrides
    and be correctly set up. Returns the class names still uncovered, so the
    checklist can name them.
    """
    if is_configured(await school_wide_maxima(db, actor, period.id), period.half):
        return True, []

    rows = {
        row.class_id: row
        for row in await all_of(
            db,
            scope.scoped_marks_obtainable(actor).where(
                MarksObtainable.assessment_period_id == period.id,
                MarksObtainable.class_id.is_not(None),
            ),
        )
    }
    if not rows:
        # Nothing is configured for this sheet at all. Naming every class
        # would turn one missing row into a dozen lines of checklist; the
        # answer is to set the school-wide row.
        return False, []

    classes = await academic.list_classes(db, actor)
    if not classes:
        return False, []

    missing = [
        klass.name for klass in classes if not is_configured(rows.get(klass.id), period.half)
    ]
    return not missing, missing
