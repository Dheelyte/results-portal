"""The audit log (ARCHITECTURE.md §4.9).

Pulled forward from milestone 3, because §4.9 requires a row for **every failed
login** and every account creation — both milestone 2 events. Building auth
without it would mean shipping a known gap and backfilling nothing.

Rows are append-only. Nothing in the application updates or deletes one.
"""

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utc_now_column, uuid_pk


class AuditAction(str):
    """Action names, as plain strings rather than an enum.

    A database enum would need a migration for every new audited action, and
    §4.9's list grows with each milestone. The constants below are the names in
    use; they are a convenience, not a constraint.
    """

    LOGIN_SUCCEEDED = "login.succeeded"
    LOGIN_FAILED = "login.failed"
    LOGIN_LOCKED = "login.locked"
    LOGOUT = "logout"
    TOKEN_REFRESHED = "token.refreshed"
    TOKEN_REUSE_DETECTED = "token.reuse_detected"
    PASSWORD_CHANGED = "password.changed"
    USER_CREATED = "user.created"
    SCHOOL_CREATED = "school.created"


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_entity", "entity_type", "entity_id", "created_at"),
        Index("ix_audit_log_school_created", "school_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"), nullable=False)

    # Nullable: a failed login has no authenticated actor, and the whole point
    # of recording it is that we could not identify one.
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))

    action: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column()

    # Never a password, a hash, a token or a score. services/audit.py is the
    # only writer, and it is where that is enforced.
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    reason: Mapped[str | None] = mapped_column(Text)
    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = utc_now_column(nullable=False)

    def __repr__(self) -> str:
        return f"<AuditLog {self.action} {self.entity_type}:{self.entity_id}>"
