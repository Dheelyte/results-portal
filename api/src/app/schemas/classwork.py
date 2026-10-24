"""Request and response models for the class teacher's own work (§7's teacher
block, §8.2, §8.3).

Named for `routers/classwork.py`, its only consumer: the narrative,
attendance, growth and the comment are four columns of one roll, written by
one person, on one screen.
"""

import datetime as dt
import decimal
import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.models import ClassTermState
from app.services.narrative import MAX_PASSAGE_LENGTH
from app.services.reports import MAX_COMMENT_LENGTH


class PassageSave(BaseModel):
    """One section's text, as the narrative screen submits it."""

    model_config = ConfigDict(extra="forbid")

    section_id: uuid.UUID
    # Null clears the passage; an omitted section is not touched at all.
    body: str | None = Field(default=None, max_length=MAX_PASSAGE_LENGTH)


class NarrativeSave(BaseModel):
    """A set of passages for one pupil. Applied all or none."""

    model_config = ConfigDict(extra="forbid")

    # Generous: the screen sends only what changed, but "copy from the
    # previous pupil" can legitimately touch every section at once.
    passages: list[PassageSave] = Field(min_length=1, max_length=64)


class PassageRead(BaseModel):
    """One section of one pupil's narrative."""

    section_id: uuid.UUID
    code: str
    label: str
    group_label: str | None = None
    display_order: int

    body: str | None = None
    # False when this section belongs to another teacher for this class (D15).
    writable: bool
    is_complete: bool
    updated_at: dt.datetime | None = None


class PupilNarrativeRead(BaseModel):
    """One pupil's page, with §8.2's previous/next navigation."""

    pupil_id: uuid.UUID
    admission_number: str
    first_name: str
    middle_name: str | None = None
    last_name: str

    class_id: uuid.UUID
    class_name: str
    term_id: uuid.UUID

    passages: list[PassageRead] = Field(default_factory=list)
    complete_count: int
    section_count: int

    state: ClassTermState
    editable: bool

    previous_pupil_id: uuid.UUID | None = None
    next_pupil_id: uuid.UUID | None = None
    # 1-based, for "pupil 7 of 30".
    position: int
    roll_size: int


class NarrativeProgressRead(BaseModel):
    """One line of the class list."""

    pupil_id: uuid.UUID
    admission_number: str
    first_name: str
    middle_name: str | None = None
    last_name: str
    written: int
    total: int
    is_complete: bool


class SectionHeadingRead(BaseModel):
    """A section as the class list shows it, without any pupil's text."""

    section_id: uuid.UUID
    code: str
    label: str
    group_label: str | None = None
    display_order: int
    writable: bool


class ClassNarrativeRead(BaseModel):
    """§8.2's progress indicator: "12 of 30 pupils complete"."""

    class_id: uuid.UUID
    class_name: str
    term_id: uuid.UUID

    sections: list[SectionHeadingRead] = Field(default_factory=list)
    pupils: list[NarrativeProgressRead] = Field(default_factory=list)
    complete_pupils: int
    roll_size: int

    state: ClassTermState
    editable: bool


# ---------------------------------------------------------------------------
# Attendance and growth (§4.7, R9)
# ---------------------------------------------------------------------------


class AttendanceSaveRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pupil_id: uuid.UUID
    times_present: int = Field(ge=0, le=400)
    times_absent: int = Field(ge=0, le=400)
    times_late: int = Field(default=0, ge=0, le=400)


class AttendanceSave(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: list[AttendanceSaveRow] = Field(min_length=1, max_length=400)


class AttendanceRead(BaseModel):
    pupil_id: uuid.UUID
    admission_number: str
    first_name: str
    middle_name: str | None = None
    last_name: str

    times_present: int | None = None
    times_absent: int | None = None
    times_late: int | None = None


class ClassAttendanceRead(BaseModel):
    class_id: uuid.UUID
    class_name: str
    term_id: uuid.UUID
    # R9's right-hand side. Null means the admin has not set it, and nothing
    # can be entered until they do.
    times_school_opened: int | None = None

    rows: list[AttendanceRead] = Field(default_factory=list)
    state: ClassTermState
    editable: bool


class GrowthSaveRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pupil_id: uuid.UUID
    height_start_m: decimal.Decimal | None = Field(
        default=None, gt=0, max_digits=4, decimal_places=2
    )
    height_end_m: decimal.Decimal | None = Field(default=None, gt=0, max_digits=4, decimal_places=2)
    weight_start_kg: decimal.Decimal | None = Field(
        default=None, gt=0, max_digits=5, decimal_places=2
    )
    weight_end_kg: decimal.Decimal | None = Field(
        default=None, gt=0, max_digits=5, decimal_places=2
    )


class GrowthSave(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: list[GrowthSaveRow] = Field(min_length=1, max_length=400)


class GrowthRead(BaseModel):
    pupil_id: uuid.UUID
    admission_number: str
    first_name: str
    middle_name: str | None = None
    last_name: str

    height_start_m: decimal.Decimal | None = None
    height_end_m: decimal.Decimal | None = None
    weight_start_kg: decimal.Decimal | None = None
    weight_end_kg: decimal.Decimal | None = None


class ClassGrowthRead(BaseModel):
    class_id: uuid.UUID
    class_name: str
    term_id: uuid.UUID
    rows: list[GrowthRead] = Field(default_factory=list)
    state: ClassTermState
    editable: bool


# ---------------------------------------------------------------------------
# The class teacher's comment (§1.6)
# ---------------------------------------------------------------------------


class CommentSaveRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pupil_id: uuid.UUID
    comment: str | None = Field(default=None, max_length=MAX_COMMENT_LENGTH)


class ClassCommentsSave(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: list[CommentSaveRow] = Field(min_length=1, max_length=400)


class PupilCommentRead(BaseModel):
    pupil_id: uuid.UUID
    admission_number: str
    first_name: str
    middle_name: str | None = None
    last_name: str
    comment: str | None = None


class ClassCommentsRead(BaseModel):
    class_id: uuid.UUID
    class_name: str
    term_id: uuid.UUID
    rows: list[PupilCommentRead] = Field(default_factory=list)
    state: ClassTermState
    editable: bool


class PhraseRead(BaseModel):
    """One entry from the phrase bank (§4.6, §8.2)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    scope: str
    # Plain `str`, not `ShortText`: this is a read model, and a length bound
    # on a response would turn an odd stored row into a 500.
    text: str
