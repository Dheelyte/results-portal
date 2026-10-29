"""Grading scales and their bands (ARCHITECTURE.md §1.3, §4.5).

Scales are **versioned data, never edited in place**. §4.5 is emphatic about
why: "if the school later changes a boundary, last term's printed cards must
still say what was printed". So this module creates scales and switches which
one is active. It never rewrites a band, because a parent holding a printed
card must always find the portal agrees with it.

**N1 is still open.** The card prints seven bands with plus grades; the
requirements approved in September described six without. The card's scale is
seeded because it is what is printed, and the school's answer will arrive as a
new scale here rather than as a migration.

R3's two period-average functions and R4's band lookup are at the foot of
this module, both marked as placeholders where N3 leaves them one. R5 and R6
join them when the cumulative columns are built (milestone 11).
"""

import datetime as dt
import decimal
import logging
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import scope
from app.models import AuditAction, GradeBand, GradingScale, TermHalf, User
from app.services import audit
from app.services.errors import Invalid
from app.services.marks import COLUMNS_BY_HALF
from app.services.support import all_of, integrity_guard, one_or_404

logger = logging.getLogger(__name__)

# The range a grade band may describe. A percentage, so 0 to 100.
LOWEST_SCORE = decimal.Decimal(0)
HIGHEST_SCORE = decimal.Decimal(100)


@dataclass(frozen=True)
class BandInput:
    letter: str
    remark: str
    min_score: decimal.Decimal
    max_score: decimal.Decimal


def validate_bands(bands: Sequence[BandInput]) -> list[BandInput]:
    """Check a proposed set of bands and return it in card order.

    Three rules, each because of a specific way a report card goes wrong:

    - **No overlaps.** Two bands containing 85 means the grade printed depends
      on which row the resolver happened to read first.
    - **Every whole mark from 0 to 100 covered.** A gap means some pupil's
      average resolves to no grade at all, and the cell prints empty.
    - **Nothing outside 0-100.** A band from 90 to 110 is a typo, and the one
      it hides is usually the band below it.

    Returned highest band first, which is the order the card prints its key
    in — A+ at the top.

    **A known limit, deliberately not papered over:** these rules cover whole
    marks only. The card's own scale runs 0-39, 40-49, … so a period average
    of 39.5 — which `numeric(5,2)` permits and R1's one decimal place allows —
    falls between two bands. Whether averages are rounded before banding, and
    to what, is part of the unanswered N3. Nothing here guesses; the gap is
    recorded in docs/DECISIONS.md so milestone 9 resolves it with an answer
    rather than an assumption.
    """
    if not bands:
        raise Invalid("A grading scale needs at least one band.")

    for band in bands:
        if not band.letter.strip():
            raise Invalid("Every band needs a grade letter.")
        if not band.remark.strip():
            raise Invalid(f"Band {band.letter} needs a remark — it prints on the card.")
        if band.min_score > band.max_score:
            raise Invalid(f"Band {band.letter} starts above where it ends.")
        if band.min_score < LOWEST_SCORE or band.max_score > HIGHEST_SCORE:
            raise Invalid(
                f"Band {band.letter} falls outside 0 to 100. Grades are read from a percentage."
            )

    letters = [band.letter.strip() for band in bands]
    duplicates = sorted({letter for letter in letters if letters.count(letter) > 1})
    if duplicates:
        raise Invalid(f"Grade letter {', '.join(duplicates)} appears twice in this scale.")

    ordered = sorted(bands, key=lambda band: band.min_score)

    for lower, upper in zip(ordered, ordered[1:], strict=False):
        if upper.min_score <= lower.max_score:
            raise Invalid(
                f"Bands {lower.letter} and {upper.letter} overlap. "
                "A score must resolve to exactly one grade."
            )

    uncovered = [
        mark
        for mark in range(int(LOWEST_SCORE), int(HIGHEST_SCORE) + 1)
        if not any(band.min_score <= mark <= band.max_score for band in ordered)
    ]
    if uncovered:
        raise Invalid(
            f"These marks fall in no band: {_describe_runs(uncovered)}. "
            "Every mark from 0 to 100 must resolve to a grade."
        )

    return list(reversed(ordered))


