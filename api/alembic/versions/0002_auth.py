"""auth: schools, users, refresh tokens, audit log

The subset of ARCHITECTURE.md §4 that milestone 2 needs:

- §4.1 schools and users, with the user_role enum of §5.2
- §5.1 refresh_tokens — not in §4; §5.1 specifies the behaviour (opaque,
  hashed, rotating, reuse-detecting) without the table
- §4.9 audit_log, pulled forward from milestone 3 because §4.9 requires a row
  for every failed login and every account creation

The rest of §4 arrives in milestone 3.

Two corrections to what autogenerate produced, both of which would have
bitten later:

1. `CREATE EXTENSION citext` — users.email is citext (§4.1) and autogenerate
   emits the column type without ever creating the extension, so upgrading a
   fresh database failed.
2. Dropping the `user_role` type on downgrade — SQLAlchemy creates an enum
   type alongside its table but does not drop it, so downgrade followed by
   upgrade failed with "type user_role already exists".

Revision ID: 0002
Revises: 0001_baseline
Created: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


user_role = sa.Enum("admin", "head_teacher", "teacher", "parent", name="user_role")


def upgrade() -> None:
    # users.email is citext so that Ada@example.com and ada@example.com reach
    # the same account (§4.1). The extension must exist before the column.
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")

    op.create_table(
        "schools",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("short_name", sa.Text(), nullable=False),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("phone", sa.Text(), nullable=True),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("logo_url", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_schools")),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("school_id", sa.Uuid(), nullable=False),
        sa.Column("role", user_role, nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=True),
        sa.Column("phone", sa.Text(), nullable=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("must_change_password", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "email IS NOT NULL OR phone IS NOT NULL", name=op.f("ck_users_identifier_present")
        ),
        sa.ForeignKeyConstraint(
            ["school_id"], ["schools.id"], name=op.f("fk_users_school_id_schools")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_index(op.f("ix_users_school_id"), "users", ["school_id"], unique=False)
    # Partial, so that many users may have a NULL email but never the same one.
    op.create_index(
        "uq_users_school_id_email",
        "users",
        ["school_id", "email"],
        unique=True,
        postgresql_where=sa.text("email IS NOT NULL"),
    )
    op.create_index(
        "uq_users_school_id_phone",
        "users",
        ["school_id", "phone"],
        unique=True,
        postgresql_where=sa.text("phone IS NOT NULL"),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("school_id", sa.Uuid(), nullable=False),
        # Nullable: a failed login has no identified actor, which is the whole
        # reason for recording it.
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name=op.f("fk_audit_log_actor_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["school_id"], ["schools.id"], name=op.f("fk_audit_log_school_id_schools")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )
    op.create_index(
        "ix_audit_log_entity", "audit_log", ["entity_type", "entity_id", "created_at"], unique=False
    )
    op.create_index(
        "ix_audit_log_school_created", "audit_log", ["school_id", "created_at"], unique=False
    )

    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("school_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        # Only the hash is stored; the token itself exists only in the cookie.
        sa.Column("token_hash", sa.Text(), nullable=False),
        # Groups every token descended from one login, so that reuse of a
        # consumed token can revoke the whole chain (§5.1).
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column(
            "issued_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["replaced_by"],
            ["refresh_tokens.id"],
            name=op.f("fk_refresh_tokens_replaced_by_refresh_tokens"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["school_id"], ["schools.id"], name=op.f("fk_refresh_tokens_school_id_schools")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_refresh_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_tokens")),
    )
    op.create_index(
        op.f("ix_refresh_tokens_family_id"), "refresh_tokens", ["family_id"], unique=False
    )
    op.create_index(
        op.f("ix_refresh_tokens_token_hash"), "refresh_tokens", ["token_hash"], unique=True
    )
    op.create_index(op.f("ix_refresh_tokens_user_id"), "refresh_tokens", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_refresh_tokens_user_id"), table_name="refresh_tokens")
    op.drop_index(op.f("ix_refresh_tokens_token_hash"), table_name="refresh_tokens")
    op.drop_index(op.f("ix_refresh_tokens_family_id"), table_name="refresh_tokens")
    op.drop_table("refresh_tokens")

    op.drop_index("ix_audit_log_school_created", table_name="audit_log")
    op.drop_index("ix_audit_log_entity", table_name="audit_log")
    op.drop_table("audit_log")

    op.drop_index(
        "uq_users_school_id_phone",
        table_name="users",
        postgresql_where=sa.text("phone IS NOT NULL"),
    )
    op.drop_index(
        "uq_users_school_id_email",
        table_name="users",
        postgresql_where=sa.text("email IS NOT NULL"),
    )
    op.drop_index(op.f("ix_users_school_id"), table_name="users")
    op.drop_table("users")

    op.drop_table("schools")

    # SQLAlchemy creates the enum type with its table but never drops it.
    # Without this, downgrade then upgrade fails with "type already exists".
    user_role.drop(op.get_bind(), checkfirst=True)

    # The citext extension is deliberately left in place. Dropping it would
    # cascade to any other object using the type, and it is harmless to keep.
