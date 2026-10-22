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

The formulas of R3, R5 and R6 will join this module when the school answers
N3. Nothing in this milestone computes a grade: §12 puts grade resolution at
approval, in milestone 9.
"""

import datetime as dt
import decimal
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import scope
from app.models import AuditAction, GradeBand, GradingScale, User
from app.services import audit
from app.services.errors import Invalid
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