def _describe_runs(marks: Sequence[int]) -> str:
    """Collapse [40,41,42,70] into "40-42, 70" so the message stays readable."""
    runs: list[str] = []
    start = previous = marks[0]
    for mark in marks[1:]:
        if mark == previous + 1:
            previous = mark
            continue
        runs.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = mark
    runs.append(str(start) if start == previous else f"{start}-{previous}")
    return ", ".join(runs)


async def list_scales(db: AsyncSession, actor: User) -> Sequence[GradingScale]:
    return await all_of(
        db,
        scope.scoped_grading_scales(actor).order_by(
            GradingScale.is_active.desc(), GradingScale.effective_from.desc()
        ),
    )


async def get_scale(db: AsyncSession, actor: User, scale_id: uuid.UUID) -> GradingScale:
    return await one_or_404(
        db, scope.scoped_grading_scales(actor).where(GradingScale.id == scale_id), "grading scale"
    )


async def bands_of(db: AsyncSession, actor: User, scale_id: uuid.UUID) -> Sequence[GradeBand]:
    return await all_of(
        db,
        scope.scoped_grade_bands(actor)
        .where(GradeBand.scale_id == scale_id)
        .order_by(GradeBand.sort_order),
    )


async def active_scale(db: AsyncSession, actor: User) -> GradingScale | None:
    return await db.scalar(
        scope.scoped_grading_scales(actor).where(GradingScale.is_active.is_(True))
    )


