"""Marks obtainable and score entries (ARCHITECTURE.md §4.4)."""

import datetime as dt
import decimal
import uuid

from sqlalchemy import (
    CheckConstraint,
    Computed,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utc_now_column, uuid_pk
from app.models.grading import Score

# R2: the sum of the five CA columns, null only when all five are null.
# A database-generated column, so no code path can disagree with it.
CA_TEST_TOTAL = """
CASE WHEN ca_test_1 IS NULL AND ca_test_2 IS NULL AND ca_test_3 IS NULL
          AND ca_test_4 IS NULL AND ca_test_5 IS NULL
     THEN NULL
     ELSE COALESCE(ca_test_1, 0) + COALESCE(ca_test_2, 0) + COALESCE(ca_test_3, 0)
        + COALESCE(ca_test_4, 0) + COALESCE(ca_test_5, 0)
END
"""


class MarksObtainable(Base):
    """The card's "Marks Obtainable" row — each column's maximum.

    Configuration, not a constant (§2.3): the school sets these per sheet, and
    N2 is still unanswered, so nothing may assume 40/60. One row per
    assessment period, with an optional per-class override.
    """

    __tablename__ = "marks_obtainable"
    __table_args__ = (
        UniqueConstraint(
            "assessment_period_id", "class_id", name="uq_marks_obtainable_period_class"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"), nullable=False)
    assessment_period_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assessment_periods.id", ondelete="CASCADE"), nullable=False
    )
    # NULL means "every class".
    class_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("classes.id"))

    ca_test_1: Mapped[decimal.Decimal | None] = mapped_column(Score)
    ca_test_2: Mapped[decimal.Decimal | None] = mapped_column(Score)
    ca_test_3: Mapped[decimal.Decimal | None] = mapped_column(Score)
    ca_test_4: Mapped[decimal.Decimal | None] = mapped_column(Score)
    ca_test_5: Mapped[decimal.Decimal | None] = mapped_column(Score)
    mid_term_test: Mapped[decimal.Decimal | None] = mapped_column(Score)  # first half only
    exam: Mapped[decimal.Decimal | None] = mapped_column(Score)  # second half only

    def __repr__(self) -> str:
        return f"<MarksObtainable period={self.assessment_period_id} class={self.class_id}>"


class ResultEntry(Base):
    """One pupil's scores for one class-subject in one assessment period.

    Upper bounds are deliberately **not** CHECK constraints: each column's
    maximum comes from `marks_obtainable` and the school can change it per
    sheet. Validation lives in `services/results.py` (R1), which can name the
    applicable maximum in the error.
    """

    __tablename__ = "result_entries"
    __table_args__ = (
        UniqueConstraint(
            "assessment_period_id",
            "pupil_id",
            "class_subject_id",
            name="uq_result_entries_period_pupil_class_subject",
        ),
        CheckConstraint("ca_test_1 >= 0", name="ca_test_1_non_negative"),
        CheckConstraint("ca_test_2 >= 0", name="ca_test_2_non_negative"),
        CheckConstraint("ca_test_3 >= 0", name="ca_test_3_non_negative"),
        CheckConstraint("ca_test_4 >= 0", name="ca_test_4_non_negative"),
        CheckConstraint("ca_test_5 >= 0", name="ca_test_5_non_negative"),
        CheckConstraint("mid_term_test >= 0", name="mid_term_test_non_negative"),
        CheckConstraint("exam >= 0", name="exam_non_negative"),
        Index("ix_result_entries_period_class_subject", "assessment_period_id", "class_subject_id"),
        Index("ix_result_entries_period_pupil", "assessment_period_id", "pupil_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"), nullable=False)
    assessment_period_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assessment_periods.id"), nullable=False
    )
    pupil_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pupils.id"), nullable=False)
    class_subject_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("class_subjects.id"), nullable=False
    )

    ca_test_1: Mapped[decimal.Decimal | None] = mapped_column(Score)
    ca_test_2: Mapped[decimal.Decimal | None] = mapped_column(Score)
    ca_test_3: Mapped[decimal.Decimal | None] = mapped_column(Score)
    ca_test_4: Mapped[decimal.Decimal | None] = mapped_column(Score)
    ca_test_5: Mapped[decimal.Decimal | None] = mapped_column(Score)

    # R2, computed by Postgres. Read-only from Python.
    ca_test_total: Mapped[decimal.Decimal | None] = mapped_column(
        Score, Computed(CA_TEST_TOTAL, persisted=True)
    )

    mid_term_test: Mapped[decimal.Decimal | None] = mapped_column(Score)
    exam: Mapped[decimal.Decimal | None] = mapped_column(Score)

    # Mid Term Ave. on the first-half sheet, Total Weighted Average on the
    # second. Stored rather than derived because the formula is unconfirmed
    # (N3) and lives behind one named function in services/grading.py.
    period_average: Mapped[decimal.Decimal | None] = mapped_column(Score)

    # Snapshotted at approval and never recomputed (CLAUDE.md rule 6). The
    # scale is recorded alongside so a printed card can always be reproduced.
    grade_letter: Mapped[str | None] = mapped_column(Text)
    grading_scale_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("grading_scales.id"))

    entered_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[dt.datetime] = utc_now_column(nullable=False)

    def __repr__(self) -> str:
        # No scores: CLAUDE.md forbids them in logs, and a repr reaches logs.
        return f"<ResultEntry {self.id}>"
