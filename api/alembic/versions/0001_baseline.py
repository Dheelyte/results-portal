"""baseline

The empty first revision.  It establishes the migration chain and the
alembic_version table against an empty database and creates nothing else.

Milestone 1 of ARCHITECTURE.md §12 adds no tables; the schema of §4 arrives in
milestone 3, which is blocked on the questions B1-B3 of §13.

Revision ID: 0001_baseline
Revises:
Created: 2026-10-20
"""

from collections.abc import Sequence

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
