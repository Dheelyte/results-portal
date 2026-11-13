"""pending approval for pupils and parent accounts (D125, D126)

Two flags, one idea: something created by someone other than an admin waits
for an admin before it counts.

- `pupils.pending_approval` and `pupils.proposed_by`: a pupil added by a
  class teacher (D125).
- `users.pending_approval`: a parent who signed themselves up (D126).

Both kinds of row are also `is_active = false` while they wait, which is what
already keeps them out of every list, sheet, card and request. The flag only
says why. `proposed_by` is SET NULL on delete: the record of who suggested a
pupil must not stop that teacher's account from ever being removed.

Written by hand; autogenerate would produce the same three columns.

Revision ID: 0006
Revises: 0005
Created: 2026-11-12
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "pupils",
        sa.Column("pending_approval", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column("pupils", sa.Column("proposed_by", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_pupils_proposed_by_users",
        "pupils",
        "users",
        ["proposed_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "users",
        sa.Column("pending_approval", sa.Boolean(), server_default="false", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("users", "pending_approval")
    op.drop_constraint("fk_pupils_proposed_by_users", "pupils", type_="foreignkey")
    op.drop_column("pupils", "proposed_by")
    op.drop_column("pupils", "pending_approval")
