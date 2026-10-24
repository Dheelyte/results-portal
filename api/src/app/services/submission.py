"""R10's submission gate, and the progress page behind it
(ARCHITECTURE.md §6 R10, §8.3, §7).

R10 lists five conditions and then the part that matters most:

    Return a structured list of what is missing, by subject, by pupil and by
    section. "Cannot submit" with no explanation generates support calls every
    term.

So this module computes the answer to "what is left" in full, and the gate is
that answer being empty. One code path produces both — `GET /progress` shows
it and `POST /submit` refuses with it — because a screen that disagreed with
the button would be worse than no screen.

**What "complete" means for a subject.** Every pupil has a score in every
column the school has set a maximum for, on both of the term's sheets. Not
"has an average", which a half-entered row also has: R2 treats a blank as
zero, so a missing CA test prints as nothing earned, and nobody notices until
a parent does. A pupil who missed a test is marked 0 by the teacher, which is
what the paper sheet does too. Recorded as §14 A23.
"""

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import policy, scope
from app.models import (
    AssessmentPeriod,
    AttendanceRecord,
    AuditAction,
    Class,
    ClassSubject,
    ClassTermState,
    ClassTermStatus,
    GrowthRecord,
    MarksObtainable,
    NarrativeEntry,
    Pupil,
    ResultEntry,
    Subject,
    TeachingAssignment,
    Term,
    TermHalf,
    TermReport,
    User,
)
from app.services import marks, narrative, results, workflow
from app.services.errors import Blocked, NotPermitted
from app.services.support import all_of, has_text, one_or_404, rows_of

logger = logging.getLogger(__name__)

HALF_LABELS = {
    TermHalf.FIRST_HALF: "First Half Term",
    TermHalf.SECOND_HALF: "Second Half Term",
}

# Every key an outstanding item can carry. Filled in full, including the keys
# that do not apply, so that `GET /progress` and R10's 422 are byte-for-byte
# the same shape: one is validated through `OutstandingItem` and the other is
# the raw payload, and a client that handled one would otherwise trip over the
# other.
ITEM_KEYS = (
    "kind",
    "what",
    "detail",
    "pupil_id",
    "subject_id",
    "class_subject_id",
    "teacher",
)


def _item(kind: str, what: str, **extra: object) -> dict[str, object]:
    return {key: extra.get(key) for key in ITEM_KEYS} | {"kind": kind, "what": what}


@dataclass(frozen=True)
class SheetProgress:
    """One class-subject on one of the term's two sheets."""

    class_subject_id: uuid.UUID
    subject_id: uuid.UUID
    subject_name: str
    teacher_name: str | None
    half: TermHalf
    assessment_period_id: uuid.UUID | None
    columns: tuple[str, ...]
    # Pupils with every column filled in, out of the roll.
    complete: int
    roll: int
    # Named so §8.3 can show the teacher which children to chase, and no more
    # than a handful so a thirty-pupil gap does not become a wall of text.
    missing_pupils: list[str] = field(default_factory=list)
    missing_pupil_count: int = 0
    # True when the sheet has no usable Marks Obtainable row: nothing can be
    # entered, so this is the admin's blocker rather than the teacher's.
    not_configured: bool = False

    @property
    def is_complete(self) -> bool:
        return (
            not self.not_configured
            and self.assessment_period_id is not None
            and self.roll > 0
            and self.complete >= self.roll
        )


@dataclass(frozen=True)
class PupilProgress:
    """One pupil's four class-teacher tasks."""

    pupil_id: uuid.UUID
    name: str
    admission_number: str
    sections_written: int
    sections_total: int
    missing_sections: list[str] = field(default_factory=list)
    has_comment: bool = False
    has_attendance: bool = False
    has_growth: bool = False

    @property
    def is_complete(self) -> bool:
        return (
            self.sections_total > 0
            and self.sections_written >= self.sections_total
            and self.has_comment
            and self.has_attendance
            and self.has_growth
        )


def _pupil_gaps(pupil: "PupilProgress") -> list[str]:
    """What this pupil is still missing, in the order a teacher would do it."""
    gaps: list[str] = []
    if pupil.sections_total == 0:
        gaps.append("narrative (no sections are set up)")
    elif pupil.missing_sections:
        shown = ", ".join(pupil.missing_sections[:4])
        more = len(pupil.missing_sections) - 4
        gaps.append(f"narrative ({shown}{f' and {more} more' if more > 0 else ''})")
    if not pupil.has_comment:
        gaps.append("class teacher's comment")
    if not pupil.has_attendance:
        gaps.append("attendance")
    if not pupil.has_growth:
        gaps.append("height and weight")
    return gaps


