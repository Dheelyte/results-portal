"""Publication, the audit log, and what a parent is told (§7, §6 R12, R13)."""

import datetime as dt
import decimal
import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.models import ClassTermState, PublicationState
from app.schemas.common import ScoreValue


class PublishRequest(BaseModel):
    """§7: `POST /classes/{id}/publish` takes `{ withhold_pupil_ids, reason }`."""

    model_config = ConfigDict(extra="forbid")

    withhold_pupil_ids: list[uuid.UUID] = Field(default_factory=list, max_length=400)
    # Required only when something is being held back. The parent never sees
    # it; the school needs it when they are asked.
    reason: str | None = Field(default=None, max_length=1000)


class PublishOutcomeRead(BaseModel):
    class_id: uuid.UUID
    class_name: str
    term_id: uuid.UUID
    published: list[uuid.UUID] = Field(default_factory=list)
    withheld: list[uuid.UUID] = Field(default_factory=list)
    # Pupils published by an earlier run. A second publish after a correction
    # releases the rest rather than refusing the lot.
    already_published: list[uuid.UUID] = Field(default_factory=list)


class ReportStateRead(BaseModel):
    """One pupil's publication state, for the admin's list."""

    report_id: uuid.UUID
    pupil_id: uuid.UUID
    name: str
    admission_number: str
    state: PublicationState
    published_at: dt.datetime | None = None
    # Never shown to a parent (R12). This is the admin's own screen.
    withheld_reason: str | None = None
    acknowledged_at: dt.datetime | None = None


class ClassPublicationRead(BaseModel):
    class_id: uuid.UUID
    class_name: str
    term_id: uuid.UUID
    # Publication needs `approved`; the screen says so rather than failing.
    workflow_state: ClassTermState
    reports: list[ReportStateRead] = Field(default_factory=list)


class WithholdRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=1000)


class EntryEditRequest(BaseModel):
    """R13. A reason is required, and §4.9 says to reject the request without
    one — so it is required by the schema as well as by the service."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=1000)

    ca_test_1: ScoreValue | None = None
    ca_test_2: ScoreValue | None = None
    ca_test_3: ScoreValue | None = None
    ca_test_4: ScoreValue | None = None
    ca_test_5: ScoreValue | None = None
    mid_term_test: ScoreValue | None = None
    exam: ScoreValue | None = None

    def provided_scores(self) -> dict[str, decimal.Decimal | None]:
        """Only the columns actually present, as the grid's save does."""
        return self.model_dump(
            include={
                "ca_test_1",
                "ca_test_2",
                "ca_test_3",
                "ca_test_4",
                "ca_test_5",
                "mid_term_test",
                "exam",
            },
            exclude_unset=True,
        )


class EntryEditRead(BaseModel):
    """What the correction changed, including whether the grade moved."""

    entry_id: uuid.UUID
    pupil_name: str
    subject_name: str
    before: dict[str, str | None]
    after: dict[str, str | None]
    # The thing that decides whether the card has to be reprinted.
    grade_changed: bool
    # The scale the grade was re-resolved against — the row's own snapshot,
    # never today's active one (§4.5).
    regraded_against: str | None = None


class CorrectableRowRead(BaseModel):
    """One score row an admin could correct, with the id R13 needs."""

    entry_id: uuid.UUID
    class_subject_id: uuid.UUID
    subject_name: str
    half: str
    columns: list[str] = Field(default_factory=list)

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
    # True once approval froze the grade. An unfrozen row is still the
    # teacher's to fix through the grid; R13 is for the ones that are not.
    is_snapshot: bool


class PupilEntriesRead(BaseModel):
    pupil_id: uuid.UUID
    first_name: str
    last_name: str
    term_id: uuid.UUID
    rows: list[CorrectableRowRead] = Field(default_factory=list)


class AuditEntryRead(BaseModel):
    id: uuid.UUID
    action: str
    entity_type: str
    entity_id: uuid.UUID | None = None
    actor_id: uuid.UUID | None = None
    actor_name: str | None = None
    before: dict | None = None
    after: dict | None = None
    reason: str | None = None
    ip_address: str | None = None
    created_at: dt.datetime


class AuditPageRead(BaseModel):
    entries: list[AuditEntryRead] = Field(default_factory=list)
    total: int
    limit: int
    offset: int


# ---------------------------------------------------------------------------
# The parent's view (R12)
# ---------------------------------------------------------------------------


class ChildRead(BaseModel):
    pupil_id: uuid.UUID
    admission_number: str
    first_name: str
    middle_name: str | None = None
    last_name: str
    class_name: str | None = None


class AvailabilityRead(BaseModel):
    """Whether one term's report can be opened, and nothing more (R12)."""

    term_id: uuid.UUID
    term_label: str
    available: bool
    published_at: dt.datetime | None = None
    acknowledged_at: dt.datetime | None = None
    # R12's sentence, present exactly when `available` is false. No hint of
    # whether the report exists or why it is not there.
    message: str | None = None


class CardLineRead(BaseModel):
    """One row of the printed score table, as a parent sees it."""

    subject_name: str
    # The spanning heading, on the first row of its group only (§9).
    group_name: str | None = None
    group_size: int = 0
    in_group: bool = False
    values: dict[str, decimal.Decimal | None] = Field(default_factory=dict)
    cumulative: dict[str, decimal.Decimal | None] = Field(default_factory=dict)
    grade: str | None = None


class ParentCardRead(BaseModel):
    """The card as the parent sees it — the same assembly the PDF renders.

    One source for both (`services/reportcard.py`), so the page a parent
    reads and the PDF they download cannot disagree.
    """

    title: str
    subtitle: str
    school_name: str

    date: dt.date | None = None
    pupil_name: str
    admission_number: str
    overall_percentage: decimal.Decimal | None = None
    position_text: str | None = None
    class_name: str
    session_name: str
    no_in_class: int | None = None
    house_name: str | None = None

    times_school_opened: int | None = None
    times_present: int | None = None
    times_absent: int | None = None
    times_late: int | None = None

    height_start_m: decimal.Decimal | None = None
    height_end_m: decimal.Decimal | None = None
    weight_start_kg: decimal.Decimal | None = None
    weight_end_kg: decimal.Decimal | None = None

    columns: list[tuple[str, str]] = Field(default_factory=list)
    cumulative_columns: list[str] = Field(default_factory=list)
    maxima: dict[str, decimal.Decimal | None] = Field(default_factory=dict)
    lines: list[CardLineRead] = Field(default_factory=list)
    grand_total: dict[str, decimal.Decimal | None] = Field(default_factory=dict)

    # The bands in force for *this* card, not today's (§9 item 6).
    key: list[tuple[str, str, str]] = Field(default_factory=list)

    narrative_groups: list[tuple[str, str | None, list[tuple[str, str, str | None]]]] = Field(
        default_factory=list
    )

    class_teacher_comment: str | None = None
    head_teacher_remark: str | None = None
    promotion_decision: str | None = None
    return_date: dt.date | None = None


class ChildReportRead(BaseModel):
    """One term for one child: the card, or R12's sentence."""

    pupil_id: uuid.UUID
    term_id: uuid.UUID
    term_label: str
    available: bool
    published_at: dt.datetime | None = None
    acknowledged_at: dt.datetime | None = None
    message: str | None = None
    card: ParentCardRead | None = None


class ChildReportsRead(BaseModel):
    pupil_id: uuid.UUID
    first_name: str
    last_name: str
    terms: list[AvailabilityRead] = Field(default_factory=list)
