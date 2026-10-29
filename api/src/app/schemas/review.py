"""Head teacher review (§7's review block, §8.4)."""

import datetime as dt
import decimal
import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.models import ClassTermState
from app.services.review import (
    MAX_POSITION_LENGTH,
    MAX_PROMOTION_LENGTH,
    MAX_REMARK_LENGTH,
)


class QueueEntryRead(BaseModel):
    """One class in the review queue (§8.4)."""

    class_id: uuid.UUID
    class_name: str
    term_id: uuid.UUID
    # "First Term, 2026/2027". §5.2 gives `/terms` to the admin alone, so this
    # travels with the queue (docs/DECISIONS.md D51's reasoning).
    term_label: str
    state: ClassTermState
    roll: int
    submitted_at: dt.datetime | None = None
    submitted_by: str | None = None
    # How many of the roll already have a remark, so the head teacher can see
    # where they left off in a class of thirty.
    remarks_written: int


class CardHalf(BaseModel):
    """One pupil's figures for one subject on one sheet."""

    ca_test_1: decimal.Decimal | None = None
    ca_test_2: decimal.Decimal | None = None
    ca_test_3: decimal.Decimal | None = None
    ca_test_4: decimal.Decimal | None = None
    ca_test_5: decimal.Decimal | None = None
    ca_test_total: decimal.Decimal | None = None
    mid_term_test: decimal.Decimal | None = None
    exam: decimal.Decimal | None = None
    period_average: decimal.Decimal | None = None
    grade_letter: str | None = None
    grade_remark: str | None = None
    # True once the grade is frozen (§4.5). Before approval the letter is
    # resolved live from the active scale; after it, this is what the card
    # says and nothing recomputes it.
    is_snapshot: bool = False


class SubjectRowRead(BaseModel):
    """One line of the card's score table, both sheets side by side."""

    class_subject_id: uuid.UUID
    subject_id: uuid.UUID
    subject_name: str
    # R7: a heading renders as a spanning row and carries no figures.
    is_group: bool
    display_order: int
    parent_subject_id: uuid.UUID | None = None
    # The spanning heading this row belongs under (§9). R7 keeps a heading out
    # of `class_subjects` entirely, so it arrives on its children rather than
    # as a row of its own.
    parent_subject_name: str | None = None
    halves: dict[str, CardHalf] = Field(default_factory=dict)


class CardPassage(BaseModel):
    section_id: uuid.UUID
    code: str
    label: str
    group_label: str | None = None
    body: str | None = None


class CardAttendance(BaseModel):
    """The card's attendance block. Named apart from `classwork.AttendanceRead`
    on purpose: that one is a row a teacher edits and carries the pupil's
    name; this is what the card prints."""

    times_school_opened: int | None = None
    times_present: int | None = None
    times_absent: int | None = None
    times_late: int | None = None


class CardGrowth(BaseModel):
    height_start_m: decimal.Decimal | None = None
    height_end_m: decimal.Decimal | None = None
    weight_start_kg: decimal.Decimal | None = None
    weight_end_kg: decimal.Decimal | None = None


class CardRead(BaseModel):
    """One pupil's card as the parent will see it, plus the review fields."""

    pupil_id: uuid.UUID
    admission_number: str
    first_name: str
    middle_name: str | None = None
    last_name: str
    house_name: str | None = None
    no_in_class: int | None = None

    subjects: list[SubjectRowRead] = Field(default_factory=list)
    narrative: list[CardPassage] = Field(default_factory=list)
    attendance: CardAttendance | None = None
    growth: CardGrowth | None = None

    class_teacher_comment: str | None = None
    # R6's aggregate, frozen at approval (§14 A25).
    overall_percentage: decimal.Decimal | None = None

    # The three the head teacher writes.
    head_teacher_remark: str | None = None
    # R11: free text. Never computed, never a rank.
    position_text: str | None = None
    promotion_decision: str | None = None


class ClassReviewRead(BaseModel):
    class_id: uuid.UUID
    class_name: str
    term_id: uuid.UUID
    term_number: str
    term_label: str
    state: ClassTermState
    return_note: str | None = None
    # §8.4 puts the promotion decision in third term only.
    promotion_applies: bool
    cards: list[CardRead] = Field(default_factory=list)


class RemarkSaveRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pupil_id: uuid.UUID
    head_teacher_remark: str | None = Field(default=None, max_length=MAX_REMARK_LENGTH)
    position_text: str | None = Field(default=None, max_length=MAX_POSITION_LENGTH)
    promotion_decision: str | None = Field(default=None, max_length=MAX_PROMOTION_LENGTH)


class RemarksSave(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: list[RemarkSaveRow] = Field(min_length=1, max_length=400)


class ReturnRequest(BaseModel):
    """§7: `POST /classes/{id}/return` takes `{ note }`, and it is required."""

    model_config = ConfigDict(extra="forbid")

    note: str = Field(min_length=1, max_length=2000)


class SnapshotRead(BaseModel):
    """What approval froze, reported back so it is visible rather than implied."""

    grading_scale_id: uuid.UUID
    grading_scale_name: str
    rows: int
    graded: int
    ungraded: int
    reports: int


class ApprovalRead(BaseModel):
    review: ClassReviewRead
    snapshot: SnapshotRead
