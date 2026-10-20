"""Subjects and their teaching assignments (ARCHITECTURE.md §4.3).

English is a heading over five scored sub-subjects. A group row prints on the
card but holds no scores (R7).
"""

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, uuid_pk


class Subject(Base):
    __tablename__ = "subjects"
    __table_args__ = (
        UniqueConstraint("school_id", "name", name="uq_subjects_school_id_name"),
        CheckConstraint(
            "NOT (is_group AND parent_subject_id IS NOT NULL)",
            name="group_has_no_parent",
        ),
        # A group that is also specialist is meaningless: a group holds no
        # scores and so has no teacher to be a specialist.
        CheckConstraint(
            "NOT (is_group AND is_specialist)",
            name="group_is_not_specialist",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)

    # English over Language Arts, Structure, Compr. & Poetry, Spelling &
    # Reading, Creative Writing.
    parent_subject_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("subjects.id"))
    is_group: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # Taught by a specialist rather than the class teacher. Set by an admin in
    # the platform, never a hardcoded list (§2.3). Which subjects are
    # specialist is the school's to decide and to change.
    is_specialist: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # The card leaves blank rows for additions, so order is configurable (§1.5).
    display_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    def __repr__(self) -> str:
        return f"<Subject {self.name!r}{' (group)' if self.is_group else ''}>"


class ClassSubject(Base):
    """A subject offered to a class in a session.

    A subject with `is_group = true` must never appear here (R7): enforced in
    the service layer and tested.
    """

    __tablename__ = "class_subjects"
    __table_args__ = (
        UniqueConstraint(
            "class_id", "subject_id", "academic_session_id", name="uq_class_subjects_triple"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"), nullable=False)
    class_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("classes.id"), nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("subjects.id"), nullable=False)
    academic_session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("academic_sessions.id"), nullable=False
    )
    display_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    def __repr__(self) -> str:
        return f"<ClassSubject class={self.class_id} subject={self.subject_id}>"


class TeachingAssignment(Base):
    """Who teaches one class-subject. One teacher per class-subject."""

    __tablename__ = "teaching_assignments"
    __table_args__ = (
        UniqueConstraint("class_subject_id", name="uq_teaching_assignments_class_subject_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"), nullable=False)
    class_subject_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("class_subjects.id", ondelete="CASCADE"), nullable=False
    )
    teacher_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)

    def __repr__(self) -> str:
        return f"<TeachingAssignment class_subject={self.class_subject_id}>"


class ClassTeacher(Base):
    """The class teacher for one class in one session.

    Distinct from a subject teacher: §5.2 gives this person the narrative,
    attendance, growth, comments and the submission gate for their class.
    """

    __tablename__ = "class_teachers"
    __table_args__ = (
        UniqueConstraint("class_id", "academic_session_id", name="uq_class_teachers_class_session"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"), nullable=False)
    class_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("classes.id"), nullable=False)
    academic_session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("academic_sessions.id"), nullable=False
    )
    teacher_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)

    def __repr__(self) -> str:
        return f"<ClassTeacher class={self.class_id}>"
