"""Head teacher review, approval and return (ARCHITECTURE.md §8.4, §4.5,
§6 R4, R11, R14).

Three jobs, and the third one is the dangerous one.

**The queue and the card.** §8.4: "Queue of submitted classes. Opening one
shows each pupil's card as the parent will see it, with fields for the remark,
the optional position text, and, in third term, the promotion decision."

**The remark, position and promotion.** Free text, all three. R11 is emphatic:
position is **never computed**, there is no ranking query anywhere in this
codebase, and `position_text` is whatever the head teacher types — the card's
"Position (In grades)" wording suggests a band rather than a rank (N4).

**The snapshot.** §4.5: "when a class is approved by the head teacher, write
the resolved `grade_letter` and `grading_scale_id` onto every result row", and
then the reason:

    If the school later changes a boundary, last term's printed cards must
    still say what was printed. Recomputing would silently rewrite history,
    and a parent holding a printed card would find it disagrees with the
    portal.

So approval is the one moment a grade is decided, and after it nothing in this
module or any other recomputes one. CLAUDE.md rule 6. The only route to a
changed grade afterwards is the admin's post-publication edit (R13), which is
audited, needs a reason, and resolves against the **snapshotted** scale rather
than today's.
"""

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import scope
from app.models import (
    AcademicSession,
    AssessmentPeriod,
    AttendanceRecord,
    AuditAction,
    Class,
    ClassSubject,
    ClassTermState,
    ClassTermStatus,
    GradeBand,
    GrowthRecord,
    NarrativeEntry,
    NarrativeSection,
    Pupil,
    ResultEntry,
    Subject,
    Term,
    TermHalf,
    TermNumber,
    TermReport,
    User,
)
from app.services import audit, grading, results, workflow
from app.services.errors import Conflict, RowErrors
from app.services.support import all_of, has_text, one_or_404, rows_of

logger = logging.getLogger(__name__)

# What the head teacher may write, per pupil. All free text: R11 forbids
# computing a position, and the promotion decision is a sentence, not an enum
# the school has agreed.
REMARK_FIELDS = ("head_teacher_remark", "position_text", "promotion_decision")

MAX_REMARK_LENGTH = 1000
MAX_POSITION_LENGTH = 100
MAX_PROMOTION_LENGTH = 200


@dataclass(frozen=True)
class QueueEntry:
    """One class awaiting review."""

    class_id: uuid.UUID
    class_name: str
    term_id: uuid.UUID
    # Carried so the screen can name the term it is showing. §5.2 gives
    # `/terms` to the admin alone, so the head teacher has no other way to
    # look it up — the same gap D51 closed for teachers.
    term_label: str
    state: ClassTermState
    roll: int
    submitted_at: object | None
    submitted_by: str | None
    remarks_written: int


@dataclass(frozen=True)
class SubjectRow:
    """One line of a pupil's score table, as the card prints it."""

    class_subject_id: uuid.UUID
    subject_id: uuid.UUID
    subject_name: str
    is_group: bool
    display_order: int
    parent_subject_id: uuid.UUID | None
    # The heading this row sits under, by name. §9 prints "English as a
    # spanning group heading over its five sub-rows", and R7 means the heading
    # is **not** a class-subject — it carries no scores, so it is never
    # offered to a class. Without the name travelling on the child rows there
    # would be nothing for the card to put in that spanning row.
    parent_subject_name: str | None
    # Keyed by half value: the entry's columns, total, average and grade.
    halves: dict[str, dict[str, object]] = field(default_factory=dict)


@dataclass(frozen=True)
class PupilCard:
    """One pupil's card as the parent will see it, plus the review fields."""

    pupil: Pupil
    house_name: str | None
    report: TermReport | None
    subjects: list[SubjectRow]
    narrative: list[tuple[NarrativeSection, str | None]]
    attendance: AttendanceRecord | None
    growth: GrowthRecord | None
    overall_percentage: object | None


@dataclass(frozen=True)
class ClassReview:
    klass: Class
    term: Term
    term_label: str
    state: ClassTermState
    cards: list[PupilCard]
    return_note: str | None
    # Third term only (§8.4). Not a code branch on the number anywhere else.
    promotion_applies: bool


