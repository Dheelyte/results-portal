"""R14's state machine for a class's term (ARCHITECTURE.md §4.8, §6 R14).

    not_started -> in_progress -> submitted -> approved
                        ^             |
                        +-- returned <+

Three things live here: which states a teacher may still write in, the
`not_started -> in_progress` move that the first save makes, and from
milestone 8 the transition table itself. Submit is wired up now; return and
approve are milestone 9 and use the same `transition` function, which is why
it takes the target state rather than being one function per move.
"""

import datetime as dt
import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import scope
from app.models import AuditAction, ClassTermState, ClassTermStatus, User
from app.services import audit
from app.services.errors import Conflict

logger = logging.getLogger(__name__)

# States in which a teacher may still change scores and narrative.
#
# `returned` is editable by design: the head teacher sent it back precisely so
# it could be corrected. `submitted` is not — it is waiting on review, and a
# score changing underneath a reviewer is the bug this state exists to stop.
TEACHER_EDITABLE = frozenset(
    {ClassTermState.NOT_STARTED, ClassTermState.IN_PROGRESS, ClassTermState.RETURNED}
)

LOCKED_MESSAGE = {
    ClassTermState.SUBMITTED: (
        "This class has been submitted for review, so its scores are now read-only. "
        "Ask the head teacher to return it if a correction is needed."
    ),
    ClassTermState.APPROVED: (
        "This class has been approved, so its scores are final. "
        "Only an administrator may change them now."
    ),
}


async def state_of(
    db: AsyncSession, actor: User, *, class_id: uuid.UUID, term_id: uuid.UUID
) -> ClassTermState:
    """The class's state this term.

    A class with no row has not been started. That is a real state rather than
    missing data, so it is reported as one instead of as `None` — the grid
    shows the same thing either way and no caller has to handle both.
    """
    record = await db.scalar(
        scope.scoped_class_term_status(actor).where(
            ClassTermStatus.class_id == class_id, ClassTermStatus.term_id == term_id
        )
    )
    return record.state if record is not None else ClassTermState.NOT_STARTED


def teacher_may_edit(state: ClassTermState) -> bool:
    return state in TEACHER_EDITABLE


def refuse_if_locked(state: ClassTermState) -> None:
    """Raise R14's 409 if teachers can no longer write to this class.

    The message says what to do next. "Cannot submit" with no explanation
    generates support calls every term (R10), and the same is true of a grid
    that silently stops saving.
    """
    if teacher_may_edit(state):
        return
    raise Conflict(LOCKED_MESSAGE.get(state, "This class is no longer open for changes."))


async def mark_in_progress(
    db: AsyncSession,
    actor: User,
    *,
    class_id: uuid.UUID,
    term_id: uuid.UUID,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> ClassTermState:
    """Move `not_started` to `in_progress`, leaving every other state alone.

    Called on the first successful write of the term, so the head teacher's
    review queue can tell a class nobody has touched from one in progress
    without counting score rows.
    """
    record = await db.scalar(
        scope.scoped_class_term_status(actor).where(
            ClassTermStatus.class_id == class_id, ClassTermStatus.term_id == term_id
        )
    )

    if record is None:
        record = ClassTermStatus(
            school_id=actor.school_id,
            class_id=class_id,
            term_id=term_id,
            state=ClassTermState.IN_PROGRESS,
        )
        db.add(record)
        await db.flush()
    elif record.state is ClassTermState.NOT_STARTED:
        record.state = ClassTermState.IN_PROGRESS
        await db.flush()
    else:
        return record.state

    await audit.record(
        db,
        school_id=actor.school_id,
        action=AuditAction.CLASS_TERM_STARTED,
        entity_type="class_term_status",
        entity_id=record.id,
        actor_id=actor.id,
        after={"state": record.state.value, "class_id": str(class_id), "term_id": str(term_id)},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    return record.state


# ---------------------------------------------------------------------------
# R14's transitions
# ---------------------------------------------------------------------------
#
# One legal predecessor set per transition, declared as data. R14 says
# "legal transitions only; anything else is 409", and a table makes that
# checkable rather than scattered through three services.

LEGAL_PREDECESSORS: dict[ClassTermState, frozenset[ClassTermState]] = {
    ClassTermState.IN_PROGRESS: frozenset({ClassTermState.NOT_STARTED}),
    # Submitting from `not_started` is legal in the state machine's own terms,
    # and R10 refuses it anyway — a class nobody has touched is missing
    # everything. Listed so the 422 comes from the gate, which can say what is
    # missing, rather than from a 409 that cannot.
    ClassTermState.SUBMITTED: frozenset(
        {ClassTermState.NOT_STARTED, ClassTermState.IN_PROGRESS, ClassTermState.RETURNED}
    ),
    ClassTermState.RETURNED: frozenset({ClassTermState.SUBMITTED}),
    ClassTermState.APPROVED: frozenset({ClassTermState.SUBMITTED}),
}

ALREADY_THERE = {
    ClassTermState.SUBMITTED: (
        "This class has already been submitted and is waiting for the head teacher."
    ),
    ClassTermState.APPROVED: "This class has already been approved.",
}


async def transition(
    db: AsyncSession,
    actor: User,
    *,
    class_id: uuid.UUID,
    term_id: uuid.UUID,
    to: ClassTermState,
    action: str,
    note: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> ClassTermStatus:
    """Move a class to `to`, or raise R14's 409.

    The row is created if it does not exist, because `not_started` is a state
    rather than missing data (see `state_of`).
    """
    record = await db.scalar(
        scope.scoped_class_term_status(actor).where(
            ClassTermStatus.class_id == class_id, ClassTermStatus.term_id == term_id
        )
    )
    current = record.state if record is not None else ClassTermState.NOT_STARTED

    if current is to:
        raise Conflict(
            ALREADY_THERE.get(to, f"This class is already {to.value.replace('_', ' ')}.")
        )

    if current not in LEGAL_PREDECESSORS[to]:
        raise Conflict(
            f"A class that is {current.value.replace('_', ' ')} cannot be "
            f"{to.value.replace('_', ' ')}."
        )

    if record is None:
        record = ClassTermStatus(
            school_id=actor.school_id, class_id=class_id, term_id=term_id, state=to
        )
        db.add(record)
    else:
        record.state = to

    now = dt.datetime.now(dt.UTC)
    if to is ClassTermState.SUBMITTED:
        record.submitted_at = now
        record.submitted_by = actor.id
        # A class resubmitted after a return starts the review afresh.
        record.return_note = None
    if to in (ClassTermState.APPROVED, ClassTermState.RETURNED):
        record.reviewed_at = now
        record.reviewed_by = actor.id
    if to is ClassTermState.RETURNED:
        record.return_note = note

    await db.flush()

    await audit.record(
        db,
        school_id=actor.school_id,
        action=action,
        entity_type="class_term_status",
        entity_id=record.id,
        actor_id=actor.id,
        before={"state": current.value},
        after={
            "state": to.value,
            "class_id": str(class_id),
            "term_id": str(term_id),
            # The note is the head teacher writing to the class teacher about
            # a class, not about a child, so it is safe to record and useful
            # when "why was this returned" is asked three weeks later.
            **({"note": note} if note else {}),
        },
        ip_address=ip_address,
        user_agent=user_agent,
    )
    return record
