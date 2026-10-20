"""Sessions, terms, assessment periods, classes and enrolment
(ARCHITECTURE.md §4.2)."""

import datetime as dt
import enum
import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    Enum,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, uuid_pk


class TermNumber(enum.StrEnum):
    FIRST = "first"
    SECOND = "second"
    THIRD = "third"


class TermHalf(enum.StrEnum):
    """Two assessment sheets per term.

    "The single most important structural fact about this system" (§1.1): each
    half term produces its own sheet with its own columns.
    """

    FIRST_HALF = "first_half"
    SECOND_HALF = "second_half"


term_number_enum = Enum(
    TermNumber,
    name="term_number",
    values_callable=lambda cls: [m.value for m in cls],
)
term_half_enum = Enum(
    TermHalf,
    name="term_half",
    values_callable=lambda cls: [m.value for m in cls],
)


class AcademicSession(Base):
    __tablename__ = "academic_sessions"
    __table_args__ = (
        UniqueConstraint("school_id", "name", name="uq_academic_sessions_school_id_name"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)  # '2026/2027'
    starts_on: Mapped[dt.date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[dt.date] = mapped_column(Date, nullable=False)

    # Set in the platform, never derived from the clock and never a constant
    # (§2.3).
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    def __repr__(self) -> str:
        return f"<AcademicSession {self.name!r}>"


class Term(Base):
    __tablename__ = "terms"
    __table_args__ = (
        UniqueConstraint("academic_session_id", "number", name="uq_terms_session_number"),
        CheckConstraint("times_school_opened >= 0", name="times_school_opened_non_negative"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"), nullable=False)
    academic_session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("academic_sessions.id"), nullable=False
    )
    number: Mapped[TermNumber] = mapped_column(term_number_enum, nullable=False)
    starts_on: Mapped[dt.date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[dt.date] = mapped_column(Date, nullable=False)

    # The denominator of R9's attendance rule. Nullable because an admin sets
    # it once the term's calendar is known.
    times_school_opened: Mapped[int | None] = mapped_column(Integer)

    next_resumption_on: Mapped[dt.date | None] = mapped_column(Date)
    # "Please return this card to the School on ___ when next term begins."
    card_return_on: Mapped[dt.date | None] = mapped_column(Date)
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    def __repr__(self) -> str:
        return f"<Term {self.number.value}>"


class AssessmentPeriod(Base):
    __tablename__ = "assessment_periods"
    __table_args__ = (UniqueConstraint("term_id", "half", name="uq_assessment_periods_term_half"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"), nullable=False)
    term_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("terms.id", ondelete="CASCADE"), nullable=False
    )
    half: Mapped[TermHalf] = mapped_column(term_half_enum, nullable=False)
    opens_on: Mapped[dt.date | None] = mapped_column(Date)
    closes_on: Mapped[dt.date | None] = mapped_column(Date)

    def __repr__(self) -> str:
        return f"<AssessmentPeriod {self.half.value}>"


class Class(Base):
    __tablename__ = "classes"
    __table_args__ = (UniqueConstraint("school_id", "name", name="uq_classes_school_id_name"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)  # 'Primary 4'

    # Sort order for display. Not a rank of any kind — see R11.
    level_order: Mapped[int] = mapped_column(Integer, nullable=False)

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    def __repr__(self) -> str:
        return f"<Class {self.name!r}>"


class Enrollment(Base):
    """A pupil's place in a class for one session.

    One row per pupil per session, so a pupil who joins mid-year has an
    enrolment only for the sessions they were present for — which is what R5's
    cumulative averages count over.
    """

    __tablename__ = "enrollments"
    __table_args__ = (
        UniqueConstraint("pupil_id", "academic_session_id", name="uq_enrollments_pupil_session"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"), nullable=False)
    pupil_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pupils.id"), nullable=False)
    class_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("classes.id"), nullable=False)
    academic_session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("academic_sessions.id"), nullable=False
    )
    joined_on: Mapped[dt.date] = mapped_column(Date, nullable=False)
    left_on: Mapped[dt.date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="active", server_default="active"
    )

    def __repr__(self) -> str:
        return f"<Enrollment pupil={self.pupil_id} class={self.class_id}>"
