"""What a parent may see (ARCHITECTURE.md §6 R12, §5.2, §7's parent block).

Milestone 10's criterion is "withheld pupil's parent sees the R12 message", so
this is the read path that produces it. §8.5's screens and the acknowledgement
are milestone 12; what is here is the availability question and the card
behind it, because a message about a report is not testable without the report
(docs/DECISIONS.md D73).

R12 is exact about the message, and exact about how little it says:

    Result not yet available. Please contact the school.

No hint of whether the report exists, whether it was withheld, or why. A
parent who has been held back for fee arrears is told by the school, in
person, not by a web page in front of whoever else is in the room. That is
also why `scoped_term_reports` filters a parent to `state = 'published'`
rather than returning a draft with a flag on it: a withheld report is
**invisible**, not forbidden, and a 403 would confirm it exists.
"""

import datetime as dt
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import scope
from app.models import (
    AuditAction,
    Class,
    Enrollment,
    GuardianPupil,
    Pupil,
    Term,
    TermNumber,
    TermReport,
    User,
)
from app.services import audit
from app.services.errors import NotFound
from app.services.publication import UNAVAILABLE_MESSAGE
from app.services.support import all_of, one_or_404, rows_of

logger = logging.getLogger(__name__)

# R12's sentence comes from `services/publication.py` rather than being
# repeated here, so the message a parent sees and the message the publication
# rules define cannot drift apart.

TERM_NAMES = {
    TermNumber.FIRST: "First Term",
    TermNumber.SECOND: "Second Term",
    TermNumber.THIRD: "Third Term",
}


@dataclass(frozen=True)
class Child:
    """One of the caller's children (§10: a parent may have several)."""

    pupil_id: uuid.UUID
    admission_number: str | None
    first_name: str
    middle_name: str | None
    last_name: str
    class_name: str | None


@dataclass(frozen=True)
class Availability:
    """Whether one term's report can be opened, and nothing more."""

    term_id: uuid.UUID
    term_label: str
    available: bool
    published_at: dt.datetime | None
    acknowledged_at: dt.datetime | None
    # R12's sentence, present exactly when `available` is false.
    message: str | None


async def children(db: AsyncSession, actor: User) -> list[Child]:
    """The caller's own children, and no others.

    `scoped_pupils` is the single most important filter in the system (§5.2),
    and for a parent it resolves to the `guardian_pupils` rows naming them.
    """
    rows = await rows_of(
        db,
        select(Pupil, Class.name)
        .join(GuardianPupil, GuardianPupil.pupil_id == Pupil.id)
        .outerjoin(
            Enrollment,
            (Enrollment.pupil_id == Pupil.id)
            & (Enrollment.academic_session_id == scope.current_session_id(actor.school_id)),
        )
        .outerjoin(Class, Class.id == Enrollment.class_id)
        .where(
            Pupil.id.in_(scope.scoped_pupils(actor).with_only_columns(Pupil.id)),
            GuardianPupil.guardian_user_id == actor.id,
        )
        .order_by(Pupil.last_name, Pupil.first_name),
    )

    return [
        Child(
            pupil_id=pupil.id,
            admission_number=pupil.admission_number,
            first_name=pupil.first_name,
            middle_name=pupil.middle_name,
            last_name=pupil.last_name,
            class_name=class_name,
        )
        for pupil, class_name in rows
    ]


async def _own_child(db: AsyncSession, actor: User, pupil_id: uuid.UUID) -> Pupil:
    return await one_or_404(
        db,
        scope.scoped_pupils(actor).where(Pupil.id == pupil_id),
        "pupil",
    )


async def reports(
    db: AsyncSession, actor: User, *, pupil_id: uuid.UUID
) -> tuple[Pupil, list[Availability]]:
    """Every term of the current session, with whether it can be opened.

    Terms the school has not published are listed as unavailable rather than
    hidden: a parent looking for a result needs to see that the term exists
    and that the result is not there yet. R12's sentence is the whole
    explanation, deliberately.
    """
    pupil = await _own_child(db, actor, pupil_id)

    terms = await all_of(
        db,
        scope.scoped_terms(actor)
        .where(Term.academic_session_id == scope.current_session_id(actor.school_id))
        .order_by(Term.number),
    )

    published = {
        report.term_id: report
        for report in await all_of(
            db,
            scope.scoped_term_reports(actor).where(TermReport.pupil_id == pupil_id),
        )
    }

    return pupil, [_availability(term, published.get(term.id)) for term in terms]


