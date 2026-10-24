"""The progress page and the submission gate (§7, §8.3, §6 R10)."""

import uuid

from pydantic import BaseModel, Field

from app.models import ClassTermState, TermHalf


class OutstandingItem(BaseModel):
    """One thing still to be done, in the shape §8.3 lists beneath the button.

    `kind` lets the screen group them — a missing Marks Obtainable row is the
    administrator's job, a missing score is a colleague's, a missing comment
    is the reader's own — and §6 R10 is explicit that a bare "cannot submit"
    is not good enough.
    """

    kind: str
    what: str
    detail: str | None = None
    pupil_id: uuid.UUID | None = None
    subject_id: uuid.UUID | None = None
    class_subject_id: uuid.UUID | None = None
    teacher: str | None = None


class SheetProgressRead(BaseModel):
    """One class-subject on one of the term's two sheets."""

    class_subject_id: uuid.UUID
    subject_id: uuid.UUID
    subject_name: str
    # §8.3's "owner". Null when nobody is assigned, which is itself a blocker
    # the setup checklist reports.
    teacher_name: str | None = None
    half: TermHalf
    assessment_period_id: uuid.UUID | None = None
    columns: list[str] = Field(default_factory=list)
    complete: int
    roll: int
    is_complete: bool
    missing_pupil_count: int
    # A handful of names, so a thirty-pupil gap is not a wall of text.
    missing_pupils: list[str] = Field(default_factory=list)
    not_configured: bool


class PupilProgressRead(BaseModel):
    """One pupil's four class-teacher tasks."""

    pupil_id: uuid.UUID
    name: str
    admission_number: str
    sections_written: int
    sections_total: int
    missing_sections: list[str] = Field(default_factory=list)
    has_comment: bool
    has_attendance: bool
    has_growth: bool
    is_complete: bool


class ProgressRead(BaseModel):
    """§8.3's page. Also the body of R10's 422, so the two cannot disagree."""

    class_id: uuid.UUID
    class_name: str
    term_id: uuid.UUID
    state: ClassTermState
    times_school_opened: int | None = None

    sheets: list[SheetProgressRead] = Field(default_factory=list)
    pupils: list[PupilProgressRead] = Field(default_factory=list)
    outstanding: list[OutstandingItem] = Field(default_factory=list)

    # True when R10 passes. The button is enabled on this and nothing else.
    ready: bool
    # False for anyone but the class teacher (§5.2), who is the only person
    # who may press it.
    may_submit: bool
    # Why the head teacher sent it back, if they did.
    return_note: str | None = None
