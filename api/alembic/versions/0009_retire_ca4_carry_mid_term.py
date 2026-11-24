"""retire CA Test 4; carry the Mid Term Test into the second half (D129)

Data only: no column changes. `ca_test_4` stays in both tables, unread, as
`ca_test_5` did (0007), so an approved row keeps the CA Test Total it was
approved with.

**Only rows whose grade isn't frozen are touched**, and Marks Obtainable
only in terms where no grade has been frozen — the same rule as 0007.

For every unfrozen row:

1. CA Test 4 is cleared, at the school's request.
2. The second-half row's CA Tests 1–3 and Mid Term Test become the first
   half's, creating the second-half row where the first half has scores and
   it doesn't exist yet.
3. Each second-half Marks Obtainable row takes its CA and Mid Term maxima
   from the first-half row for the same class (or school-wide).

The stored `period_average` of those rows is now stale: the second half's
average counts the Mid Term Test from now on. Run, after this migration:

    docker compose exec api python -m app.recompute_averages --dry-run
    docker compose exec api python -m app.recompute_averages

**Not reversible.** The downgrade can't bring back the CA Test 4 scores it
cleared, so it does nothing. Take a backup first (`python -m app.backup`).

Revision ID: 0009
Revises: 0008
Created: 2026-11-24
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PAIRS = """
    assessment_periods AS fp
    JOIN assessment_periods AS sp
      ON sp.term_id = fp.term_id
     AND fp.half = 'first_half'
     AND sp.half = 'second_half'
"""

FROZEN_TERM = """
    EXISTS (
        SELECT 1
          FROM result_entries AS r
          JOIN assessment_periods AS rp ON rp.id = r.assessment_period_id
         WHERE rp.term_id = {term} AND r.grade_letter IS NOT NULL
    )
"""


def upgrade() -> None:
    # 1. CA Test 4 is retired.
    op.execute(
        "UPDATE result_entries SET ca_test_4 = NULL "
        "WHERE grade_letter IS NULL AND ca_test_4 IS NOT NULL"
    )

    # 2a. Carry CA 1–3 and the Mid Term Test onto second-half rows that exist.
    op.execute(
        f"""
        UPDATE result_entries AS s
           SET ca_test_1 = f.ca_test_1,
               ca_test_2 = f.ca_test_2,
               ca_test_3 = f.ca_test_3,
               ca_test_4 = NULL,
               ca_test_5 = NULL,
               mid_term_test = f.mid_term_test
          FROM result_entries AS f
          JOIN {PAIRS} ON fp.id = f.assessment_period_id
         WHERE s.assessment_period_id = sp.id
           AND s.pupil_id = f.pupil_id
           AND s.class_subject_id = f.class_subject_id
           AND s.grade_letter IS NULL
        """
    )

    # 2b. And create the second-half row where the first half has scores.
    op.execute(
        f"""
        INSERT INTO result_entries (
            id, school_id, assessment_period_id, pupil_id, class_subject_id,
            ca_test_1, ca_test_2, ca_test_3, mid_term_test, entered_by
        )
        SELECT gen_random_uuid(), f.school_id, sp.id, f.pupil_id, f.class_subject_id,
               f.ca_test_1, f.ca_test_2, f.ca_test_3, f.mid_term_test, f.entered_by
          FROM result_entries AS f
          JOIN {PAIRS} ON fp.id = f.assessment_period_id
         WHERE f.grade_letter IS NULL
           AND (f.ca_test_1 IS NOT NULL OR f.ca_test_2 IS NOT NULL
                OR f.ca_test_3 IS NOT NULL OR f.mid_term_test IS NOT NULL)
           AND NOT EXISTS (
                SELECT 1 FROM result_entries AS s
                 WHERE s.assessment_period_id = sp.id
                   AND s.pupil_id = f.pupil_id
                   AND s.class_subject_id = f.class_subject_id
           )
        """
    )

    # 3. Second-half maxima follow the first half, in unfrozen terms.
    op.execute(
        f"""
        UPDATE marks_obtainable AS s
           SET ca_test_1 = f.ca_test_1,
               ca_test_2 = f.ca_test_2,
               ca_test_3 = f.ca_test_3,
               ca_test_4 = NULL,
               ca_test_5 = NULL,
               mid_term_test = f.mid_term_test
          FROM marks_obtainable AS f
          JOIN {PAIRS} ON fp.id = f.assessment_period_id
         WHERE s.assessment_period_id = sp.id
           AND s.class_id IS NOT DISTINCT FROM f.class_id
           AND NOT {FROZEN_TERM.format(term="fp.term_id")}
        """
    )
    op.execute(
        f"""
        UPDATE marks_obtainable AS m
           SET ca_test_4 = NULL
          FROM assessment_periods AS p
         WHERE p.id = m.assessment_period_id
           AND m.ca_test_4 IS NOT NULL
           AND NOT {FROZEN_TERM.format(term="p.term_id")}
        """
    )


def downgrade() -> None:
    # See the docstring: the cleared scores can't be restored.
    pass
