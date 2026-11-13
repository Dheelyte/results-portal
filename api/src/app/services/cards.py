"""Producing and serving a card PDF (ARCHITECTURE.md §9, §2.1, R13).

§2.1: "PDF generation for one pupil takes well under a second. Generate on
demand, cache the artifact." So that is what happens — a card is rendered the
first time it is asked for, stored under §9's versioned key, and served from
the store afterwards.

The link a parent follows is signed and expires in five minutes
(`app/pdf/links.py`). The file itself is never reachable by guessing: §9 is
explicit that "a guessable public URL would let anyone enumerate the school's
results".
"""

import datetime as dt
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import scope
from app.config import settings
from app.models import (
    AssessmentPeriod,
    PublicationState,
    TermHalf,
    TermReport,
    User,
)
from app.pdf import links, render, storage
from app.services import reportcard
from app.services.errors import Conflict, NotFound, NotPermitted
from app.services.support import all_of

logger = logging.getLogger(__name__)

# §9: "Under 300 KB per file." Logged rather than enforced — refusing to serve
# a card because it is large would punish a parent for a teacher writing at
# length — but a test asserts the fixture card is well under, and this says so
# in the log when a real one is not.
SIZE_BUDGET_BYTES = 300 * 1024


@dataclass(frozen=True)
class StoredCard:
    key: str
    content: bytes
    generated: bool


def store() -> storage.LocalStore:
    return storage.LocalStore(settings.report_store_path)


async def card_pdf(
    db: AsyncSession,
    actor: User,
    *,
    pupil_id: uuid.UUID,
    term_id: uuid.UUID,
    half: TermHalf,
    force: bool = False,
) -> StoredCard:
    """The card, from the cache or freshly rendered.

    `force` is R13's path: a corrected score means the stored artifact is
    wrong, and the new one is written under the next version so the one the
    parent already has is retained (§9, R13).
    """
    card = await reportcard.build(db, actor, pupil_id=pupil_id, term_id=term_id, half=half)

    key = storage.object_key(
        session_name=card.session_name,
        term=f"{card.subtitle.split()[0].lower()}-half-{_term_slug(card.title)}",
        # Without an admission number (D124), the pupil's id names the file.
        admission_number=card.admission_number or str(pupil_id),
        version=card.version,
    )

    keeper = store()
    if not force:
        existing = keeper.get(key)
        if existing is not None:
            return StoredCard(key=key, content=existing, generated=False)

    content = render.render_pdf(card)
    if len(content) > SIZE_BUDGET_BYTES:
        # §9 sets the budget; exceeding it is a layout problem, not a reason
        # to withhold a parent's card.
        logger.warning(
            "report card over the size budget",
            extra={"key": key, "bytes": len(content), "budget": SIZE_BUDGET_BYTES},
        )
    keeper.put(key, content)

    return StoredCard(key=key, content=content, generated=True)


def _term_slug(title: str) -> str:
    """ "CONTINUOUS ASSESSMENT FOR FIRST TERM" -> "first-term"."""
    words = title.lower().split()
    return "-".join(words[-2:]) if len(words) >= 2 else "term"


async def signed_link(
    db: AsyncSession,
    actor: User,
    *,
    pupil_id: uuid.UUID,
    term_id: uuid.UUID,
    half: TermHalf,
) -> str:
    """A five-minute URL path for this pupil's card (§7: "302 → signed URL").

    The card is generated here rather than behind the redirect, so a parent
    who follows the link gets a file rather than a spinner — and so a
    rendering failure surfaces as an error on the page they are already on.
    """
    stored = await card_pdf(db, actor, pupil_id=pupil_id, term_id=term_id, half=half)
    return links.sign(stored.key)


async def open_signed(token: str) -> bytes:
    """The file a signed link points at.

    Deliberately takes no user: the token **is** the authority, which is what
    makes the URL shareable with a browser's download manager and a printer.
    It is short-lived for the same reason (§9).

    **403, not 404**, for every failure — forged, tampered, expired, or a key
    that was never written. §12's criterion says so, and it is also what an
    S3-compatible store returns for a bad presigned signature, which is what
    `app/pdf/storage.py` is a seam for (§11). It leaks nothing: without the
    secret no signature can be produced for any key, so the status code is
    the same whatever is guessed.

    One message for every reason, for the same cause as `InvalidLink`:
    distinguishing "expired" from "forged" tells whoever is trying which half
    to work on.
    """
    refusal = "This link is no longer valid. Open the result again."
    try:
        key = links.verify(token)
    except links.InvalidLink as error:
        raise NotPermitted(refusal) from error

    content = store().get(key)
    if content is None:
        raise NotPermitted(refusal)
    return content


async def available_halves(
    db: AsyncSession, actor: User, *, pupil_id: uuid.UUID, term_id: uuid.UUID
) -> list[TermHalf]:
    """Which sheets exist for this term.

    §1.1 states both halves as a fact about the domain and D36 creates both
    with the term, so this is almost always two — but a card cannot be
    offered for a half that has no assessment period.
    """
    periods = await all_of(
        db,
        scope.scoped_assessment_periods(actor)
        .where(AssessmentPeriod.term_id == term_id)
        .order_by(AssessmentPeriod.half),
    )
    return [period.half for period in periods]


async def ensure_published(
    db: AsyncSession, actor: User, *, pupil_id: uuid.UUID, term_id: uuid.UUID
) -> TermReport:
    """A parent's card exists only once the report is published (R12).

    `scoped_term_reports` already filters a parent to published rows, so this
    is belt and braces for the staff paths, which see everything.
    """
    report = await db.scalar(
        scope.scoped_term_reports(actor).where(
            TermReport.term_id == term_id, TermReport.pupil_id == pupil_id
        )
    )
    if report is None:
        raise NotFound("No report for this pupil and term.")
    if report.state is not PublicationState.PUBLISHED:
        raise Conflict("This result has not been published yet.")
    return report


async def record_generation(db: AsyncSession, report: TermReport, *, key: str) -> None:
    """Remember which artefact a report's card is, for R13's versioning."""
    report.pdf_object_key = key
    report.pdf_generated_at = dt.datetime.now(dt.UTC)
    await db.flush()
