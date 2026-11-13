"""Accounts and their refresh tokens (ARCHITECTURE.md §4.1, §5.1)."""

import datetime as dt
import enum
import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, INET
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utc_now_column, uuid_pk


class UserRole(enum.StrEnum):
    """The four roles of §5.2.

    B2 settled that the head teacher and the admin are **two distinct people**
    (docs/DECISIONS.md): the head teacher approves, the admin publishes, and
    the separation is what gives §4.9's audit trail two signatures rather than
    one. Should one person ever need both, they get two accounts — this stays a
    single-valued column.
    """

    ADMIN = "admin"
    HEAD_TEACHER = "head_teacher"
    TEACHER = "teacher"
    PARENT = "parent"


# native_enum with an explicit name, so Alembic emits CREATE TYPE user_role.
user_role_enum = Enum(
    UserRole,
    name="user_role",
    values_callable=lambda enum_cls: [member.value for member in enum_cls],
)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "email IS NOT NULL OR phone IS NOT NULL",
            name="identifier_present",
        ),
        # Partial unique indexes: two users may both have a NULL email, but
        # never the same one. A plain UNIQUE would not allow the first part.
        Index(
            "uq_users_school_id_email",
            "school_id",
            "email",
            unique=True,
            postgresql_where=text("email IS NOT NULL"),
        ),
        Index(
            "uq_users_school_id_phone",
            "school_id",
            "phone",
            unique=True,
            postgresql_where=text("phone IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id"), nullable=False, index=True
    )
    role: Mapped[UserRole] = mapped_column(user_role_enum, nullable=False)

    # citext: parents will type Ada@example.com one day and ada@example.com the
    # next, and both must reach the same account.
    email: Mapped[str | None] = mapped_column(CITEXT)
    phone: Mapped[str | None] = mapped_column(Text)

    # Argon2id. Never serialised — no Pydantic Read schema exposes this field.
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)

    must_change_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    # A parent who signed themselves up and is waiting for an admin (D126).
    # Also inactive, so every request and every sign-in refuses them; the flag
    # is what lets sign-in say "waiting for approval" rather than "wrong
    # password", and lets the admin's dashboard find them.
    pending_approval: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    last_login_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    failed_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    locked_until: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = utc_now_column(nullable=False)

    def __repr__(self) -> str:
        # Deliberately no email, phone or name: a repr reaches logs and
        # tracebacks, and CLAUDE.md forbids a person's identity in either.
        return f"<User {self.id} role={self.role.value}>"


class RefreshToken(Base):
    """Opaque refresh tokens with rotation and reuse detection (§5.1).

    Not in §4 — §5.1 requires the behaviour without specifying the table.
    Recorded as an addition in docs/DECISIONS.md.

    Only the hash is stored. A database disclosure then yields nothing an
    attacker can present, exactly as with passwords.

    `family_id` groups every token descended from one login. Rotation issues a
    successor in the same family; presenting an already-used token means the
    chain has leaked, so the whole family is revoked rather than just that one.
    """

    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = uuid_pk()
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True, index=True)
    family_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)

    issued_at: Mapped[dt.datetime] = utc_now_column(nullable=False)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("refresh_tokens.id", ondelete="SET NULL")
    )

    def __repr__(self) -> str:
        return f"<RefreshToken {self.id} family={self.family_id}>"


class LoginAttempt(Base):
    """One login attempt from one IP address (ARCHITECTURE.md §5.1).

    §5.1 asks for two defences and this is the second: "lock for 15 minutes
    after 5 failed attempts; **rate-limit login by IP too**". The lockout is
    per account, and it cannot see the attack that matters here — an attacker
    spraying *identifiers*, where no single account ever reaches five
    failures. A login with an unknown identifier does not even write an audit
    row, because there is no `school_id` to attach it to.

    Hence a table of its own, and the only one in this schema with **no
    `school_id`**: an attempt is recorded before any user is found, so there
    is no school to attribute it to yet. Nothing in it is tenant data — an IP
    address and a moment, no identifier, because the identifier is a parent's
    phone number (§5.1) and this is a log.

    Rows are pruned as they are counted; see `services/ratelimit.py`.
    """

    __tablename__ = "login_attempts"

    # A bigint identity rather than a uuid7: these rows are written on every
    # attempt, counted in bulk and thrown away, and nothing ever references
    # one by id.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    ip_address: Mapped[str] = mapped_column(INET, nullable=False)
    attempted_at: Mapped[dt.datetime] = utc_now_column(nullable=False)

    __table_args__ = (
        # The only query this table serves: count one address over a window,
        # newest first. Descending so the window scan stops early.
        Index(
            "ix_login_attempts_ip_address_attempted_at",
            "ip_address",
            text("attempted_at DESC"),
        ),
    )

    def __repr__(self) -> str:
        return f"<LoginAttempt {self.id} at={self.attempted_at.isoformat()}>"