@dataclass(frozen=True)
class RemarkInput:
    pupil_id: uuid.UUID
    head_teacher_remark: str | None = None
    position_text: str | None = None
    promotion_decision: str | None = None


# ---------------------------------------------------------------------------
# The queue (§8.4)
# ---------------------------------------------------------------------------


TERM_NAMES = {
    TermNumber.FIRST: "First Term",
    TermNumber.SECOND: "Second Term",
    TermNumber.THIRD: "Third Term",
}


async def _term_or_current(db: AsyncSession, actor: User, term_id: uuid.UUID | None) -> Term:
    if term_id is not None:
        return await one_or_404(db, scope.scoped_terms(actor).where(Term.id == term_id), "term")

    current = await db.scalar(scope.scoped_terms(actor).where(Term.is_current.is_(True)))
    if current is None:
        raise Conflict(
            "No term has been marked as the current one yet. An administrator sets that up."
        )
    return current


async def _term_label(db: AsyncSession, actor: User, term: Term) -> str:
    """ "First Term, 2026/2027" — what the screen puts at the top."""
    name = await db.scalar(
        scope.scoped_academic_sessions(actor)
        .where(AcademicSession.id == term.academic_session_id)
        .with_only_columns(AcademicSession.name)
    )
    return f"{TERM_NAMES.get(term.number, term.number.value)}, {name}"


async def queue(
    db: AsyncSession, actor: User, *, term_id: uuid.UUID | None = None
) -> list[QueueEntry]:
    """Classes submitted for review this term, oldest submission first.

    Oldest first because the queue is worked through, not browsed: the class
    that has been waiting longest is the one holding up the release.

    `term_id` defaults to the current term for the same reason it does on
    `/my/assignments`: §2.3 sets that in the platform, §5.2 gives `/terms` to
    the admin, and the head teacher would otherwise have no id to pass (D51).
    """
    term = await _term_or_current(db, actor, term_id)

    rows = await rows_of(
        db,
        select(ClassTermStatus, Class, User.full_name)
        .join(Class, Class.id == ClassTermStatus.class_id)
        .outerjoin(User, User.id == ClassTermStatus.submitted_by)
        .where(
            ClassTermStatus.id.in_(
                scope.scoped_class_term_status(actor).with_only_columns(ClassTermStatus.id)
            ),
            ClassTermStatus.term_id == term.id,
            ClassTermStatus.state.in_(
                [ClassTermState.SUBMITTED, ClassTermState.RETURNED, ClassTermState.APPROVED]
            ),
        )
        .order_by(ClassTermStatus.submitted_at, Class.level_order),
    )

    label = await _term_label(db, actor, term)

    entries: list[QueueEntry] = []
    for status, klass, submitted_by in rows:
        pupils = await results.pupils_of(
            db, actor, class_id=klass.id, academic_session_id=term.academic_session_id
        )
        written = await db.scalar(
            select(func.count()).where(
                TermReport.id.in_(
                    scope.scoped_term_reports(actor).with_only_columns(TermReport.id)
                ),
                TermReport.term_id == term.id,
                TermReport.class_id == klass.id,
                has_text(TermReport.head_teacher_remark),
            )
        )
        entries.append(
            QueueEntry(
                class_id=klass.id,
                class_name=klass.name,
                term_id=term.id,
                term_label=label,
                state=status.state,
                roll=len(pupils),
                submitted_at=status.submitted_at,
                submitted_by=submitted_by,
                remarks_written=written or 0,
            )
        )
    return entries


# ---------------------------------------------------------------------------
# The card (§8.4)
# ---------------------------------------------------------------------------


