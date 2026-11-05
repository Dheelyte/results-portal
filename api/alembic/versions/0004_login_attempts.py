"""login attempts, for the per-IP rate limit (§5.1)

§5.1 asks for two defences on login and milestone 2 built only the first:
"lock for 15 minutes after 5 failed attempts; **rate-limit login by IP too**".
The lockout is per account, and the attack it cannot see is one address
spraying *identifiers* — no single account ever reaches five failures, and a
login with an unknown identifier does not even write an audit row, because
there is no `school_id` to attach it to.

So, a table. It is the only one in this schema with **no `school_id`**: an
attempt is recorded before any user is found, so there is no school to
attribute it to yet. It holds an address and a moment and nothing else — not
the identifier, which is a parent's phone number (§5.1).

Autogenerate produced this unaltered. Two choices worth naming: a `bigint`
identity rather than a uuid7, because these rows are written on every
attempt, counted in bulk and thrown away and nothing ever references one; and
`attempted_at DESC` in the index, because the only query it serves counts one
address backwards from now.

Revision ID: 0004
Revises: 0003
Created: 2026-11-05
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "login_attempts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("ip_address", postgresql.INET(), nullable=False),
        sa.Column(
            "attempted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_login_attempts")),
    )
    op.create_index(
        "ix_login_attempts_ip_address_attempted_at",
        "login_attempts",
        ["ip_address", sa.literal_column("attempted_at DESC")],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_login_attempts_ip_address_attempted_at", table_name="login_attempts")
    op.drop_table("login_attempts")