@dataclass(frozen=True)
class Progress:
    """§8.3's page, and R10's answer, in one object."""

    klass: Class
    term: Term
    state: ClassTermState
    sheets: list[SheetProgress]
    pupils: list[PupilProgress]
    times_school_opened: int | None
    # Set when the caller is the class teacher; §5.2 gives the button to them.
    may_submit: bool
    return_note: str | None = None

    @property
    def outstanding(self) -> list[dict[str, object]]:
        """What is left, in the shape R10 asks for and the screen renders."""
        items: list[dict[str, object]] = []

        if self.times_school_opened is None:
            items.append(
                _item(
                    "term",
                    "The number of times the school opened this term is not set",
                    detail="An administrator sets this on the term.",
                )
            )

        if not self.pupils:
            items.append(
                _item(
                    "class",
                    "No pupils are enrolled in this class for this session",
                    detail="An administrator places pupils in a class.",
                )
            )

        for sheet in self.sheets:
            if sheet.is_complete:
                continue
            if sheet.assessment_period_id is None:
                items.append(
                    _item(
                        "sheet",
                        f"{HALF_LABELS[sheet.half]} has no assessment period",
                        detail="An administrator creates both halves with the term.",
                    )
                )
            elif sheet.not_configured:
                items.append(
                    _item(
                        "sheet",
                        f"{sheet.subject_name} — {HALF_LABELS[sheet.half]}: "
                        "no Marks Obtainable row",
                        detail="An administrator sets each column's maximum.",
                        subject_id=str(sheet.subject_id),
                        class_subject_id=str(sheet.class_subject_id),
                    )
                )
            else:
                more = sheet.missing_pupil_count - len(sheet.missing_pupils)
                items.append(
                    _item(
                        "scores",
                        f"{sheet.subject_name} — {HALF_LABELS[sheet.half]}: "
                        f"{sheet.missing_pupil_count} of {sheet.roll} pupils incomplete",
                        detail=", ".join(sheet.missing_pupils)
                        + (f" and {more} more" if more > 0 else ""),
                        subject_id=str(sheet.subject_id),
                        class_subject_id=str(sheet.class_subject_id),
                        teacher=sheet.teacher_name,
                    )
                )

        for pupil in self.pupils:
            if pupil.is_complete:
                continue
            items.append(
                _item(
                    "pupil",
                    f"{pupil.name}: {', '.join(_pupil_gaps(pupil))}",
                    detail=pupil.admission_number,
                    pupil_id=str(pupil.pupil_id),
                )
            )

        return items

    @property
    def ready(self) -> bool:
        return not self.outstanding


# ---------------------------------------------------------------------------
# Building it
# ---------------------------------------------------------------------------


async def _offerings(
    db: AsyncSession, actor: User, *, class_id: uuid.UUID, academic_session_id: uuid.UUID
) -> list[tuple[ClassSubject, Subject, str | None]]:
    """Every subject this class is offered, with who teaches it (§8.3).

    The class itself has already been scope-checked by the caller; this adds
    the subject's name and the teacher's, which is what §8.3 means by "state
    and owner".
    """
    offered = scope.subjects_offered_to(actor, class_id, academic_session_id).with_only_columns(
        ClassSubject.id
    )
    return list(
        await rows_of(
            db,
            select(ClassSubject, Subject, User.full_name)
            .join(Subject, Subject.id == ClassSubject.subject_id)
            .outerjoin(
                TeachingAssignment,
                TeachingAssignment.class_subject_id == ClassSubject.id,
            )
            .outerjoin(User, User.id == TeachingAssignment.teacher_user_id)
            .where(ClassSubject.id.in_(offered))
            .order_by(Subject.display_order, Subject.name),
        )
    )


async def _periods(db: AsyncSession, actor: User, term: Term) -> dict[TermHalf, AssessmentPeriod]:
    return {
        period.half: period
        for period in await all_of(
            db,
            scope.scoped_assessment_periods(actor).where(AssessmentPeriod.term_id == term.id),
        )
    }


async def _maxima(
    db: AsyncSession, actor: User, *, period_ids: Sequence[uuid.UUID], class_id: uuid.UUID
) -> dict[uuid.UUID, MarksObtainable | None]:
    """The applicable Marks Obtainable row per period: override, else school.

    The same resolution order as R1, resolved here in one query for both
    sheets rather than two calls per subject — thirty subjects would otherwise
    be sixty round trips to paint one page.
    """
    rows = await all_of(
        db,
        scope.scoped_marks_obtainable(actor).where(
            MarksObtainable.assessment_period_id.in_(period_ids)
        ),
    )
    resolved: dict[uuid.UUID, MarksObtainable | None] = {}
    for period_id in period_ids:
        for_period = [row for row in rows if row.assessment_period_id == period_id]
        override = next((row for row in for_period if row.class_id == class_id), None)
        resolved[period_id] = override or next(
            (row for row in for_period if row.class_id is None), None
        )
    return resolved


