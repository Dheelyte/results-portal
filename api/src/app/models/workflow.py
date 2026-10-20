"""Workflow state (ARCHITECTURE.md §4.8).

Submission is per class; publication is per pupil. That asymmetry is
deliberate: a class teacher submits the whole class at once, but an admin may
hold back one pupil's report without blocking the other twenty-nine (R12).
"""

import datetime as dt
import decimal
import enum
import uuid

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, uuid_pk
from app.models.grading import Score


class ClassTermState(enum.StrEnum):
    """R14's state machine.

        not_started -> in_progress -> submitted -> approved
                            ^             |
                            +-- returned <+

    Anything else is a 409.
    """

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"
    RETURNED = "returned"
    APPROVED = "approved"


class PublicationState(enum.StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    WITHHELD = "withheld"


class_term_state_enum = Enum(
    ClassTermState,
    name="class_term_state",
    values_callable=lambda cls: [m.value for m in cls],
)
publication_state_enum = Enum(
    PublicationState,
    name="publication_state",
    values_callable=lambda cls: [m.value for m in cls],
)


class ClassTermStatus(Base):
    __tablename__ = "class_term_status"
    __table_args__ = (
        UniqueConstraint("class_id", "term_id", name="uq_class_term_status_class_term"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"), nullable=False)
    class_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("classes.id"), nullable=False)
    term_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("terms.id"), nullable=False)
    state: Mapped[ClassTermState] = mapped_column(
        class_term_state_enum,
        nullable=False,
        default=ClassTermState.NOT_STARTED,
        server_default=ClassTermState.NOT_STARTED.value,
    )

    submitted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    # Why the head teacher sent it back. "Cannot submit" with no explanation
    # generates support calls every term (R10).
    return_note: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"<ClassTermStatus class={self.class_id} {self.state.value}>"


class TermReport(Base):
    """One pupil's report for one term — the publication unit."""

    __tablename__ = "term_reports"
    __table_args__ = (UniqueConstraint("term_id", "pupil_id", name="uq_term_reports_term_pupil"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"), nullable=False)
    term_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("terms.id"), nullable=False)
    pupil_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pupils.id"), nullable=False)
    class_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("classes.id"), nullable=False)

    overall_percentage: Mapped[decimal.Decimal | None] = mapped_column(Score)

    # R11: free text a head teacher may optionally type. NEVER computed.
    # There is no ranking query anywhere in this codebase, and the card's
    # "Position (In grades)" wording suggests a band rather than a rank (N4).
    position_text: Mapped[str | None] = mapped_column(Text)

    no_in_class: Mapped[int | None] = mapped_column(Integer)
    class_teacher_comment: Mapped[str | None] = mapped_column(Text)
    head_teacher_remark: Mapped[str | None] = mapped_column(Text)
    promotion_decision: Mapped[str | None] = mapped_column(Text)  # third term only

    state: Mapped[PublicationState] = mapped_column(
        publication_state_enum,
        nullable=False,
        default=PublicationState.DRAFT,
        server_default=PublicationState.DRAFT.value,
    )
    published_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    published_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    withheld_reason: Mapped[str | None] = mapped_column(Text)

    # Replaces the parent's signature and the physical return of the card (A8).
    parent_acknowledged_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    # Versioned key (§9). A post-publication edit writes a new one; the
    # previously published PDF is retained, never overwritten (R13).
    pdf_object_key: Mapped[str | None] = mapped_column(Text)
    pdf_generated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return f"<TermReport {self.id} {self.state.value}>"
