"""The written assessment (ARCHITECTURE.md §4.6).

Seventeen free-text sections per pupil per term: seven curriculum areas under
"Area of Curriculum", then B through J. This is a Montessori narrative report,
not a set of 1-5 ratings (CARD-FINDINGS §4).
"""

import datetime as dt
import uuid

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utc_now_column, uuid_pk


class NarrativeSection(Base):
    """One heading on the assessment pages.

    Seeded in card order and editable thereafter (§2.3) — N7 may yet reduce
    the set, which `is_active` accommodates without a migration.
    """

    __tablename__ = "narrative_sections"
    __table_args__ = (
        UniqueConstraint("school_id", "code", name="uq_narrative_sections_school_id_code"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"), nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)  # 'A.english_language_arts', 'B'
    label: Mapped[str] = mapped_column(Text, nullable=False)  # 'English Language Arts'
    group_label: Mapped[str | None] = mapped_column(Text)  # 'Area of Curriculum'
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    def __repr__(self) -> str:
        return f"<NarrativeSection {self.code}>"


class NarrativeSectionAssignment(Base):
    """Who writes one section for one class (B1, docs/DECISIONS.md D15).

    The specialist teacher writes the curriculum area for their own subject;
    the class teacher writes everything else. Where no row exists for a
    section, the class teacher writes it — so the common case needs no
    configuration at all.

    Deliberately **not** linked to `subjects`. §1.4's seven curriculum areas
    are a different list from the eighteen scored subjects, and the mapping
    does not close: "Art & Music" has no scored counterpart. An explicit
    assignment sidesteps that and keeps authorship as data the school edits.
    """

    __tablename__ = "narrative_section_assignments"
    __table_args__ = (
        UniqueConstraint(
            "class_id",
            "section_id",
            "academic_session_id",
            name="uq_narrative_section_assignments_triple",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"), nullable=False)
    class_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("classes.id"), nullable=False)
    section_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("narrative_sections.id", ondelete="CASCADE"), nullable=False
    )
    academic_session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("academic_sessions.id"), nullable=False
    )
    teacher_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)

    def __repr__(self) -> str:
        return f"<NarrativeSectionAssignment class={self.class_id} section={self.section_id}>"


class NarrativeEntry(Base):
    """One written passage.

    Keyed on `term_id`, not on an assessment period: the card carries one set
    of written assessments for the whole term (A6).
    """

    __tablename__ = "narrative_entries"
    __table_args__ = (
        UniqueConstraint(
            "term_id", "pupil_id", "section_id", name="uq_narrative_entries_term_pupil_section"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"), nullable=False)
    term_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("terms.id"), nullable=False)
    pupil_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pupils.id"), nullable=False)
    section_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("narrative_sections.id"), nullable=False
    )
    body: Mapped[str | None] = mapped_column(Text)
    written_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[dt.datetime] = utc_now_column(nullable=False)

    def __repr__(self) -> str:
        # No body: it is a comment about a named child.
        return f"<NarrativeEntry {self.id}>"


class CommentBank(Base):
    """Reusable phrases, scoped to a section.

    Core, not optional (§4.6): a class of 30 needs 510 written passages a term
    from one teacher. Without a strong phrase bank the feature will not be used
    as intended.
    """

    __tablename__ = "comment_bank"

    id: Mapped[uuid.UUID] = uuid_pk()
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"), nullable=False)
    # A narrative_sections.code, or 'class_teacher' | 'head_teacher'.
    scope: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    def __repr__(self) -> str:
        return f"<CommentBank {self.scope}>"
