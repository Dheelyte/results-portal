"""Recompute stored period averages (ARCHITECTURE.md §6 R3).

R3's formulas are unconfirmed (N3). `period_average` is therefore stored
rather than derived, and when the school finally says what *Mid Term Ave.*
and *Total Weighted Average* actually are, the rows already in the database
hold the old arithmetic. This backfills them.

    docker compose exec api python -m app.recompute_averages --dry-run
    docker compose exec api python -m app.recompute_averages

**It never touches an approved row.** CLAUDE.md rule 6 and §4.5: a grade is
snapshotted at approval and a printed card must keep saying what was printed.
A row carrying a `grade_letter` is skipped, counted, and reported — so if the
formula changes after a term has been approved, the operator is told exactly
how many rows are now computed on the old rule rather than having it done
silently behind them.

Pass --term to limit the run to one term, which is the usual case: the school
answers N3 mid-year and only the live term should move.
"""

import argparse
import asyncio
import sys
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal
from app.models import (
    AssessmentPeriod,
    AuditAction,
    Class,
    ClassSubject,
    MarksObtainable,
    ResultEntry,
)
from app.services import audit, grading, marks


@dataclass
class Outcome:
    examined: int = 0
    changed: int = 0
    skipped_approved: int = 0
    skipped_unconfigured: int = 0


async def recompute(
    session: AsyncSession, *, term_id: uuid.UUID | None = None, dry_run: bool = False
) -> Outcome:
    """Rewrite `period_average` from the current formula. Returns the counts."""
    outcome = Outcome()

    # Queried without a scope filter because this is an operator command, not
    # a request: there is no caller whose scope could narrow it, and the whole
    # point is to reach every row. CLAUDE.md rule 4 governs routers.
    stmt = (
        select(ResultEntry, AssessmentPeriod, ClassSubject)
        .join(AssessmentPeriod, AssessmentPeriod.id == ResultEntry.assessment_period_id)
        .join(ClassSubject, ClassSubject.id == ResultEntry.class_subject_id)
        .order_by(ResultEntry.updated_at)
    )
    if term_id is not None:
        stmt = stmt.where(AssessmentPeriod.term_id == term_id)

    maxima_cache: dict[tuple[uuid.UUID, uuid.UUID], MarksObtainable | None] = {}

    for entry, period, class_subject in (await session.execute(stmt)).all():
        outcome.examined += 1

        if entry.grade_letter is not None:
            outcome.skipped_approved += 1
            continue

        key = (period.id, class_subject.class_id)
        if key not in maxima_cache:
            maxima_cache[key] = await _maxima(session, period.id, class_subject.class_id)
        maxima = maxima_cache[key]

        if maxima is None:
            outcome.skipped_unconfigured += 1
            continue

        columns = marks.COLUMNS_BY_HALF[period.half]
        recomputed = grading.period_average(
            period.half,
            {column: getattr(entry, column) for column in columns},
            {column: getattr(maxima, column) for column in marks.ALL_COLUMNS},
        )

        if recomputed != entry.period_average:
            outcome.changed += 1
            if not dry_run:
                entry.period_average = recomputed

    if not dry_run and outcome.changed:
        await audit.record(
            session,
            school_id=await _any_school_id(session),
            action=AuditAction.AVERAGES_RECOMPUTED,
            entity_type="result_entries",
            after={
                "examined": outcome.examined,
                "changed": outcome.changed,
                "skipped_approved": outcome.skipped_approved,
                "term_id": str(term_id) if term_id else None,
            },
            reason="period_average recomputed by python -m app.recompute_averages",
        )
        await session.commit()

    return outcome


async def _maxima(
    session: AsyncSession, assessment_period_id: uuid.UUID, class_id: uuid.UUID
) -> MarksObtainable | None:
    """The class override if there is one, else the school-wide row.

    The same resolution order as R1, which `services/marks.applicable_maxima`
    owns — repeated here only because that function takes a caller's scope and
    this command has no caller.
    """
    rows = (
        (
            await session.execute(
                select(MarksObtainable).where(
                    MarksObtainable.assessment_period_id == assessment_period_id
                )
            )
        )
        .scalars()
        .all()
    )
    override = next((row for row in rows if row.class_id == class_id), None)
    return override or next((row for row in rows if row.class_id is None), None)


async def _any_school_id(session: AsyncSession) -> uuid.UUID:
    return (await session.execute(select(Class.school_id).limit(1))).scalar_one()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--term", help="Limit the run to one term, by id.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing anything.",
    )
    args = parser.parse_args(argv)

    term_id = uuid.UUID(args.term) if args.term else None

    async def run() -> Outcome:
        async with SessionLocal() as session:
            return await recompute(session, term_id=term_id, dry_run=args.dry_run)

    outcome = asyncio.run(run())

    print(f"{'Would change' if args.dry_run else 'Changed'}: {outcome.changed}")
    print(f"Examined:     {outcome.examined}")
    if outcome.skipped_approved:
        print(
            f"Skipped:      {outcome.skipped_approved} approved rows — a snapshotted grade is "
            "never recomputed (§4.5)."
        )
    if outcome.skipped_unconfigured:
        print(
            f"Skipped:      {outcome.skipped_unconfigured} rows whose sheet has no "
            "Marks Obtainable row."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
