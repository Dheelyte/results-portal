"""Subjects, what a class offers, and who teaches it (§4.3)."""

import uuid

from pydantic import BaseModel, Field

from app.schemas.common import Name, OrmModel


class SubjectCreate(BaseModel):
    name: Name
    parent_subject_id: uuid.UUID | None = Field(
        default=None,
        description="The group heading this sits under. English is the only one on the card.",
    )
    is_group: bool = Field(
        default=False,
        description=(
            "A heading that prints on the card and carries no scores (R7). "
            "A group can never be offered to a class."
        ),
    )
    is_specialist: bool = Field(
        default=False,
        description=(
            "Taught by a specialist rather than the class teacher. The school sets "
            "this; nothing is hardcoded (§2.3)."
        ),
    )
    display_order: int = Field(default=0, ge=0, le=1000)


class SubjectUpdate(BaseModel):
    name: Name | None = None
    parent_subject_id: uuid.UUID | None = None
    is_group: bool | None = None
    is_specialist: bool | None = None
    display_order: int | None = Field(default=None, ge=0, le=1000)
    is_active: bool | None = Field(
        default=None,
        description="Retire a subject rather than deleting it; past cards still cite it.",
    )


class SubjectRead(OrmModel):
    id: uuid.UUID
    name: str
    parent_subject_id: uuid.UUID | None
    is_group: bool
    is_specialist: bool
    display_order: int
    is_active: bool


class ClassSubjectsSave(BaseModel):
    """The complete set of subjects a class is taught this session."""

    subject_ids: list[uuid.UUID] = Field(
        description="Replaces the class's current list. Group headings are rejected (R7)."
    )
    academic_session_id: uuid.UUID | None = Field(
        default=None, description="Defaults to the school's current session."
    )


class ClassSubjectRead(OrmModel):
    id: uuid.UUID
    class_id: uuid.UUID
    subject_id: uuid.UUID
    academic_session_id: uuid.UUID
    display_order: int


class TeacherAssignmentSave(BaseModel):
    teacher_user_id: uuid.UUID


class ClassTeacherSave(BaseModel):
    teacher_user_id: uuid.UUID
    academic_session_id: uuid.UUID | None = None


class TeachingAssignmentRead(OrmModel):
    id: uuid.UUID
    class_subject_id: uuid.UUID
    teacher_user_id: uuid.UUID


class ClassTeacherRead(OrmModel):
    id: uuid.UUID
    class_id: uuid.UUID
    academic_session_id: uuid.UUID
    teacher_user_id: uuid.UUID
