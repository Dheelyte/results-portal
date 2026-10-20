"""Attendance and physical growth (ARCHITECTURE.md §4.7).

Four attendance fields, not two (CARD-FINDINGS §6), and height and weight at
both ends of term — a section absent from the original spec entirely.
"""

import decimal
import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Integer, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, uuid_pk


class AttendanceRecord(Base):
    """One pupil's attendance for one term.

    R9 additionally requires `times_present + times_absent` to equal
    `terms.times_school_opened`. Postgres cannot express a cross-table CHECK,
    so that is enforced by a trigger (migration 0003) **and** in the service
    layer, so no path can write a bad row.
    """

    __tablename__ = "attendance_records"
    __table_args__ = (
        UniqueConstraint("term_id", "pupil_id", name="uq_attendance_records_term_pupil"),
        CheckConstraint("times_present >= 0", name="times_present_non_negative"),
        CheckConstraint("times_absent >= 0", name="times_absent_non_negative"),
        CheckConstraint("times_late >= 0", name="times_late_non_negative"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"), nullable=False)
    term_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("terms.id"), nullable=False)
    pupil_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pupils.id"), nullable=False)

    times_present: Mapped[int] = mapped_column(Integer, nullable=False)
    times_absent: Mapped[int] = mapped_column(Integer, nullable=False)
    # "Times Collected Late" on the card. N6 asks whether it carries over to
    # the digital version; the column costs nothing and dropping it later is
    # a migration either way.
    times_late: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))

    def __repr__(self) -> str:
        return f"<AttendanceRecord term={self.term_id} pupil={self.pupil_id}>"


class GrowthRecord(Base):
    """Height and weight at the beginning and end of term."""

    __tablename__ = "growth_records"
    __table_args__ = (
        UniqueConstraint("term_id", "pupil_id", name="uq_growth_records_term_pupil"),
        CheckConstraint("height_start_m > 0", name="height_start_positive"),
        CheckConstraint("height_end_m > 0", name="height_end_positive"),
        CheckConstraint("weight_start_kg > 0", name="weight_start_positive"),
        CheckConstraint("weight_end_kg > 0", name="weight_end_positive"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"), nullable=False)
    term_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("terms.id"), nullable=False)
    pupil_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pupils.id"), nullable=False)

    height_start_m: Mapped[decimal.Decimal | None] = mapped_column(Numeric(4, 2))
    height_end_m: Mapped[decimal.Decimal | None] = mapped_column(Numeric(4, 2))
    weight_start_kg: Mapped[decimal.Decimal | None] = mapped_column(Numeric(5, 2))
    weight_end_kg: Mapped[decimal.Decimal | None] = mapped_column(Numeric(5, 2))
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))

    def __repr__(self) -> str:
        return f"<GrowthRecord term={self.term_id} pupil={self.pupil_id}>"
