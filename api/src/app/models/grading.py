"""Versioned grading scales (ARCHITECTURE.md §4.5).

Scales are versioned because the school's answer may change: the card prints
seven bands with plus grades, while the requirements approved in September had
six and no plus grades (N1, CARD-FINDINGS §1). A2 seeds the card's scale.

The rule: a grade is snapshotted onto each result row at approval and never
recomputed (CLAUDE.md rule 6). If a boundary moves later, last term's printed
cards must still say what was printed.
"""

import datetime as dt
import decimal
import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    Numeric,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utc_now_column, uuid_pk

# Scores are numeric(5,2) throughout — never float (CLAUDE.md, Conventions).
Score = Numeric(5, 2)


class GradingScale(Base):
    __tablename__ = "grading_scales"

    id: Mapped[uuid.UUID] = uuid_pk()
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    effective_from: Mapped[dt.date] = mapped_column(Date, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_at: Mapped[dt.datetime] = utc_now_column(nullable=False)

    def __repr__(self) -> str:
        return f"<GradingScale {self.name!r}>"


class GradeBand(Base):
    """One band of a scale.

    `letter` is text, not an enum: A+ and B+ exist, and the school may add
    more (§4.5).
    """

    __tablename__ = "grade_bands"
    __table_args__ = (CheckConstraint("min_score <= max_score", name="min_not_above_max"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    scale_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("grading_scales.id", ondelete="CASCADE"), nullable=False
    )
    min_score: Mapped[decimal.Decimal] = mapped_column(Score, nullable=False)
    max_score: Mapped[decimal.Decimal] = mapped_column(Score, nullable=False)
    letter: Mapped[str] = mapped_column(Text, nullable=False)
    remark: Mapped[str] = mapped_column(Text, nullable=False)  # 'Excellence'
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    def __repr__(self) -> str:
        return f"<GradeBand {self.letter} {self.min_score}-{self.max_score}>"