async def class_review(
    db: AsyncSession, actor: User, *, class_id: uuid.UUID, term_id: uuid.UUID | None = None
) -> ClassReview:
    """Every pupil's card, as the parent will see it.

    Built in a fixed number of queries whatever the class size: the head
    teacher scrolls through thirty cards in one sitting, and a query per pupil
    per subject would make that unusable.
    """
    klass = await one_or_404(db, scope.scoped_classes(actor).where(Class.id == class_id), "class")
    term = await _term_or_current(db, actor, term_id)

    pupils = list(
        await results.pupils_of(
            db, actor, class_id=class_id, academic_session_id=term.academic_session_id
        )
    )
    pupil_ids = [pupil.id for pupil in pupils]

    periods = {
        period.half: period
        for period in await all_of(
            db,
            scope.scoped_assessment_periods(actor).where(AssessmentPeriod.term_id == term.id),
        )
    }

    offerings = list(
        await rows_of(
            db,
            select(ClassSubject, Subject)
            .join(Subject, Subject.id == ClassSubject.subject_id)
            .where(
                ClassSubject.id.in_(
                    scope.subjects_offered_to(
                        actor, class_id, term.academic_session_id
                    ).with_only_columns(ClassSubject.id)
                )
            )
            .order_by(Subject.display_order, Subject.name),
        )
    )

    # The headings those subjects hang under, by id. One query for the whole
    # tree rather than a join that would repeat the parent on every row.
    headings = {
        subject_id: name
        for subject_id, name in await rows_of(
            db,
            scope.scoped_subjects(actor)
            .where(Subject.is_group.is_(True))
            .with_only_columns(Subject.id, Subject.name),
        )
    }

    # Read fresh, because approval writes a grade onto every one of these and
    # the session may already hold a copy from before that (`populate_existing`).
    score_rows: Sequence[ResultEntry] = []
    if pupil_ids and periods:
        score_rows = await all_of(
            db,
            select(ResultEntry)
            .where(
                ResultEntry.school_id == actor.school_id,
                ResultEntry.assessment_period_id.in_([period.id for period in periods.values()]),
                ResultEntry.pupil_id.in_(pupil_ids),
            )
            .execution_options(populate_existing=True),
        )
    entries = {
        (entry.assessment_period_id, entry.class_subject_id, entry.pupil_id): entry
        for entry in score_rows
    }

    # R4: before approval the grade is resolved from the active scale; after
    # it, from the snapshot on the row. Both appear below, and the row's own
    # `grade_letter` always wins.
    scale = await grading.active_scale(db, actor)
    live_bands = await grading.bands_of(db, actor, scale.id) if scale is not None else []

    sections = list(await narrative_sections(db, actor))
    narrative_rows: Sequence[NarrativeEntry] = []
    if pupil_ids:
        narrative_rows = await all_of(
            db,
            select(NarrativeEntry).where(
                NarrativeEntry.school_id == actor.school_id,
                NarrativeEntry.term_id == term.id,
                NarrativeEntry.pupil_id.in_(pupil_ids),
            ),
        )
    passages = {(entry.pupil_id, entry.section_id): entry.body for entry in narrative_rows}

    attendance = {
        record.pupil_id: record
        for record in await all_of(
            db,
            scope.scoped_attendance(actor, term.academic_session_id).where(
                AttendanceRecord.term_id == term.id
            ),
        )
    }
    growth = {
        record.pupil_id: record
        for record in await all_of(
            db,
            scope.scoped_growth(actor, term.academic_session_id).where(
                GrowthRecord.term_id == term.id
            ),
        )
    }
    reports = {
        report.pupil_id: report
        for report in await all_of(
            db,
            scope.scoped_term_reports(actor, term.academic_session_id)
            .where(TermReport.term_id == term.id)
            .execution_options(populate_existing=True),
        )
    }
    houses = {house.id: house.name for house in await all_of(db, scope.scoped_houses(actor))}

    status = await db.scalar(
        scope.scoped_class_term_status(actor).where(
            ClassTermStatus.class_id == class_id, ClassTermStatus.term_id == term.id
        )
    )

    cards = [
        PupilCard(
            pupil=pupil,
            house_name=houses.get(pupil.house_id) if pupil.house_id else None,
            report=reports.get(pupil.id),
            subjects=[
                _subject_row(
                    offering,
                    subject,
                    pupil_id=pupil.id,
                    periods=periods,
                    entries=entries,
                    live_bands=live_bands,
                    headings=headings,
                )
                for offering, subject in offerings
            ],
            narrative=[(section, passages.get((pupil.id, section.id))) for section in sections],
            attendance=attendance.get(pupil.id),
            growth=growth.get(pupil.id),
            overall_percentage=(
                reports[pupil.id].overall_percentage if pupil.id in reports else None
            ),
        )
        for pupil in pupils
    ]

    return ClassReview(
        klass=klass,
        term=term,
        term_label=await _term_label(db, actor, term),
        state=status.state if status is not None else ClassTermState.NOT_STARTED,
        cards=cards,
        return_note=status.return_note if status is not None else None,
        promotion_applies=term.number is TermNumber.THIRD,
    )