async def create_scale(
    db: AsyncSession,
    actor: User,
    *,
    name: str,
    effective_from: dt.date,
    bands: Sequence[BandInput],
    activate: bool = False,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> GradingScale:
    """Create a scale with its bands, optionally making it the active one."""
    if not name.strip():
        raise Invalid("Give the scale a name — it identifies which card used it.")

    ordered = validate_bands(bands)

    scale = GradingScale(
        school_id=actor.school_id,
        name=name.strip(),
        effective_from=effective_from,
        is_active=False,
    )
    db.add(scale)

    async with integrity_guard(db, "A grading scale could not be saved."):
        await db.flush()

    for position, band in enumerate(ordered):
        db.add(
            GradeBand(
                scale_id=scale.id,
                letter=band.letter.strip(),
                remark=band.remark.strip(),
                min_score=band.min_score,
                max_score=band.max_score,
                sort_order=position,
            )
        )

    # §4.9 names this explicitly: every grading-scale change is audited.
    await audit.record(
        db,
        school_id=actor.school_id,
        actor_id=actor.id,
        action=AuditAction.GRADING_SCALE_CREATED,
        entity_type="grading_scale",
        entity_id=scale.id,
        after={
            "name": scale.name,
            "effective_from": scale.effective_from.isoformat(),
            "bands": [
                {
                    "letter": band.letter.strip(),
                    "remark": band.remark.strip(),
                    "min_score": str(band.min_score),
                    "max_score": str(band.max_score),
                }
                for band in ordered
            ],
        },
        ip_address=ip_address,
        user_agent=user_agent,
    )

    if activate:
        await _activate(db, actor, scale, ip_address, user_agent)

    await db.commit()
    await db.refresh(scale)
    return scale


async def activate_scale(
    db: AsyncSession,
    actor: User,
    scale_id: uuid.UUID,
    *,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> GradingScale:
    """Make one scale the active one.

    Not in §7's list, which has only GET and POST for scales. Switching
    between versions is the whole point of versioning them, and the answer to
    N1 will arrive as "use this one from now on" — so the verb has to exist.
    Recorded in docs/DECISIONS.md.
    """
    scale = await get_scale(db, actor, scale_id)
    if not await bands_of(db, actor, scale.id):
        raise Invalid("That scale has no bands, so it cannot be made active.")

    await _activate(db, actor, scale, ip_address, user_agent)
    await db.commit()
    await db.refresh(scale)
    return scale


async def _activate(
    db: AsyncSession,
    actor: User,
    scale: GradingScale,
    ip_address: str | None,
    user_agent: str | None,
) -> None:
    """Promote one scale and demote the rest.

    Exactly one active scale, because §4.5 says grades are resolved "from the
    active scale" — singular. Two would make the grade depend on row order.
    Already-approved results keep the scale snapshotted onto them, so nothing
    printed changes when this runs (CLAUDE.md rule 6).
    """
    await db.execute(
        update(GradingScale)
        .where(
            GradingScale.school_id == actor.school_id,
            GradingScale.id != scale.id,
            GradingScale.is_active.is_(True),
        )
        .values(is_active=False)
    )
    scale.is_active = True

    await audit.record(
        db,
        school_id=actor.school_id,
        actor_id=actor.id,
        action=AuditAction.GRADING_SCALE_ACTIVATED,
        entity_type="grading_scale",
        entity_id=scale.id,
        after={"name": scale.name, "is_active": True},
        ip_address=ip_address,
        user_agent=user_agent,
    )


# ---------------------------------------------------------------------------
# R3 — the period average.  ⚠ PLACEHOLDER: N3 is unanswered.
# ---------------------------------------------------------------------------
#
# §6 R3 names two different figures: *Mid Term Ave.* on the first-half sheet
# and *Total Weighted Average* on the second. Different names on the printed
# card almost certainly mean different arithmetic, and the school has not yet
# said what either one is — N3.
#
# So there are two functions below, as R3 instructs, and today they agree.
# That agreement is the placeholder, not the design: when the answer arrives,
# each has exactly one body to change and `python -m app.recompute_averages`
# backfills every unapproved row. No other module does this arithmetic, and
# nothing reads `period_average` and adjusts it afterwards.
#
# The placeholder is the pupil's marks as a percentage of the marks obtainable
# for that sheet. Three properties make it the safest guess available:
#
#   * It is scale-free. Whatever the school's maxima turn out to be (N2), the
#     result is 0-100, which is the range the grade bands describe.
#   * It treats a blank cell as zero and returns nothing only when the whole
#     row is blank — exactly what R2's generated CA Test Total column does. A
#     half-entered row therefore reads low in both columns, consistently,
#     rather than the average disagreeing with the total beside it.
#   * A column the school left out of Marks Obtainable is not on the sheet, so
#     it counts in neither the numerator nor the denominator.
#
# What it is NOT is weighted — nothing here can be, until "weighted" is
# defined. If the school says the exam is worth 60% and the CA total 40%,
# `total_weighted_average` is the one function that changes.

Scores = Mapping[str, decimal.Decimal | None]

# Two decimal places, because `result_entries.period_average` is numeric(5,2).
AVERAGE_PLACES = decimal.Decimal("0.01")


def _percentage_of_obtainable(
    columns: Sequence[str], scores: Scores, maxima: Scores
) -> decimal.Decimal | None:
    """The shared placeholder body. See the note above before editing."""
    applicable = [column for column in columns if maxima.get(column) is not None]

    obtainable = sum(
        (maxima[column] for column in applicable),
        start=decimal.Decimal(0),
    )
    if obtainable <= 0:
        return None

    if all(scores.get(column) is None for column in applicable):
        return None

    earned = sum(
        (scores.get(column) or decimal.Decimal(0) for column in applicable),
        start=decimal.Decimal(0),
    )

    percentage = earned / obtainable * HIGHEST_SCORE
    return percentage.quantize(AVERAGE_PLACES, rounding=decimal.ROUND_HALF_UP)


def mid_term_average(scores: Scores, maxima: Scores) -> decimal.Decimal | None:
    """*Mid Term Ave.* — the first-half sheet's figure. ⚠ PLACEHOLDER (N3)."""
    return _percentage_of_obtainable(COLUMNS_BY_HALF[TermHalf.FIRST_HALF], scores, maxima)


def total_weighted_average(scores: Scores, maxima: Scores) -> decimal.Decimal | None:
    """*Total Weighted Average* — the second-half sheet's figure.

    ⚠ PLACEHOLDER (N3), and the one most likely to be wrong: "weighted" is a
    word the card uses and this function does not yet honour.
    """
    return _percentage_of_obtainable(COLUMNS_BY_HALF[TermHalf.SECOND_HALF], scores, maxima)


def period_average(half: TermHalf, scores: Scores, maxima: Scores) -> decimal.Decimal | None:
    """Whichever of the two figures this sheet prints.

    The single entry point, so no caller chooses the formula by inspecting the
    half itself.
    """
    if half is TermHalf.FIRST_HALF:
        return mid_term_average(scores, maxima)
    return total_weighted_average(scores, maxima)


# ---------------------------------------------------------------------------
# R4 — the grade
# ---------------------------------------------------------------------------


def banded_value(average: decimal.Decimal) -> decimal.Decimal:
    """The number a band is looked up by.

    The card's bands run 0-39, 40-49, 50-59 and so on — whole marks, with
    nothing between them. A period average is numeric(5,2), so 39.50 falls in
    no band at all (docs/DECISIONS.md D43).

    This rounds half up to the nearest whole mark before the lookup, which is
    an **assumption** (§14 A17): the second half of N3 asks the school whether
    an average is rounded before a grade is read from it. It lives in one
    named function so the answer is a one-line change, and
    `test_grading_bands.py` pins the current behaviour so that change cannot
    be made silently.
    """
    return average.quantize(decimal.Decimal(1), rounding=decimal.ROUND_HALF_UP)


def band_for(average: decimal.Decimal | None, bands: Sequence[GradeBand]) -> GradeBand | None:
    """The band an average falls in, or None.

    None has two causes and both are legitimate: there is no average yet, or
    the bands do not cover the rounded value. The second should be impossible
    for a scale built through `create_scale`, which refuses gaps — but a scale
    seeded or edited before that rule existed could have one, and a missing
    grade is better than a wrong one.
    """
    if average is None:
        return None

    value = banded_value(average)
    for band in bands:
        if band.min_score <= value <= band.max_score:
            return band
    return None


# ---------------------------------------------------------------------------
# R6 — overall percentage.  ⚠ PLACEHOLDER: the definition is unconfirmed.
# ---------------------------------------------------------------------------
#
# §1.4 puts *Overall Percentage* in the card's header, once per term, beside
# Position and No. in Class. §6 R6 defines it as "the pupil's aggregate as a
# percentage" and then says, in as many words, that the exact definition is
# unconfirmed.
#
# Something has to fill `term_reports.overall_percentage`, and approval is the
# only moment rule 6 permits it to be fixed: after publication a parent is
# holding a card with this number printed on it. So it is computed here, once,
# by one named function, and `python -m app.recompute_averages` moves it when
# the school answers (§14 A25).
#
# The placeholder is the mean of the pupil's **second-half** period averages
# across scored subjects. Two reasons for the second half rather than both:
# R5 treats a term's contribution to the annual average as its second-half
# *Total Weighted Average*, and the second-half sheet is the one that carries
# the exam. The obvious alternative — the mean across both halves — is one
# line away.


def overall_percentage(averages: Sequence[decimal.Decimal | None]) -> decimal.Decimal | None:
    """A pupil's aggregate across subjects, as a percentage. ⚠ PLACEHOLDER (R6).

    Subjects with no average are skipped rather than counted as zero: a
    subject a pupil is not taking must not drag their aggregate down. R10
    guarantees every offered subject has a score before approval, so in
    practice nothing is skipped — this matters only for a row written by some
    other path.
    """
    present = [average for average in averages if average is not None]
    if not present:
        return None

    total = sum(present, start=decimal.Decimal(0))
    return (total / len(present)).quantize(AVERAGE_PLACES, rounding=decimal.ROUND_HALF_UP)
