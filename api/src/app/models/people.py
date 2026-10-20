"""Pupils, houses and the guardian link (ARCHITECTURE.md §4.1)."""

import datetime as dt
import uuid

from sqlalchemy import Boolean, CheckConstraint, Date, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utc_now_column, uuid_pk


class House(Base):
    """The school runs a house system — absent from the original spec, present
    on the card (CARD-FINDINGS §7)."""

    __tablename__ = "houses"
    __table_args__ = (UniqueConstraint("school_id", "name", name="uq_houses_school_id_name"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)

    def __repr__(self) -> str:
        return f"<House {self.name!r}>"


class Pupil(Base):
    __tablename__ = "pupils"
    __table_args__ = (
        UniqueConstraint(
            "school_id", "admission_number", name="uq_pupils_school_id_admission_number"
        ),
        CheckConstraint("sex IN ('M','F')", name="sex_is_m_or_f"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"), nullable=False)

    # The pupil's permanent identifier. It reaches the PDF object key of every
    # report card they will ever receive (§9), so it must never be reused.
    # Assigned in the platform, since there is no external source (N8).
    admission_number: Mapped[str] = mapped_column(Text, nullable=False)

    first_name: Mapped[str] = mapped_column(Text, nullable=False)
    middle_name: Mapped[str | None] = mapped_column(Text)
    last_name: Mapped[str] = mapped_column(Text, nullable=False)
    sex: Mapped[str | None] = mapped_column(Text)
    date_of_birth: Mapped[dt.date | None] = mapped_column(Date)
    house_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("houses.id"))
    photo_url: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_at: Mapped[dt.datetime] = utc_now_column(nullable=False)

    @property
    def full_name(self) -> str:
        parts = [self.first_name, self.middle_name, self.last_name]
        return " ".join(part for part in parts if part)

    def __repr__(self) -> str:
        # No name: CLAUDE.md forbids a pupil's identity in logs, and a repr
        # reaches logs and tracebacks.
        return f"<Pupil {self.id}>"


class GuardianPupil(Base):
    """Which parent accounts may see which pupils.

    The join that §5.2's parent scope is built from. A parent with two children
    in different classes sees both and nothing else.
    """

    __tablename__ = "guardian_pupils"

    guardian_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    pupil_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pupils.id", ondelete="CASCADE"), primary_key=True
    )
    relationship: Mapped[str | None] = mapped_column(Text)
    is_primary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    def __repr__(self) -> str:
        return f"<GuardianPupil {self.guardian_user_id}->{self.pupil_id}>"