async def _entered(
    db: AsyncSession,
    actor: User,
    *,
    period_ids: Sequence[uuid.UUID],
    pupil_ids: Sequence[uuid.UUID],
    class_subject_ids: Sequence[uuid.UUID],
) -> dict[tuple[uuid.UUID, uuid.UUID, uuid.UUID], ResultEntry]:
    """Every score row for this class, keyed by period, subject and pupil.

    Queried by the ids already resolved above rather than through
    `scoped_result_entries`, which narrows a teacher to their own subjects —
    the same widening as `subjects_offered_to`, and for the same reason: R10
    is a statement about the whole class. The rows are counted, never read
    out: `columns_filled` below looks only at whether each cell is null.
    """
    if not (period_ids and pupil_ids and class_subject_ids):
        return {}

    rows = await all_of(
        db,
        select(ResultEntry).where(
            ResultEntry.school_id == actor.school_id,
            ResultEntry.assessment_period_id.in_(period_ids),
            ResultEntry.pupil_id.in_(pupil_ids),
            ResultEntry.class_subject_id.in_(class_subject_ids),
        ),
    )
    return {(row.assessment_period_id, row.class_subject_id, row.pupil_id): row for row in rows}


def columns_filled(entry: ResultEntry | None, columns: Sequence[str]) -> bool:
    """Whether every column the sheet carries has a score (A23).

    Not "has an average": R2 treats a blank as zero, so a row missing one CA
    test still produces a figure, and the gap only shows up when a parent
    compares the card with the paper sheet. A pupil who missed a test is
    marked 0, which is what the paper sheet does.
    """
    if entry is None:
        return False
    return all(getattr(entry, column) is not None for column in columns)


def _name(pupil: Pupil) -> str:
    return f"{pupil.last_name}, {pupil.first_name}"


async def class_progress(
    db: AsyncSession, actor: User, *, class_id: uuid.UUID, term_id: uuid.UUID
) -> Progress:
    """§8.3's page: every subject, both sheets, and the class teacher's tasks.

    One read. A class teacher opens this to find out what is left, and will
    reload it after every correction, so it is built to be cheap: a fixed
    number of queries regardless of how many subjects or pupils the class has.
    """
    klass = await one_or_404(db, scope.scoped_classes(actor).where(Class.id == class_id), "class")
    term = await one_or_404(db, scope.scoped_terms(actor).where(Term.id == term_id), "term")

    pupils = list(
        await results.pupils_of(
            db, actor, class_id=class_id, academic_session_id=term.academic_session_id
        )
    )
    pupil_ids = [pupil.id for pupil in pupils]

    offerings = await _offerings(
        db, actor, class_id=class_id, academic_session_id=term.academic_session_id
    )
    periods = await _periods(db, actor, term)
    maxima = await _maxima(
        db,
        actor,
        period_ids=[period.id for period in periods.values()],
        class_id=class_id,
    )
    entries = await _entered(
        db,
        actor,
        period_ids=[period.id for period in periods.values()],
        pupil_ids=pupil_ids,
        class_subject_ids=[offering.id for offering, _, _ in offerings],
    )

    sheets: list[SheetProgress] = []
    for half in TermHalf:
        period = periods.get(half)
        for offering, subject, teacher_name in offerings:
            if subject.is_group:
                # R7: a heading carries no scores, so it cannot be incomplete.
                continue

            row = maxima.get(period.id) if period is not None else None
            configured = marks.is_configured(row, half)
            columns = (
                tuple(
                    column
                    for column in marks.COLUMNS_BY_HALF[half]
                    if getattr(row, column) is not None
                )
                if configured and row is not None
                else ()
            )

            missing = [
                pupil
                for pupil in pupils
                if period is None
                or not columns_filled(entries.get((period.id, offering.id, pupil.id)), columns)
            ]
            sheets.append(
                SheetProgress(
                    class_subject_id=offering.id,
                    subject_id=subject.id,
                    subject_name=subject.name,
                    teacher_name=teacher_name,
                    half=half,
                    assessment_period_id=period.id if period is not None else None,
                    columns=columns,
                    complete=len(pupils) - len(missing),
                    roll=len(pupils),
                    missing_pupils=[_name(pupil) for pupil in missing[:3]],
                    missing_pupil_count=len(missing),
                    not_configured=not configured,
                )
            )

    pupil_progress = await _pupil_progress(db, actor, term=term, pupils=pupils, pupil_ids=pupil_ids)

    status = await db.scalar(
        scope.scoped_class_term_status(actor).where(
            ClassTermStatus.class_id == class_id, ClassTermStatus.term_id == term.id
        )
    )

    return Progress(
        klass=klass,
        term=term,
        state=status.state if status is not None else ClassTermState.NOT_STARTED,
        sheets=sheets,
        pupils=pupil_progress,
        times_school_opened=term.times_school_opened,
        may_submit=await policy.can_submit_class(db, actor, class_id, term.academic_session_id),
        return_note=status.return_note if status is not None else None,
    )


