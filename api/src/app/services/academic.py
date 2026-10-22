"""Academic structure: sessions, terms, assessment periods, classes, houses
(ARCHITECTURE.md §1.1, §4.2).

Every rule here, none in a router (CLAUDE.md rule 2). The rules are mostly
about coherence — a term that ends before it starts, two terms both claiming to
be current — and each one exists because the alternative is a wrong report card
that nobody can explain.
"""

import datetime as dt
import logging
import uuid
from collections.abc import Sequence

from sqlalchemy import case, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import scope
from app.models import (
    AcademicSession,
    AssessmentPeriod,
    AuditAction,
    Class,
    House,
    Term,
    TermHalf,
    TermNumber,
    User,
)
from app.services import audit
from app.services.errors import Conflict, Invalid
from app.services.support import all_of, integrity_guard, one_or_404

logger = logging.getLogger(__name__)

# Fields recorded in the audit log. Named explicitly — see audit.snapshot.
SESSION_FIELDS = ("name", "starts_on", "ends_on", "is_current")
TERM_FIELDS = (
    "academic_session_id",
    "number",
    "starts_on",
    "ends_on",
    "times_school_opened",
    "next_resumption_on",
    "card_return_on",
    "is_current",
)
PERIOD_FIELDS = ("term_id", "half", "opens_on", "closes_on")

# Chronological, which the enum's own alphabetical order is not.
TERM_ORDER = case(
    {TermNumber.FIRST: 1, TermNumber.SECOND: 2, TermNumber.THIRD: 3},
    value=Term.number,
)


def _check_range(starts_on: dt.date, ends_on: dt.date, what: str) -> None:
    if starts_on >= ends_on:
        raise Invalid(f"The {what} must start before it ends.")


# ---------------------------------------------------------------------------
# Academic sessions
# ---------------------------------------------------------------------------


async def list_sessions(db: AsyncSession, actor: User) -> Sequence[AcademicSession]:
    return await all_of(
        db, scope.scoped_academic_sessions(actor).order_by(AcademicSession.starts_on.desc())
    )


async def get_session_record(
    db: AsyncSession, actor: User, session_id: uuid.UUID
) -> AcademicSession:
    return await one_or_404(
        db,
        scope.scoped_academic_sessions(actor).where(AcademicSession.id == session_id),
        "academic session",
    )