async def narrative_sections(db: AsyncSession, actor: User) -> Sequence[NarrativeSection]:
    """The active sections in card order.

    A thin wrapper so this module does not import `services/narrative.py` for
    one call — review reads the narrative, it does not write it.
    """
    return await all_of(
        db,
        scope.scoped_narrative_sections(actor)
        .where(NarrativeSection.is_active.is_(True))
        .order_by(NarrativeSection.display_order),
    )


def _subject_row(
    offering: ClassSubject,
    subject: Subject,
    *,
    pupil_id: uuid.UUID,
    periods: dict,
    entries: dict,
    live_bands: Sequence[GradeBand],
    headings: dict[uuid.UUID, str],
) -> SubjectRow:
    halves: dict[str, dict[str, object]] = {}
    for half, period in periods.items():
        entry = entries.get((period.id, offering.id, pupil_id))
        if entry is None:
            halves[half.value] = {}
            continue

        # R4. A snapshotted letter is what the card says, whatever today's
        # scale would make of the same average (rule 6).
        if entry.grade_letter is not None:
            letter, remark = entry.grade_letter, None
        else:
            band = grading.band_for(entry.period_average, live_bands)
            letter, remark = (band.letter, band.remark) if band is not None else (None, None)

        halves[half.value] = {
            "ca_test_1": entry.ca_test_1,
            "ca_test_2": entry.ca_test_2,
            "ca_test_3": entry.ca_test_3,
            "ca_test_4": entry.ca_test_4,
            "ca_test_5": entry.ca_test_5,
            "ca_test_total": entry.ca_test_total,
            "mid_term_test": entry.mid_term_test,
            "exam": entry.exam,
            "period_average": entry.period_average,
            "grade_letter": letter,
            "grade_remark": remark,
            "is_snapshot": entry.grade_letter is not None,
        }

    return SubjectRow(
        class_subject_id=offering.id,
        subject_id=subject.id,
        subject_name=subject.name,
        is_group=subject.is_group,
        display_order=subject.display_order,
        parent_subject_id=subject.parent_subject_id,
        parent_subject_name=headings.get(subject.parent_subject_id)
        if subject.parent_subject_id
        else None,
        halves=halves,
    )


# ---------------------------------------------------------------------------
# The remark, the position and the promotion (§8.4, R11)
# ---------------------------------------------------------------------------


