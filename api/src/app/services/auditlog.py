"""Reading the audit log (ARCHITECTURE.md §4.9, §7, §5.2).

§4.9 says what goes in; this is how it comes out. §5.2 gives it to the **admin
in full and the head teacher read-only**, which in a read-only resource means
the same rows — the distinction is that no endpoint lets either of them change
one, and nothing in the system deletes a row.

The log is the one place scores and before/after values legitimately travel in
a payload (R13's edits record them, because "what did this card say before?"
cannot be answered without them). Its audience is the two roles who already
see every card, and `scoped_audit_log` keeps it inside one school.
"""

import datetime as dt
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import scope
from app.models import AuditLog, User
from app.services.support import rows_of

logger = logging.getLogger(__name__)

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


@dataclass(frozen=True)
class Entry:
    """One audit row, with the actor's name resolved."""

    id: uuid.UUID
    action: str
    entity_type: str
    entity_id: uuid.UUID | None
    actor_id: uuid.UUID | None
    actor_name: str | None
    before: dict | None
    after: dict | None
    reason: str | None
    ip_address: str | None
    created_at: dt.datetime


@dataclass(frozen=True)
class Page:
    entries: list[Entry]
    total: int
    limit: int
    offset: int


async def read(
    db: AsyncSession,
    actor: User,
    *,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    action: str | None = None,
    actor_id: uuid.UUID | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> Page:
    """A page of the log, newest first.

    Newest first because the question is almost always "what just happened" —
    §4.9's own index is `(entity_type, entity_id, created_at DESC)`, and §7
    exposes exactly those two filters.
    """
    limit = max(1, min(limit, MAX_PAGE_SIZE))
    offset = max(0, offset)

    stmt = scope.scoped_audit_log(actor)
    if entity_type is not None:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if entity_id is not None:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    if action is not None:
        stmt = stmt.where(AuditLog.action == action)
    if actor_id is not None:
        stmt = stmt.where(AuditLog.actor_id == actor_id)

    total = await db.scalar(
        select(func.count()).select_from(stmt.with_only_columns(AuditLog.id).subquery())
    )

    rows = await rows_of(
        db,
        select(AuditLog, User.full_name)
        .outerjoin(User, User.id == AuditLog.actor_id)
        .where(AuditLog.id.in_(stmt.with_only_columns(AuditLog.id)))
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(limit)
        .offset(offset),
    )

    return Page(
        entries=[
            Entry(
                id=row.id,
                action=row.action,
                entity_type=row.entity_type,
                entity_id=row.entity_id,
                actor_id=row.actor_id,
                actor_name=actor_name,
                before=row.before,
                after=row.after,
                reason=row.reason,
                # INET comes back as an object; the screen wants a string.
                ip_address=str(row.ip_address) if row.ip_address else None,
                created_at=row.created_at,
            )
            for row, actor_name in rows
        ],
        total=total or 0,
        limit=limit,
        offset=offset,
    )


async def actions(db: AsyncSession, actor: User) -> Sequence[str]:
    """The distinct actions present, so the filter is a list rather than a
    free-text box the reader has to guess the vocabulary for."""
    return await rows_of(
        db,
        scope.scoped_audit_log(actor)
        .with_only_columns(AuditLog.action)
        .distinct()
        .order_by(AuditLog.action),
    )