async def create_session(
    db: AsyncSession,
    actor: User,
    *,
    name: str,
    starts_on: dt.date,
    ends_on: dt.date,
    is_current: bool = False,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> AcademicSession:
    _check_range(starts_on, ends_on, "session")

    record = AcademicSession(
        school_id=actor.school_id,
        name=name.strip(),
        starts_on=starts_on,
        ends_on=ends_on,
        is_current=False,
    )
    db.add(record)

    async with integrity_guard(db, "A session with that name already exists."):
        await db.flush()

    await audit.record(
        db,
        school_id=actor.school_id,
        actor_id=actor.id,
        action=AuditAction.SESSION_CREATED,
        entity_type="academic_session",
        entity_id=record.id,
        after=audit.snapshot(record, SESSION_FIELDS),
        ip_address=ip_address,
        user_agent=user_agent,
    )

    if is_current:
        await _make_session_current(db, actor, record, ip_address, user_agent)

    await db.commit()
    await db.refresh(record)
    return record


async def make_session_current(
    db: AsyncSession,
    actor: User,
    session_id: uuid.UUID,
    *,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> AcademicSession:
    record = await get_session_record(db, actor, session_id)
    await _make_session_current(db, actor, record, ip_address, user_agent)
    await db.commit()
    await db.refresh(record)
    return record


async def _make_session_current(
    db: AsyncSession,
    actor: User,
    record: AcademicSession,
    ip_address: str | None,
    user_agent: str | None,
) -> None:
    """Promote one session and demote every other, in one statement.

    Exactly one session may be current, because `scope.current_session_id`
    resolves it with `LIMIT 1` — two current sessions would not fail, they
    would silently pick one, and half the portal would scope itself to last
    year. Enforced here rather than by a unique index so the demotion is part
    of the same transaction as the promotion; a partial unique index would
    reject the intermediate state where both are briefly true.
    """
    await db.execute(
        update(AcademicSession)
        .where(
            AcademicSession.school_id == actor.school_id,
            AcademicSession.id != record.id,
            AcademicSession.is_current.is_(True),
        )
        .values(is_current=False)
    )
    record.is_current = True

    # A current term in a session that is no longer current leaves the two
    # pointers disagreeing. Demote it; the admin picks the new term.
    await db.execute(
        update(Term)
        .where(
            Term.school_id == actor.school_id,
            Term.academic_session_id != record.id,
            Term.is_current.is_(True),
        )
        .values(is_current=False)
    )

    await audit.record(
        db,
        school_id=actor.school_id,
        actor_id=actor.id,
        action=AuditAction.SESSION_MADE_CURRENT,
        entity_type="academic_session",
        entity_id=record.id,
        after={"name": record.name, "is_current": True},
        ip_address=ip_address,
        user_agent=user_agent,
    )


# ---------------------------------------------------------------------------
# Terms and assessment periods
# ---------------------------------------------------------------------------


async def list_terms(
    db: AsyncSession, actor: User, *, academic_session_id: uuid.UUID | None = None
) -> Sequence[Term]:
    stmt = scope.scoped_terms(actor)
    if academic_session_id is not None:
        stmt = stmt.where(Term.academic_session_id == academic_session_id)
    return await all_of(db, stmt.order_by(TERM_ORDER))


async def get_term(db: AsyncSession, actor: User, term_id: uuid.UUID) -> Term:
    return await one_or_404(db, scope.scoped_terms(actor).where(Term.id == term_id), "term")


async def create_term(
    db: AsyncSession,
    actor: User,
    *,
    academic_session_id: uuid.UUID,
    number: TermNumber,
    starts_on: dt.date,
    ends_on: dt.date,
    times_school_opened: int | None = None,
    next_resumption_on: dt.date | None = None,
    card_return_on: dt.date | None = None,
    is_current: bool = False,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> Term:
    """Create a term **and both of its assessment periods**.

    §1.1 states the two halves as a fact about the domain, not a choice an
    admin makes: "each term has two assessment periods … this is the single
    most important structural fact about this system". Creating them with the
    term means a term can never exist in a state where a teacher has nowhere
    to enter scores. Their dates are set afterwards through
    `save_assessment_period`.
    """
    academic = await get_session_record(db, actor, academic_session_id)

    _check_range(starts_on, ends_on, "term")
    if starts_on < academic.starts_on or ends_on > academic.ends_on:
        raise Invalid(
            f"A term must fall inside its session, which runs from "
            f"{academic.starts_on.isoformat()} to {academic.ends_on.isoformat()}."
        )

    record = Term(
        school_id=actor.school_id,
        academic_session_id=academic.id,
        number=number,
        starts_on=starts_on,
        ends_on=ends_on,
        times_school_opened=times_school_opened,
        next_resumption_on=next_resumption_on,
        card_return_on=card_return_on,
        is_current=False,
    )
    db.add(record)

    async with integrity_guard(db, "That term already exists for this session."):
        await db.flush()

    for half in TermHalf:
        db.add(AssessmentPeriod(school_id=actor.school_id, term_id=record.id, half=half))

    await audit.record(
        db,
        school_id=actor.school_id,
        actor_id=actor.id,
        action=AuditAction.TERM_CREATED,
        entity_type="term",
        entity_id=record.id,
        after=audit.snapshot(record, TERM_FIELDS),
        ip_address=ip_address,
        user_agent=user_agent,
    )

    if is_current:
        await _make_term_current(db, actor, record, ip_address, user_agent)

    await db.commit()
    await db.refresh(record)
    return record


async def update_term(
    db: AsyncSession,
    actor: User,
    term_id: uuid.UUID,
    *,
    changes: dict[str, object],
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> Term:
    """Patch a term's dates and calendar figures.

    `times_school_opened` is the reason this endpoint exists: R9 measures
    attendance against it, and it is rarely known on the day the term is
    created.
    """
    record = await get_term(db, actor, term_id)
    before = audit.snapshot(record, TERM_FIELDS)

    make_current = changes.pop("is_current", None)

    for field, value in changes.items():
        setattr(record, field, value)

    _check_range(record.starts_on, record.ends_on, "term")
    academic = await get_session_record(db, actor, record.academic_session_id)
    if record.starts_on < academic.starts_on or record.ends_on > academic.ends_on:
        raise Invalid(
            f"A term must fall inside its session, which runs from "
            f"{academic.starts_on.isoformat()} to {academic.ends_on.isoformat()}."
        )
    if record.times_school_opened is not None and record.times_school_opened < 0:
        raise Invalid("Times school opened cannot be negative.")

    await _check_periods_within_term(db, actor, record)

    await audit.record(
        db,
        school_id=actor.school_id,
        actor_id=actor.id,
        action=AuditAction.TERM_UPDATED,
        entity_type="term",
        entity_id=record.id,
        before=before,
        after=audit.snapshot(record, TERM_FIELDS),
        ip_address=ip_address,
        user_agent=user_agent,
    )

    if make_current:
        await _make_term_current(db, actor, record, ip_address, user_agent)

    await db.commit()
    await db.refresh(record)
    return record


async def make_term_current(
    db: AsyncSession,
    actor: User,
    term_id: uuid.UUID,
    *,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> Term:
    record = await get_term(db, actor, term_id)
    await _make_term_current(db, actor, record, ip_address, user_agent)
    await db.commit()
    await db.refresh(record)
    return record


async def _make_term_current(
    db: AsyncSession,
    actor: User,
    record: Term,
    ip_address: str | None,
    user_agent: str | None,
) -> None:
    """Promote one term and demote the rest, school-wide.

    Refuses a term outside the current session rather than quietly switching
    the session too. Two pointers, two deliberate acts: an admin who meant to
    move the whole school into next year should say so, because that changes
    which classes, enrolments and teaching assignments the portal resolves.
    """
    academic = await get_session_record(db, actor, record.academic_session_id)
    if not academic.is_current:
        raise Conflict(
            f"{academic.name} is not the current session. Make it current first, then set the term."
        )

    await db.execute(
        update(Term)
        .where(
            Term.school_id == actor.school_id,
            Term.id != record.id,
            Term.is_current.is_(True),
        )
        .values(is_current=False)
    )
    record.is_current = True

    await audit.record(
        db,
        school_id=actor.school_id,
        actor_id=actor.id,
        action=AuditAction.TERM_MADE_CURRENT,
        entity_type="term",
        entity_id=record.id,
        after={"number": record.number.value, "is_current": True},
        ip_address=ip_address,
        user_agent=user_agent,
    )


async def list_assessment_periods(
    db: AsyncSession, actor: User, term_id: uuid.UUID
) -> Sequence[AssessmentPeriod]:
    await get_term(db, actor, term_id)
    return await all_of(
        db,
        scope.scoped_assessment_periods(actor)
        .where(AssessmentPeriod.term_id == term_id)
        .order_by(
            case({TermHalf.FIRST_HALF: 1, TermHalf.SECOND_HALF: 2}, value=AssessmentPeriod.half)
        ),
    )


async def save_assessment_period(
    db: AsyncSession,
    actor: User,
    term_id: uuid.UUID,
    *,
    half: TermHalf,
    opens_on: dt.date | None,
    closes_on: dt.date | None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> tuple[AssessmentPeriod, bool]:
    """Set one half term's window, creating the row if it is missing.

    An upsert keyed on `half` rather than a plain insert, because the two rows
    already exist — `create_term` makes them — so the only thing a POST here
    can mean is "these are the dates". Returns whether a row was created, so
    the router can answer 201 or 200 honestly.
    """
    term = await get_term(db, actor, term_id)

    if opens_on and closes_on and opens_on > closes_on:
        raise Invalid("A half term must open before it closes.")

    for label, value in (("opens_on", opens_on), ("closes_on", closes_on)):
        if value is not None and not (term.starts_on <= value <= term.ends_on):
            raise Invalid(
                f"The half term's {label.replace('_', ' ')} must fall inside the term, "
                f"which runs from {term.starts_on.isoformat()} to {term.ends_on.isoformat()}."
            )

    record = await db.scalar(
        scope.scoped_assessment_periods(actor).where(
            AssessmentPeriod.term_id == term_id, AssessmentPeriod.half == half
        )
    )
    created = record is None
    before = None if created else audit.snapshot(record, PERIOD_FIELDS)

    if record is None:
        record = AssessmentPeriod(school_id=actor.school_id, term_id=term_id, half=half)
        db.add(record)

    record.opens_on = opens_on
    record.closes_on = closes_on

    async with integrity_guard(db, "That half term already exists for this term."):
        await db.flush()

    await audit.record(
        db,
        school_id=actor.school_id,
        actor_id=actor.id,
        action=AuditAction.ASSESSMENT_PERIOD_SAVED,
        entity_type="assessment_period",
        entity_id=record.id,
        before=before,
        after=audit.snapshot(record, PERIOD_FIELDS),
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()
    await db.refresh(record)
    return record, created


async def _check_periods_within_term(db: AsyncSession, actor: User, term: Term) -> None:
    """Refuse a term whose new dates would exclude its own half terms."""
    periods = await all_of(
        db, scope.scoped_assessment_periods(actor).where(AssessmentPeriod.term_id == term.id)
    )
    for period in periods:
        for value in (period.opens_on, period.closes_on):
            if value is not None and not (term.starts_on <= value <= term.ends_on):
                raise Invalid(
                    "These term dates would leave a half term's window outside the term. "
                    "Adjust the half term dates first."
                )


# ---------------------------------------------------------------------------
# Classes and houses
# ---------------------------------------------------------------------------


async def list_classes(
    db: AsyncSession, actor: User, *, include_inactive: bool = False
) -> Sequence[Class]:
    stmt = scope.scoped_classes(actor)
    if not include_inactive:
        stmt = stmt.where(Class.is_active.is_(True))
    return await all_of(db, stmt.order_by(Class.level_order, Class.name))


async def get_class(db: AsyncSession, actor: User, class_id: uuid.UUID) -> Class:
    return await one_or_404(db, scope.scoped_classes(actor).where(Class.id == class_id), "class")


async def create_class(
    db: AsyncSession,
    actor: User,
    *,
    name: str,
    level_order: int,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> Class:
    record = Class(school_id=actor.school_id, name=name.strip(), level_order=level_order)
    db.add(record)

    async with integrity_guard(db, "A class with that name already exists."):
        await db.flush()

    await audit.record(
        db,
        school_id=actor.school_id,
        actor_id=actor.id,
        action=AuditAction.CLASS_CREATED,
        entity_type="class",
        entity_id=record.id,
        after=audit.snapshot(record, ("name", "level_order", "is_active")),
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()
    await db.refresh(record)
    return record


async def list_houses(db: AsyncSession, actor: User) -> Sequence[House]:
    return await all_of(db, scope.scoped_houses(actor).order_by(House.name))


async def create_house(
    db: AsyncSession,
    actor: User,
    *,
    name: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> House:
    record = House(school_id=actor.school_id, name=name.strip())
    db.add(record)

    async with integrity_guard(db, "A house with that name already exists."):
        await db.flush()

    await audit.record(
        db,
        school_id=actor.school_id,
        actor_id=actor.id,
        action=AuditAction.HOUSE_CREATED,
        entity_type="house",
        entity_id=record.id,
        after={"name": record.name},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()
    await db.refresh(record)
    return record


async def resolve_session_id(
    db: AsyncSession, actor: User, academic_session_id: uuid.UUID | None
) -> uuid.UUID:
    """The session to act in: the one named, or the school's current one.

    Refuses to guess when no session is current. Silently falling back to the
    most recent would attach a class's subject list, a pupil's enrolment or a
    class teacher to the wrong year, and nobody would notice until the cards
    printed.

    One implementation, used by every service that takes an optional
    `academic_session_id`, because "which year is this?" must not have two
    answers.
    """
    if academic_session_id is not None:
        return (await get_session_record(db, actor, academic_session_id)).id

    current = await current_session_or_none(db, actor)
    if current is None:
        raise Conflict("No academic session is current. Create one and make it current first.")
    return current.id


async def current_session_or_none(db: AsyncSession, actor: User) -> AcademicSession | None:
    return await db.scalar(
        scope.scoped_academic_sessions(actor).where(AcademicSession.is_current.is_(True))
    )


async def current_term_or_none(db: AsyncSession, actor: User) -> Term | None:
    return await db.scalar(scope.scoped_terms(actor).where(Term.is_current.is_(True)))
