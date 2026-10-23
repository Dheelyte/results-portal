"""`python -m app.recompute_averages` (R3).

R3's formulas are a placeholder until N3 is answered, so the stored
`period_average` of every existing row is provisional. This command is how
they move when the answer arrives — and the one thing it must never do is move
a grade that has already been printed on a card (§4.5, CLAUDE.md rule 6).
"""

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AssessmentPeriod,
    AuditLog,
    MarksObtainable,
    ResultEntry,
    TermHalf,
)
from app.recompute_averages import recompute


@pytest.fixture
async def stale(session: AsyncSession, world):
    """One sheet, one pupil, and a stored average that is simply wrong.

    Written directly rather than through the API, which is the situation the
    command exists for: rows computed by an older version of the formula.
    """
    period = AssessmentPeriod(
        school_id=world.school.id, term_id=world.term.id, half=TermHalf.FIRST_HALF
    )
    session.add(period)
    await session.flush()
    session.add(
        MarksObtainable(
            school_id=world.school.id,
            assessment_period_id=period.id,
            class_id=None,
            ca_test_1=Decimal(10),
            mid_term_test=Decimal(40),
        )
    )
    entry = ResultEntry(
        school_id=world.school.id,
        assessment_period_id=period.id,
        pupil_id=world.pupils["ada"].id,
        class_subject_id=world.maths_4a.id,
        ca_test_1=Decimal(5),
        mid_term_test=Decimal(25),
        period_average=Decimal("1.00"),  # nonsense, deliberately
    )
    session.add(entry)
    await session.commit()

    from types import SimpleNamespace

    return SimpleNamespace(period=period, entry=entry)


async def test_a_stale_average_is_rewritten(session: AsyncSession, world, stale) -> None:
    outcome = await recompute(session)

    assert outcome.changed == 1
    await session.refresh(stale.entry)
    # 30 earned of 50 obtainable.
    assert stale.entry.period_average == Decimal("60.00")


async def test_a_dry_run_writes_nothing(session: AsyncSession, world, stale) -> None:
    outcome = await recompute(session, dry_run=True)

    assert outcome.changed == 1
    await session.refresh(stale.entry)
    assert stale.entry.period_average == Decimal("1.00")


async def test_an_approved_row_is_never_recomputed(session: AsyncSession, world, stale) -> None:
    """The rule this command exists to respect.

    A row carrying a snapshotted grade was printed on a card. Recomputing it
    would make the portal disagree with the paper in a parent's hand (§4.5).
    """
    stale.entry.grade_letter = "E"
    await session.commit()

    outcome = await recompute(session)

    assert outcome.changed == 0
    assert outcome.skipped_approved == 1
    await session.refresh(stale.entry)
    assert stale.entry.period_average == Decimal("1.00")


async def test_a_sheet_with_no_maxima_is_skipped_and_counted(
    session: AsyncSession, world, stale
) -> None:
    """Reported rather than silently passed over: a sheet whose Marks
    Obtainable row has gone missing is something the operator should know."""
    await session.execute(
        MarksObtainable.__table__.delete().where(
            MarksObtainable.assessment_period_id == stale.period.id
        )
    )
    await session.commit()

    outcome = await recompute(session)

    assert outcome.changed == 0
    assert outcome.skipped_unconfigured == 1


async def test_a_run_can_be_limited_to_one_term(session: AsyncSession, world, stale) -> None:
    """The usual case: the school answers N3 mid-year and only the live term
    should move."""
    from app.models import Term, TermNumber

    other_term = Term(
        school_id=world.school.id,
        academic_session_id=world.academic_session.id,
        number=TermNumber.SECOND,
        starts_on=dt.date(2027, 1, 11),
        ends_on=dt.date(2027, 4, 2),
    )
    session.add(other_term)
    await session.commit()

    outcome = await recompute(session, term_id=other_term.id)

    assert outcome.examined == 0
    await session.refresh(stale.entry)
    assert stale.entry.period_average == Decimal("1.00")


async def test_a_recompute_is_audited(session: AsyncSession, world, stale) -> None:
    await recompute(session)

    rows = (
        (
            await session.execute(
                select(AuditLog).where(AuditLog.action == "result_entries.averages_recomputed")
            )
        )
        .scalars()
        .all()
    )

    assert len(rows) == 1
    assert rows[0].after["changed"] == 1
    assert "period_average recomputed" in rows[0].reason


async def test_a_correct_average_is_left_alone(session: AsyncSession, world, stale) -> None:
    """Idempotent, so running it twice is safe and the count means something."""
    await recompute(session)

    second = await recompute(session)

    assert second.changed == 0
    assert second.examined == 1