def _availability(term: Term, report: TermReport | None) -> Availability:
    # `scoped_term_reports` already filters a parent to published rows, so a
    # report arriving here at all means it is available. A draft or withheld
    # one is simply absent — invisible, not forbidden (R12).
    available = report is not None
    return Availability(
        term_id=term.id,
        term_label=TERM_NAMES.get(term.number, term.number.value),
        available=available,
        published_at=report.published_at if report else None,
        acknowledged_at=report.parent_acknowledged_at if report else None,
        message=None if available else UNAVAILABLE_MESSAGE,
    )


async def report_or_message(
    db: AsyncSession, actor: User, *, pupil_id: uuid.UUID, term_id: uuid.UUID
) -> tuple[Pupil, Term, TermReport | None, str | None]:
    """One term's report, or R12's sentence.

    Returns the message rather than raising, because "not yet available" is a
    normal answer to a reasonable question — the single most common thing a
    parent will do in this system is open a result the evening before it is
    released. A 404 would be true but unhelpful, and a 403 would confirm the
    report exists.
    """
    pupil = await _own_child(db, actor, pupil_id)
    term = await one_or_404(db, scope.scoped_terms(actor).where(Term.id == term_id), "term")

    report = await db.scalar(
        scope.scoped_term_reports(actor).where(
            TermReport.pupil_id == pupil_id, TermReport.term_id == term_id
        )
    )

    if report is None:
        return pupil, term, None, UNAVAILABLE_MESSAGE
    return pupil, term, report, None


async def guardians_of(db: AsyncSession, actor: User, pupil_id: uuid.UUID) -> Sequence[uuid.UUID]:
    """Which accounts may see this pupil's results. Used by the admin screens."""
    if not await db.scalar(
        select(Pupil.id).where(
            Pupil.id.in_(scope.scoped_pupils(actor).with_only_columns(Pupil.id)),
            Pupil.id == pupil_id,
        )
    ):
        raise NotFound("No such pupil.")

    return await all_of(
        db,
        select(GuardianPupil.guardian_user_id).where(GuardianPupil.pupil_id == pupil_id),
    )


async def acknowledge(
    db: AsyncSession,
    actor: User,
    *,
    pupil_id: uuid.UUID,
    term_id: uuid.UUID,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> TermReport:
    """A parent confirms they have seen the card (§8.5, A8).

    This replaces the signature and the physical return of the paper card:
    "Please return this card to the School on ___ when next term begins".

    Idempotent. A parent who taps twice, or opens the page on a phone and
    again on a laptop, has still acknowledged once — and the first moment is
    the true one, so a second tap does not move it.
    """
    # For its refusal, not its value: a pupil who is not this parent's child
    # is a 404 here, before anything is read or written.
    await _own_child(db, actor, pupil_id)
    report = await db.scalar(
        scope.scoped_term_reports(actor).where(
            TermReport.pupil_id == pupil_id, TermReport.term_id == term_id
        )
    )
    if report is None:
        # Unpublished or withheld. R12 again: invisible, not forbidden — and
        # there is nothing to acknowledge.
        raise NotFound(UNAVAILABLE_MESSAGE)

    if report.parent_acknowledged_at is None:
        report.parent_acknowledged_at = dt.datetime.now(dt.UTC)
        await db.flush()
        await audit.record(
            db,
            school_id=actor.school_id,
            action=AuditAction.REPORT_ACKNOWLEDGED,
            entity_type="term_report",
            entity_id=report.id,
            actor_id=actor.id,
            after={"acknowledged": True},
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await db.commit()

    # The report id alone, deliberately. It identifies the row for support
    # work without naming a child, and CLAUDE.md forbids "a pupil's identity
    # in logs". `test_logs_name_no_pupil` keeps it that way.
    logger.info("report acknowledged", extra={"report_id": str(report.id)})
    return report