async def save_remarks(
    db: AsyncSession,
    actor: User,
    *,
    class_id: uuid.UUID,
    term_id: uuid.UUID,
    rows: Sequence[RemarkInput],
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> ClassReview:
    """Write the head teacher's three free-text fields, all or none.

    Writable while the class is **submitted or approved** — the opposite of
    everything else in this system. A head teacher reads thirty cards and
    types as they go, and the remark is theirs rather than the class
    teacher's, so R14's "read-only for teachers on submitted" does not apply
    to it. Before submission there is nothing to remark on
    (docs/DECISIONS.md D67).
    """
    review = await class_review(db, actor, class_id=class_id, term_id=term_id)

    if review.state not in (ClassTermState.SUBMITTED, ClassTermState.APPROVED):
        raise Conflict(
            "This class has not been submitted for review yet, so there is nothing to remark on."
        )

    known = {card.pupil.id for card in review.cards}
    errors: dict[str, dict[str, str]] = {}
    for row in rows:
        found: dict[str, str] = {}
        if row.pupil_id not in known:
            errors[str(row.pupil_id)] = {
                "pupil_id": "This pupil is not in this class for this session."
            }
            continue
        for field_name, limit in (
            ("head_teacher_remark", MAX_REMARK_LENGTH),
            ("position_text", MAX_POSITION_LENGTH),
            ("promotion_decision", MAX_PROMOTION_LENGTH),
        ):
            value = getattr(row, field_name)
            if value is not None and len(value) > limit:
                found[field_name] = (
                    f"This is longer than {limit} characters, which will not fit on the card."
                )
        if row.promotion_decision and not review.promotion_applies:
            # §8.4 puts the promotion decision in third term only. Refused
            # rather than ignored: silently dropping it would have the head
            # teacher believe they had recorded something.
            found["promotion_decision"] = "The promotion decision is recorded in third term only."
        if found:
            errors[str(row.pupil_id)] = found

    if errors:
        raise RowErrors(
            f"{len(errors)} of {len(rows)} pupils were rejected, so nothing was saved.",
            errors,
        )

    reports = {card.pupil.id: card.report for card in review.cards}
    for row in rows:
        report = reports.get(row.pupil_id)
        if report is None:
            # Submission creates a row for every pupil (A24), so this is the
            # path for a pupil enrolled after submission — rare, and better
            # than refusing to record a remark about a child who is in the
            # class.
            report = TermReport(
                school_id=actor.school_id,
                term_id=term_id,
                pupil_id=row.pupil_id,
                class_id=class_id,
            )
            db.add(report)
        for field_name in REMARK_FIELDS:
            value = getattr(row, field_name)
            setattr(report, field_name, None if value is None else value.rstrip())

    await db.flush()
    await audit.record(
        db,
        school_id=actor.school_id,
        action=AuditAction.HEAD_TEACHER_REMARKS_SAVED,
        entity_type="class",
        entity_id=class_id,
        actor_id=actor.id,
        # Counts and field names only. A remark is written about a named
        # child, and R11's position is the school's judgement of one.
        after={
            "term_id": str(term_id),
            "pupils": len(rows),
            "fields": sorted(
                {
                    field_name
                    for row in rows
                    for field_name in REMARK_FIELDS
                    if getattr(row, field_name) is not None
                }
            ),
        },
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()

    return await class_review(db, actor, class_id=class_id, term_id=term_id)


# ---------------------------------------------------------------------------
# Approval, and the snapshot it takes (§4.5, R4, CLAUDE.md rule 6)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Snapshot:
    """What approval wrote, for the audit row and the caller's report."""

    scale_id: uuid.UUID
    scale_name: str
    rows: int
    graded: int
    ungraded: int
    reports: int


async def approve(
    db: AsyncSession,
    actor: User,
    *,
    class_id: uuid.UUID,
    term_id: uuid.UUID,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> tuple[ClassReview, Snapshot]:
    """Approve a class, snapshotting every grade on the way (§4.5).

    The order matters. The snapshot is written **before** the state changes,
    in one transaction: if the two were separate an interrupted approval could
    leave a class approved with no grades on it, and the only way back would
    be to recompute — which is the thing §4.5 forbids.
    """
    review = await class_review(db, actor, class_id=class_id, term_id=term_id)

    if review.state is not ClassTermState.SUBMITTED:
        # R14's table says the same thing; this says it first so the message
        # is about reviewing rather than about state names.
        raise Conflict(
            "Only a class that has been submitted for review can be approved. "
            f"This one is {review.state.value.replace('_', ' ')}."
        )

    snapshot = await _snapshot_grades(db, actor, review=review)

    await workflow.transition(
        db,
        actor,
        class_id=class_id,
        term_id=term_id,
        to=ClassTermState.APPROVED,
        action=AuditAction.CLASS_APPROVED,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    await audit.record(
        db,
        school_id=actor.school_id,
        action=AuditAction.GRADES_SNAPSHOTTED,
        entity_type="class",
        entity_id=class_id,
        actor_id=actor.id,
        after={
            "term_id": str(term_id),
            "grading_scale_id": str(snapshot.scale_id),
            "grading_scale_name": snapshot.scale_name,
            "rows": snapshot.rows,
            "graded": snapshot.graded,
            "ungraded": snapshot.ungraded,
            "reports": snapshot.reports,
        },
        reason=("Grades resolved and frozen at approval; never recomputed afterwards (§4.5)."),
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()

    return (
        await class_review(db, actor, class_id=class_id, term_id=term_id),
        snapshot,
    )


async def _snapshot_grades(db: AsyncSession, actor: User, *, review: ClassReview) -> Snapshot:
    """Write `grade_letter` and `grading_scale_id` onto every result row.

    §12's criterion for this milestone, and the one place in the system where
    a grade is decided. Three rules it keeps:

    - **A row that already carries a letter is left alone.** Nothing here
      overwrites a snapshot, whatever the current scale would say.
    - **The scale is recorded even when no letter resolves**, so a card with a
      blank grade can still be explained: the scale that was in force is on
      the row.
    - **The active scale must exist.** Approving against no scale would freeze
      a whole class's grades as blank, permanently.
    """
    scale = await grading.active_scale(db, actor)
    if scale is None:
        raise Conflict(
            "No grading scale is active, so grades cannot be resolved. An administrator "
            "activates one before a class is approved — and because grades are frozen at "
            "approval, this cannot be put right afterwards."
        )
    bands = await grading.bands_of(db, actor, scale.id)

    periods = [
        period.id
        for period in await all_of(
            db,
            scope.scoped_assessment_periods(actor).where(
                AssessmentPeriod.term_id == review.term.id
            ),
        )
    ]
    pupil_ids = [card.pupil.id for card in review.cards]
    if not (periods and pupil_ids):
        raise Conflict("This class has nothing to approve.")

    rows = await all_of(
        db,
        select(ResultEntry)
        .where(
            ResultEntry.school_id == actor.school_id,
            ResultEntry.assessment_period_id.in_(periods),
            ResultEntry.pupil_id.in_(pupil_ids),
        )
        .execution_options(populate_existing=True),
    )

    graded = ungraded = 0
    for entry in rows:
        if entry.grade_letter is not None:
            # Already frozen. Rule 6: never recompute.
            graded += 1
            continue
        band = grading.band_for(entry.period_average, bands)
        if band is not None:
            entry.grade_letter = band.letter
            graded += 1
        else:
            ungraded += 1
        entry.grading_scale_id = scale.id

    # R6's aggregate, frozen at the same moment and for the same reason: a
    # parent is about to be handed a card with it printed on (A25).
    second_half = await db.scalar(
        scope.scoped_assessment_periods(actor)
        .where(
            AssessmentPeriod.term_id == review.term.id,
            AssessmentPeriod.half == TermHalf.SECOND_HALF,
        )
        .with_only_columns(AssessmentPeriod.id)
    )
    reports = 0
    for card in review.cards:
        if card.report is None:
            continue
        averages = [
            entry.period_average
            for entry in rows
            if entry.pupil_id == card.pupil.id and entry.assessment_period_id == second_half
        ]
        card.report.overall_percentage = grading.overall_percentage(averages)
        reports += 1

    await db.flush()

    logger.info(
        "grades snapshotted",
        extra={
            "class_id": str(review.klass.id),
            "term_id": str(review.term.id),
            "rows": len(rows),
            "graded": graded,
        },
    )

    return Snapshot(
        scale_id=scale.id,
        scale_name=scale.name,
        rows=len(rows),
        graded=graded,
        ungraded=ungraded,
        reports=reports,
    )


async def return_class(
    db: AsyncSession,
    actor: User,
    *,
    class_id: uuid.UUID,
    term_id: uuid.UUID,
    note: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> ClassReview:
    """Send a class back to its teacher with a note (§8.4, R14).

    The note is required. R10's lesson applies here too: a class that comes
    back with no explanation is a phone call, and the class teacher has thirty
    cards to guess among.
    """
    if not note.strip():
        raise Conflict(
            "Say what needs changing. A class returned without a note leaves the teacher "
            "guessing which of thirty pupils to look at."
        )

    review = await class_review(db, actor, class_id=class_id, term_id=term_id)
    if review.state is not ClassTermState.SUBMITTED:
        raise Conflict(
            "Only a class that has been submitted for review can be returned. "
            f"This one is {review.state.value.replace('_', ' ')}."
        )

    await workflow.transition(
        db,
        actor,
        class_id=class_id,
        term_id=term_id,
        to=ClassTermState.RETURNED,
        action=AuditAction.CLASS_RETURNED,
        note=note.strip(),
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()

    return await class_review(db, actor, class_id=class_id, term_id=term_id)
