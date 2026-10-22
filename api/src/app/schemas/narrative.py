"""Narrative sections, their authorship and the phrase bank (§4.6)."""

import uuid

from pydantic import BaseModel, Field

from app.schemas.common import OrmModel, ShortText


class NarrativeSectionSave(BaseModel):
    code: str = Field(min_length=1, max_length=60, examples=["A.english_language_arts"])
    label: str = Field(min_length=1, max_length=200, examples=["English Language Arts"])
    group_label: str | None = Field(default=None, max_length=200, examples=["Area of Curriculum"])
    display_order: int = Field(ge=0, le=1000)
    is_active: bool = Field(
        default=True,
        description="Retire a section rather than deleting it; past cards still cite it.",
    )


class NarrativeSectionsSave(BaseModel):
    sections: list[NarrativeSectionSave] = Field(min_length=1)


class NarrativeSectionRead(OrmModel):
    id: uuid.UUID
    code: str
    label: str
    group_label: str | None
    display_order: int
    is_active: bool


class NarrativeAssignment(BaseModel):
    section_id: uuid.UUID
    teacher_user_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "null clears the assignment, which hands the section back to the class "
            "teacher — that is the default, not nobody (D15)."
        ),
    )


class NarrativeAssignmentsSave(BaseModel):
    assignments: list[NarrativeAssignment] = Field(min_length=1)
    academic_session_id: uuid.UUID | None = None


class NarrativeAssignmentRead(OrmModel):
    id: uuid.UUID
    class_id: uuid.UUID
    section_id: uuid.UUID
    academic_session_id: uuid.UUID
    teacher_user_id: uuid.UUID


class CommentCreate(BaseModel):
    scope: str = Field(
        min_length=1,
        max_length=60,
        description=(
            "A narrative section's code, or 'class_teacher' or 'head_teacher' for the "
            "card's footer comments."
        ),
    )
    text: ShortText


class CommentRead(OrmModel):
    id: uuid.UUID
    scope: str
    text: str
    is_active: bool
