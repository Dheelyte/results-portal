"""retire CA Test 5; carry first-half CA tests into the second half (D127)

Data only: no column changes. `ca_test_5` stays in both tables, unread, so
that an approved row keeps the CA Test Total it was approved with (the
total is a generated column over all five).

**Only rows whose grade isn't frozen are touched.** A row with a
`grade_letter` was snapshotted at approval (§4.5, CLAUDE.md rule 6), and a
published card must keep saying what it said. That is the same test
`app.recompute_averages` uses. Marks Obtainable rows are changed only for
terms in which no grade has been frozen yet.

For every unfrozen row:

1. CA Test 5 is cleared. The school confirmed scores had been entered in
   it, and that they go.
2. The second-half row's CA Tests 1–4 become the first half's, creating the
   second-half row where the first half has scores and it doesn't exist yet.
3. Each second-half Marks Obtainable row takes its CA maxima from the
   first-half row for the same class (or school-wide).

The stored `period_average` of those rows is now stale. Run, after this
migration:

    docker compose exec api python -m app.recompute_averages --dry-run
    docker compose exec api python -m app.recompute_averages

**Not reversible.** The downgrade can't bring back the CA Test 5 scores it
cleared or the second-half CA values it overwrote, so it does nothing.
Take a backup first (`python -m app.backup`).

Revision ID: 0007
Revises: 0006
Created: 2026-11-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# First-half and second-half periods of the same term, side by side.
PAIRS = """
    assessment_periods AS fp
    JOIN assessment_periods AS sp
      ON sp.term_id = fp.term_id
     AND fp.half = 'first_half'
     AND sp.half = 'second_half'
"""

# A term in which some grade has been frozen. Its Marks Obtainable stay.
FROZEN_TERM = """
    EXISTS (
        SELECT 1
          FROM result_entries AS r
          JOIN assessment_periods AS rp ON rp.id = r.assessment_period_id
         WHERE rp.term_id = {term} AND r.grade_letter IS NOT NULL
    )
"""


def upgrade() -> None:
    # 1. CA Test 5 is retired.
    op.execute(
        "UPDATE result_entries SET ca_test_5 = NULL "
        "WHERE grade_letter IS NULL AND ca_test_5 IS NOT NULL"
    )

    # 2a. Carry CA 1–4 onto second-half rows that exist.
    op.execute(
        f"""
        UPDATE result_entries AS s
           SET ca_test_1 = f.ca_test_1,
               ca_test_2 = f.ca_test_2,
               ca_test_3 = f.ca_test_3,
               ca_test_4 = f.ca_test_4,
               ca_test_5 = NULL
          FROM result_entries AS f
          JOIN {PAIRS} ON fp.id = f.assessment_period_id
         WHERE s.assessment_period_id = sp.id
           AND s.pupil_id = f.pupil_id
           AND s.class_subject_id = f.class_subject_id
           AND s.grade_letter IS NULL
        """
    )

    # 2b. And create the second-half row where the first half has CA scores.
    op.execute(
        f"""
        INSERT INTO result_entries (
            id, school_id, assessment_period_id, pupil_id, class_subject_id,
            ca_test_1, ca_test_2, ca_test_3, ca_test_4, entered_by
        )
        SELECT gen_random_uuid(), f.school_id, sp.id, f.pupil_id, f.class_subject_id,
               f.ca_test_1, f.ca_test_2, f.ca_test_3, f.ca_test_4, f.entered_by
          FROM result_entries AS f
          JOIN {PAIRS} ON fp.id = f.assessment_period_id
         WHERE f.grade_letter IS NULL
           AND (f.ca_test_1 IS NOT NULL OR f.ca_test_2 IS NOT NULL
                OR f.ca_test_3 IS NOT NULL OR f.ca_test_4 IS NOT NULL)
           AND NOT EXISTS (
                SELECT 1 FROM result_entries AS s
                 WHERE s.assessment_period_id = sp.id
                   AND s.pupil_id = f.pupil_id
                   AND s.class_subject_id = f.class_subject_id
           )
        """
    )

    # 3. Second-half CA maxima follow the first half, in unfrozen terms.
    op.execute(
        f"""
        UPDATE marks_obtainable AS s
           SET ca_test_1 = f.ca_test_1,
               ca_test_2 = f.ca_test_2,
               ca_test_3 = f.ca_test_3,
               ca_test_4 = f.ca_test_4,
               ca_test_5 = NULL
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
           SET ca_test_5 = NULL
          FROM assessment_periods AS p
         WHERE p.id = m.assessment_period_id
           AND m.ca_test_5 IS NOT NULL
           AND NOT {FROZEN_TERM.format(term="p.term_id")}
        """
    )


def downgrade() -> None:
    # See the docstring: the cleared and overwritten scores can't be restored.
    pass
