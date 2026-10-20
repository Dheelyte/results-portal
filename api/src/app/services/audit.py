"""The single writer for the audit log (ARCHITECTURE.md §4.9).

Everything that must be audited goes through `record()`. One writer means one
place to enforce what may never be written: CLAUDE.md forbids scores,
comments, tokens, password hashes and pupil identity from reaching a log, and
`audit_log.before` / `after` are as much a log as stdout is.
"""

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog

logger = logging.getLogger(__name__)

# Keys that must never appear in a before/after payload, whatever the caller
# passes. Matched case-insensitively against the key name.
FORBIDDEN_KEYS = frozenset(
    {
        "password",
        "password_hash",
        "new_password",
        "current_password",
        "temporary_password",
        "token",
        "token_hash",
        "access_token",
        "refresh_token",
        "secret",
        "jwt_secret",
    }
)

REDACTED = "[redacted]"


def scrub(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Replace the value of any forbidden key with a marker.

    Recurses into nested dictionaries and lists. The key is kept so the shape
    of the change stays legible — "the password changed" is the audit-worthy
    fact, and the value never is.
    """
    if payload is None:
        return None

    scrubbed: dict[str, Any] = {}
    for key, value in payload.items():
        if key.lower() in FORBIDDEN_KEYS:
            scrubbed[key] = REDACTED
        elif isinstance(value, dict):
            scrubbed[key] = scrub(value)
        elif isinstance(value, list):
            scrubbed[key] = [scrub(v) if isinstance(v, dict) else v for v in value]
        else:
            scrubbed[key] = value
    return scrubbed


async def record(
    session: AsyncSession,
    *,
    school_id: uuid.UUID,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    reason: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> AuditLog:
    """Append an audit row.

    Added to the session but not committed — the caller's transaction decides,
    so an audited action and its record succeed or fail together.
    """
    entry = AuditLog(
        school_id=school_id,
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before=scrub(before),
        after=scrub(after),
        reason=reason,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    session.add(entry)

    # The identifiers are safe to log; the payloads are not, and are omitted.
    logger.info(
        "audit",
        extra={
            "action": action,
            "entity_type": entity_type,
            "entity_id": str(entity_id) if entity_id else None,
            "actor_id": str(actor_id) if actor_id else None,
        },
    )
    return entry