async def _pupil_progress(
    db: AsyncSession,
    actor: User,
    *,
    term: Term,
    pupils: Sequence[Pupil],
    pupil_ids: Sequence[uuid.UUID],
) -> list[PupilProgress]:
    """The four per-pupil tasks, in four queries rather than four per pupil."""
    sections = list(await narrative.active_sections(db, actor))
    labels = {section.id: section.label for section in sections}

    written: dict[uuid.UUID, set[uuid.UUID]] = {}
    if pupil_ids and sections:
        for pupil_id, section_id in await rows_of(
            db,
            select(NarrativeEntry.pupil_id, NarrativeEntry.section_id).where(
                NarrativeEntry.school_id == actor.school_id,
                NarrativeEntry.term_id == term.id,
                NarrativeEntry.pupil_id.in_(pupil_ids),
                NarrativeEntry.section_id.in_(labels),
                has_text(NarrativeEntry.body),
            ),
        ):
            written.setdefault(pupil_id, set()).add(section_id)

    async def ids_present(model, extra=None) -> set[uuid.UUID]:
        if not pupil_ids:
            return set()
        stmt = select(model.pupil_id).where(
            model.school_id == actor.school_id,
            model.term_id == term.id,
            model.pupil_id.in_(pupil_ids),
        )
        if extra is not None:
            stmt = stmt.where(extra)
        return set(await all_of(db, stmt))

    with_attendance = await ids_present(AttendanceRecord)
    with_growth = await ids_present(GrowthRecord)
    with_comment = await ids_present(TermReport, has_text(TermReport.class_teacher_comment))

    ordered = [section.id for section in sections]
    return [
        PupilProgress(
            pupil_id=pupil.id,
            name=_name(pupil),
            admission_number=pupil.admission_number,
            sections_written=len(written.get(pupil.id, set())),
            sections_total=len(sections),
            missing_sections=[
                labels[section_id]
                for section_id in ordered
                if section_id not in written.get(pupil.id, set())
            ],
            has_comment=pupil.id in with_comment,
            has_attendance=pupil.id in with_attendance,
            has_growth=pupil.id in with_growth,
        )
        for pupil in pupils
    ]


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


async def submit(
    db: AsyncSession,
    actor: User,
    *,
    class_id: uuid.UUID,
    term_id: uuid.UUID,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> Progress:
    """Submit a class for review, if R10 lets it (§7: 422 and the list).

    Three refusals, each a different status on purpose:

    - **403** the caller is not the class teacher of this class (§5.2).
    - **409** the class is already submitted or approved (R14).
    - **422** something is still outstanding, with the list.
    """
    progress = await class_progress(db, actor, class_id=class_id, term_id=term_id)

    if not progress.may_submit:
        raise NotPermitted(
            "Only the class teacher submits a class for review. "
            "If you should be the class teacher, an administrator sets that."
        )

    if not progress.ready:
        raise Blocked(
            f"{len(progress.outstanding)} "
            f"{'item is' if len(progress.outstanding) == 1 else 'items are'} still outstanding, "
            "so this class cannot be submitted yet.",
            progress.outstanding,
        )

    await workflow.transition(
        db,
        actor,
        class_id=class_id,
        term_id=term_id,
        to=ClassTermState.SUBMITTED,
        action=AuditAction.CLASS_SUBMITTED,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    await _ensure_reports(db, actor, progress=progress)
    await db.commit()

    return await class_progress(db, actor, class_id=class_id, term_id=term_id)


async def _ensure_reports(db: AsyncSession, actor: User, *, progress: Progress) -> None:
    """Every pupil has a `term_reports` row once the class is submitted.

    Publication acts on these rows (R12) and the head teacher's remark hangs
    off them (§4.8), so the set has to be complete before review begins. A
    pupil whose comment was written already has one; this is for the rest.

    `no_in_class` is filled in here because submission is the moment the roll
    is final — it prints on the card beside the pupil's own figures, and
    §4.8 does not say who sets it (§14 A24).
    """
    existing = {
        report.pupil_id: report
        for report in await all_of(
            db,
            scope.scoped_term_reports(actor).where(
                TermReport.term_id == progress.term.id,
                TermReport.pupil_id.in_([pupil.pupil_id for pupil in progress.pupils]),
            ),
        )
    }

    for pupil in progress.pupils:
        report = existing.get(pupil.pupil_id)
        if report is None:
            report = TermReport(
                school_id=actor.school_id,
                term_id=progress.term.id,
                pupil_id=pupil.pupil_id,
                class_id=progress.klass.id,
            )
            db.add(report)
        report.no_in_class = len(progress.pupils)

    await db.flush()
