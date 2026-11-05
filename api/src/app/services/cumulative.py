"""R5's term and annual averages (ARCHITECTURE.md §6 R5, §9).

    On the second-half sheet, *1st Term Ave.*, *2nd Term Ave.* and *Annual
    Scores (Ave.)* are per subject, across the terms the pupil was present
    for. A pupil who joined in second term averages over two terms, not
    three. Report the number of terms counted alongside the figure so a
    parent can see why it differs.

    ⚠ UNCONFIRMED: whether a term's average is its second-half *Total
    Weighted Average*, or a blend of both halves.

So this module carries a placeholder like R3's, in one named function, with
the count travelling beside every figure. §14 A30.

§9's conditional rendering follows from the same data: "Render a column only
when the pupil has results for that term: none in first term, one in second,
both plus the annual average in third. Never print an empty or zero-filled
column." A column with no `Average` is absent from the mapping below, and the
template renders what it is given.
"""

import decimal
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import scope
from app.models import (
    AssessmentPeriod,
    ClassSubject,
    ResultEntry,
    Term,
    TermHalf,
    TermNumber,
    User,
)
from app.services.grading import AVERAGE_PLACES
from app.services.support import rows_of

logger = logging.getLogger(__name__)

# The order the card prints them in, which is not the order you would expect:
# the photographed second-half sheet reads 2ND TERM AVE., then 1ST TERM AVE.,
# then ANNUAL SCORES (AVE.). The photographs are the specification (§9).
PRIOR_TERM_ORDER = (TermNumber.SECOND, TermNumber.FIRST)

TERM_COLUMN_LABELS = {
    TermNumber.FIRST: "1ST TERM AVE.",
    TermNumber.SECOND: "2ND TERM AVE.",
    TermNumber.THIRD: "3RD TERM AVE.",
}


@dataclass(frozen=True)
class Average:
    """One cumulative figure, with the count R5 asks to be shown beside it."""

    value: decimal.Decimal
    terms_counted: int


def term_average(halves: Sequence[decimal.Decimal | None]) -> decimal.Decimal | None:
    """One term's contribution for one subject, from `[second_half, first_half]`.

    ⚠ PLACEHOLDER (R5).

    The placeholder takes the **second-half** figure where there is one — the
    *Total Weighted Average*, which R5 names as the likelier reading and which
    is the sheet carrying the exam — and falls back to whatever half exists.
    The alternative, a blend of both halves, is one line away.
    """
    second_half = halves[0] if halves else None
    first_half = halves[1] if len(halves) > 1 else None
    return second_half if second_half is not None else first_half


def annual_average(term_values: Sequence[decimal.Decimal]) -> Average | None:
    """The year's figure for one subject, over the terms actually present.

    R5: "A pupil who joined in second term averages over two terms, not
    three." Absent terms are not counted as zero — a pupil is not penalised
    for a term they were not enrolled in.
    """
    present = [value for value in term_values if value is not None]
    if not present:
        return None

    total = sum(present, start=decimal.Decimal(0))
    return Average(
        value=(total / len(present)).quantize(AVERAGE_PLACES, rounding=decimal.ROUND_HALF_UP),
        terms_counted=len(present),
    )


async def prior_term_averages(
    db: AsyncSession, actor: User, *, pupil_id: uuid.UUID, term: Term
) -> tuple[dict[uuid.UUID, dict[TermNumber, decimal.Decimal]], list[TermNumber]]:
    """Each earlier term's average per subject, and which terms exist.

    Keyed by **subject**, not by class-subject, because a pupil who moved
    class mid-year has a different `class_subjects` row for the same subject —
    and the card's Mathematics line is one line whatever class it was taught
    in.

    Returns the terms that actually produced a figure, so §9's conditional
    rendering has the list rather than inferring it: none in first term, one
    in second, two in third.
    """
    earlier = list(
        await rows_of(
            db,
            select(Term.id, Term.number)
            .where(
                Term.id.in_(scope.scoped_terms(actor).with_only_columns(Term.id)),
                Term.academic_session_id == term.academic_session_id,
                Term.number < term.number,
            )
            .order_by(Term.number),
        )
    )
    if not earlier:
        return {}, []

    by_term = {term_id: number for term_id, number in earlier}

    rows = await rows_of(
        db,
        select(
            ClassSubject.subject_id,
            AssessmentPeriod.term_id,
            AssessmentPeriod.half,
            ResultEntry.period_average,
        )
        .join(AssessmentPeriod, AssessmentPeriod.id == ResultEntry.assessment_period_id)
        .join(ClassSubject, ClassSubject.id == ResultEntry.class_subject_id)
        .where(
            # Filtered by school and pupil rather than by the row scope, for
            # the reason `services/reportcard.py` sets out: the caller has
            # already been granted sight of this pupil's card, and
            # `scoped_result_entries` returns nothing to a parent by design
            # (docs/DECISIONS.md D88). The caller checks the report first.
            ResultEntry.school_id == actor.school_id,
            ResultEntry.pupil_id == pupil_id,
            AssessmentPeriod.term_id.in_(by_term),
        ),
    )

    # subject -> term -> {half: average}
    gathered: dict[uuid.UUID, dict[TermNumber, dict[TermHalf, decimal.Decimal]]] = {}
    for subject_id, term_id, half, average in rows:
        if average is None:
            continue
        gathered.setdefault(subject_id, {}).setdefault(by_term[term_id], {})[half] = average

    averages: dict[uuid.UUID, dict[TermNumber, decimal.Decimal]] = {}
    produced: set[TermNumber] = set()
    for subject_id, terms in gathered.items():
        for number, halves in terms.items():
            value = term_average(
                [halves.get(TermHalf.SECOND_HALF), halves.get(TermHalf.FIRST_HALF)]
            )
            if value is None:
                continue
            averages.setdefault(subject_id, {})[number] = value
            produced.add(number)

    return averages, [number for number in PRIOR_TERM_ORDER if number in produced]
