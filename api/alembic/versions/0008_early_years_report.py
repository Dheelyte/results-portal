"""the early-years progress report (docs/DECISIONS.md D128)

Preparatory, Nursery and Kindergarten get a written Nursery Progress Report
rather than the scored card.

- `classes.report_type`: which report a class's pupils get. Every existing
  class is `primary`, which is what they all are today.
- `narrative_sections.report_type`: which report a section belongs to.
  Every existing section is `primary`. The early-years sections are created
  by the application the first time a class is set to early years, so a
  school that has none gets none.
- `term_reports.dominance` and `term_reports.years_in_school`: the two
  header lines of the early-years form the class teacher fills in each term.

Written by hand; autogenerate would produce the same.

Revision ID: 0008
Revises: 0007
Created: 2026-11-18
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

report_type = postgresql.ENUM("primary", "early_years", name="report_type", create_type=False)
dominance = postgresql.ENUM(
    "right", "left", "not_established", name="dominance", create_type=False
)


def upgrade() -> None:
    report_type.create(op.get_bind(), checkfirst=False)
    dominance.create(op.get_bind(), checkfirst=False)

    op.add_column(
        "classes",
        sa.Column("report_type", report_type, server_default="primary", nullable=False),
    )
    op.add_column(
        "narrative_sections",
        sa.Column("report_type", report_type, server_default="primary", nullable=False),
    )
    op.add_column("term_reports", sa.Column("dominance", dominance, nullable=True))
    op.add_column("term_reports", sa.Column("years_in_school", sa.Text(), nullable=True))


def downgrade() -> None:
    # Early-years sections and their passages would lose their meaning as
    # primary sections, so they go with the column.
    op.execute(
        "DELETE FROM narrative_entries WHERE section_id IN "
        "(SELECT id FROM narrative_sections WHERE report_type = 'early_years')"
    )
    op.execute(
        "DELETE FROM narrative_section_assignments WHERE section_id IN "
        "(SELECT id FROM narrative_sections WHERE report_type = 'early_years')"
    )
    op.execute("DELETE FROM narrative_sections WHERE report_type = 'early_years'")
    op.drop_column("term_reports", "years_in_school")
    op.drop_column("term_reports", "dominance")
    op.drop_column("narrative_sections", "report_type")
    op.drop_column("classes", "report_type")
    dominance.drop(op.get_bind(), checkfirst=False)
    report_type.drop(op.get_bind(), checkfirst=False)
