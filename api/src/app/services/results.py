"""Score entry (ARCHITECTURE.md §4.4, §6 R1-R4, §7, §8.1).

`PUT /class-subjects/{id}/entries` is the most-used write in the system: a
teacher saves a whole class at once, thirty rows across up to eight columns,
on a phone, several times a term. Everything about this module is shaped by
that — it validates the whole set before writing any of it, reports refusals
per pupil so the grid can paint the offending cell, and never leaves a sheet
half-saved.

Rules enforced here:

- **R1** every score is >= 0 and <= its column in the applicable Marks
  Obtainable row, and the refusal names that maximum.
- **R2** CA Test Total is not written at all — Postgres generates it.
- **R3** the period average is recomputed on every save, by the single named
  function in `services/grading.py`.
- **R4** the grade shown during entry is resolved live from the active scale.
  Nothing is snapshotted here; that happens at approval (milestone 9), and
  `grade_letter` stays NULL until then.
- **R7** a group heading carries no scores, so its class-subject offers no
  sheet at all.
- **R14** a submitted or approved class is read-only for teachers.
"""

import decimal
import logging
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import scope
from app.models import (
    AcademicSession,
    AssessmentPeriod,
    AuditAction,
    Class,
    ClassSubject,
    ClassTermState,
    Enrollment,
    GradeBand,
    MarksObtainable,
    Pupil,
    ResultEntry,
    Subject,
    Term,
    TermHalf,
    User,
)
from app.services import academic, audit, grading, marks, workflow
from app.services.errors import Conflict, Invalid, NotFound, RowErrors
from app.services.support import all_of, one_or_404, rows_of

logger = logging.getLogger(__name__)

# R1: "One decimal place." The column itself is numeric(5,2) — it shares the
# type with `period_average`, which needs two — so this is a rule rather than
# a constraint, and it belongs here with the other half of R1.
SCORE_DECIMAL_PLACES = 1
SCORE_STEP = decimal.Decimal("0.1")


@dataclass(frozen=True)
class Row:
    """One pupil's scores as submitted. Absent columns are left alone."""

    pupil_id: uuid.UUID
    scores: Mapping[str, decimal.Decimal | None]


@dataclass(frozen=True)
class SheetRow:
    """One line of the grid, ready to render."""

    pupil: Pupil
    entry: ResultEntry | None
    grade: GradeBand | None


@dataclass(frozen=True)
class Sheet:
    """One class-subject's grid for one assessment period."""

    class_subject: ClassSubject
    subject: Subject
    klass: Class
    period: AssessmentPeriod
    term: Term
    columns: tuple[str, ...]
    maxima: MarksObtainable | None
    state: ClassTermState
    editable: bool
    rows: list[SheetRow] = field(default_factory=list)

    @property
    def configured(self) -> bool:
        return marks.is_configured(self.maxima, self.period.half)


@dataclass(frozen=True)
class Workload:
    """A teacher's whole term: which term it is, its sheets, and their state.

    One response rather than three because of what a teacher can reach. §5.2
    gives the calendar to the admin alone, so a teacher has no endpoint that
    would tell them which term is current or what the two assessment periods
    are — and without those ids the grid cannot be opened at all
    (docs/DECISIONS.md D51).
    """

    term: Term
    academic_session_name: str
    periods: list[AssessmentPeriod]
    assignments: list["Assignment"]
    # The classes this caller is class teacher of. A separate list because it
    # is a different job: §5.2 gives the narrative, attendance, growth and the
    # class teacher's comment to the class teacher of a class, whatever
    # subjects they happen to teach in it. Without this a class teacher has no
    # way to find that work at all.
    class_teacher_of: list[Class]


@dataclass(frozen=True)
class Assignment:
    """One line of a teacher's "what am I entering" list (§7 /my/assignments)."""

    class_subject_id: uuid.UUID
    class_id: uuid.UUID
    class_name: str
    subject_id: uuid.UUID
    subject_name: str
    pupil_count: int
    entered_count: dict[str, int]
    state: ClassTermState


# ---------------------------------------------------------------------------
# Loading a sheet
# ---------------------------------------------------------------------------


async def _class_subject(
    db: AsyncSession, actor: User, class_subject_id: uuid.UUID
) -> ClassSubject:
    return await one_or_404(
        db,
        scope.scoped_class_subjects(actor).where(ClassSubject.id == class_subject_id),
        "class-subject",
    )


async def _period_and_term(
    db: AsyncSession, actor: User, assessment_period_id: uuid.UUID
) -> tuple[AssessmentPeriod, Term]:
    period = await one_or_404(
        db,
        scope.scoped_assessment_periods(actor).where(AssessmentPeriod.id == assessment_period_id),
        "assessment period",
    )
    term = await one_or_404(db, scope.scoped_terms(actor).where(Term.id == period.term_id), "term")
    return period, term


async def pupils_of(
    db: AsyncSession, actor: User, *, class_id: uuid.UUID, academic_session_id: uuid.UUID
) -> Sequence[Pupil]:
    """The class roll, in the order the card lists it.

    Surname first, which is how the school's own sheets are ordered, so a
    teacher reading from paper does not have to hunt up and down the screen.

    Public because the narrative screen walks the same roll in the same order
    (§8.2's previous/next pupil). Two orderings of one class would have the
    teacher hunting for the pupil they just left.
    """
    visible = scope.scoped_pupils(actor, academic_session_id).with_only_columns(Pupil.id)
    return await all_of(
        db,
        select(Pupil)
        .join(Enrollment, Enrollment.pupil_id == Pupil.id)
        .where(
            Pupil.id.in_(visible),
            Enrollment.class_id == class_id,
            Enrollment.academic_session_id == academic_session_id,
            Pupil.is_active.is_(True),
        )
        .order_by(Pupil.last_name, Pupil.first_name, Pupil.admission_number),
    )


async def load_sheet(
    db: AsyncSession,
    actor: User,
    *,
    class_subject_id: uuid.UUID,
    assessment_period_id: uuid.UUID,
) -> Sheet:
    """Everything the grid needs for one class-subject and one period."""
    class_subject = await _class_subject(db, actor, class_subject_id)
    period, term = await _period_and_term(db, actor, assessment_period_id)

    if term.academic_session_id != class_subject.academic_session_id:
        # Two valid ids that do not belong together. Refusing is not pedantry:
        # silently entering a 2026/27 class against a 2025/26 sheet writes
        # rows nobody will find again.
        raise Invalid("That assessment period belongs to a different academic session.")

    subject = await one_or_404(
        db,
        scope.scoped_subjects(actor).where(Subject.id == class_subject.subject_id),
        "subject",
    )
    if subject.is_group:
        # R7. The offering should never have been created either, and
        # `services/subjects.py` refuses to — this is the second line.
        raise Invalid(
            f"{subject.name} is a heading on the card and carries no scores of its own. "
            "Enter scores against the subjects listed beneath it."
        )

    klass = await one_or_404(
        db, scope.scoped_classes(actor).where(Class.id == class_subject.class_id), "class"
    )

    state = await workflow.state_of(db, actor, class_id=klass.id, term_id=term.id)
    maxima = await marks.applicable_maxima(
        db, actor, assessment_period_id=period.id, class_id=klass.id
    )

    pupils = await pupils_of(
        db,
        actor,
        class_id=klass.id,
        academic_session_id=class_subject.academic_session_id,
    )
    entries = {
        entry.pupil_id: entry
        for entry in await all_of(
            db,
            scope.scoped_result_entries(actor)
            .where(
                ResultEntry.assessment_period_id == period.id,
                ResultEntry.class_subject_id == class_subject.id,
            )
            # Overwrite anything the session already holds with what the
            # database holds. `SessionLocal` is built with
            # expire_on_commit=False, so after a save the identity map still
            # carries the Decimals Python assigned — the response would then
            # say "40" where the numeric(5,2) column says "40.00", and
            # `ca_test_total` and `updated_at`, both written by Postgres,
            # would be whatever they were before the save.
            .execution_options(populate_existing=True),
        )
    }

    bands = await _active_bands(db, actor)

    return Sheet(
        class_subject=class_subject,
        subject=subject,
        klass=klass,
        period=period,
        term=term,
        columns=marks.COLUMNS_BY_HALF[period.half],
        maxima=maxima,
        state=state,
        editable=workflow.teacher_may_edit(state),
        rows=[
            SheetRow(
                pupil=pupil,
                entry=entries.get(pupil.id),
                grade=_grade_of(entries.get(pupil.id), bands),
            )
            for pupil in pupils
        ],
    )


async def _active_bands(db: AsyncSession, actor: User) -> Sequence[GradeBand]:
    """The active scale's bands, or none if the school has not set one up.

    R4: before approval the grade is resolved from the active scale on the
    fly. After approval the snapshot on the row is what counts, and nothing
    here recomputes it (CLAUDE.md rule 6).
    """
    scale = await grading.active_scale(db, actor)
    if scale is None:
        return []
    return await grading.bands_of(db, actor, scale.id)


def _grade_of(entry: ResultEntry | None, bands: Sequence[GradeBand]) -> GradeBand | None:
    if entry is None:
        return None
    if entry.grade_letter is not None:
        # Approved. The printed card said this, so the portal says it too.
        return None
    return grading.band_for(entry.period_average, bands)


# ---------------------------------------------------------------------------
# Saving a sheet
# ---------------------------------------------------------------------------


def _validate(
    rows: Sequence[Row],
    *,
    columns: Sequence[str],
    maxima: MarksObtainable,
    known_pupils: set[uuid.UUID],
) -> dict[str, dict[str, str]]:
    """R1, for every cell of the submitted set.

    Returns refusals keyed by pupil id and then by column, so the grid can
    paint exactly the cells that are wrong (§8.1 wants a red cell naming the
    maximum, not a modal). Collects every refusal rather than stopping at the
    first: a teacher who mistyped three cells should be told about three.
    """
    errors: dict[str, dict[str, str]] = {}

    for row in rows:
        key = str(row.pupil_id)
        row_errors: dict[str, str] = {}

        if row.pupil_id not in known_pupils:
            # Not "no such pupil": the id may well exist in another class.
            errors[key] = {"pupil_id": "This pupil is not in this class for this session."}
            continue

        for column, value in row.scores.items():
            if column not in columns:
                row_errors[column] = (
                    f"This sheet has no {_label(column)} column. "
                    f"The {_half_name(columns)} sheet ends in {_label(columns[-1])}."
                )
                continue

            if value is None:
                continue

            maximum = getattr(maxima, column)
            if maximum is None:
                row_errors[column] = (
                    f"{_label(column)} has no maximum set, so nothing can be entered "
                    "against it. An administrator sets these on the Marks Obtainable row."
                )
            elif value < 0:
                row_errors[column] = "A score cannot be negative."
            elif value != value.quantize(SCORE_STEP):
                # R1: "One decimal place." The column is numeric(5,2) because
                # `period_average` shares the type, but a mark of 7.25 is a
                # typing slip rather than a score the school awards.
                #
                # The test is on the **value**, not its representation. "8.00"
                # carries two decimal digits and is still the whole number
                # eight — and it is exactly what this API returns for a column
                # maximum, so refusing it would mean refusing a figure the
                # server itself had just handed out.
                row_errors[column] = "A score may have at most one decimal place."
            elif value > maximum:
                # Naming the maximum is R1's own requirement: the teacher needs
                # to know what the ceiling is, not merely that they exceeded it.
                row_errors[column] = f"{_label(column)} is out of {_plain(maximum)}."

        if row_errors:
            errors[key] = row_errors

    return errors


def _label(column: str) -> str:
    """The column's name as the card prints it."""
    if column.startswith("ca_test_"):
        return f"CA Test {column.rsplit('_', 1)[1]}"
    return {"mid_term_test": "Mid Term Test", "exam": "Exam"}.get(column, column)


def _half_name(columns: Sequence[str]) -> str:
    return "first half" if "mid_term_test" in columns else "second half"


def _plain(value: decimal.Decimal) -> str:
    """A maximum as a person would write it: 40, not 40.00."""
    normalised = value.normalize()
    return f"{normalised:f}"


async def save_entries(
    db: AsyncSession,
    actor: User,
    *,
    class_subject_id: uuid.UUID,
    assessment_period_id: uuid.UUID,
    rows: Sequence[Row],
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> Sheet:
    """Upsert a set of score rows, all or none (§7).

    All or none matters more than it looks. The grid autosaves a dirty set
    every twenty seconds (§8.1); if a partial save were possible, a teacher
    would be left with some cells written, some not, and no way to tell which
    from looking at the screen.
    """
    sheet = await load_sheet(
        db,
        actor,
        class_subject_id=class_subject_id,
        assessment_period_id=assessment_period_id,
    )

    workflow.refuse_if_locked(sheet.state)

    if sheet.maxima is None or not sheet.configured:
        raise Conflict(
            "The Marks Obtainable row for this sheet is not set up yet, so there is nothing "
            "to check these scores against. Ask an administrator to set the maximum for each "
            "column first."
        )

    if not sheet.rows:
        raise Conflict("No pupils are enrolled in this class for this session.")

    known = {row.pupil.id for row in sheet.rows}
    errors = _validate(rows, columns=sheet.columns, maxima=sheet.maxima, known_pupils=known)
    if errors:
        raise RowErrors(
            f"{len(errors)} of {len(rows)} rows were rejected, so nothing was saved.",
            errors,
        )

    existing = {row.pupil.id: row.entry for row in sheet.rows}
    maxima_map = {column: getattr(sheet.maxima, column) for column in marks.ALL_COLUMNS}

    created = 0
    for row in rows:
        entry = existing.get(row.pupil_id)
        if entry is None:
            entry = ResultEntry(
                school_id=actor.school_id,
                assessment_period_id=sheet.period.id,
                pupil_id=row.pupil_id,
                class_subject_id=sheet.class_subject.id,
            )
            db.add(entry)
            created += 1

        for column, value in row.scores.items():
            setattr(entry, column, value)

        entry.entered_by = actor.id
        entry.period_average = grading.period_average(
            sheet.period.half, _scores_of(entry, sheet.columns), maxima_map
        )

    await db.flush()

    await workflow.mark_in_progress(
        db,
        actor,
        class_id=sheet.klass.id,
        term_id=sheet.term.id,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    await audit.record(
        db,
        school_id=actor.school_id,
        action=AuditAction.SCORES_SAVED,
        entity_type="class_subject",
        entity_id=sheet.class_subject.id,
        actor_id=actor.id,
        # Counts only. A score in an audit payload is still a score in a log
        # (CLAUDE.md), and "who saved what, when" needs none of the values.
        after={
            "assessment_period_id": str(sheet.period.id),
            "half": sheet.period.half.value,
            "rows_saved": len(rows),
            "rows_created": created,
            "columns": sorted({column for row in rows for column in row.scores}),
        },
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()

    return await load_sheet(
        db,
        actor,
        class_subject_id=class_subject_id,
        assessment_period_id=assessment_period_id,
    )


def _scores_of(entry: ResultEntry, columns: Sequence[str]) -> dict[str, decimal.Decimal | None]:
    return {column: getattr(entry, column) for column in columns}


# ---------------------------------------------------------------------------
# A teacher's own list of sheets (§7 GET /my/assignments)
# ---------------------------------------------------------------------------


async def my_work(db: AsyncSession, actor: User, *, term_id: uuid.UUID | None = None) -> Workload:
    """Every class-subject this caller enters scores for, with its progress.

    The first screen a teacher sees. It carries the entered counts per half
    because the alternative is a teacher opening eight sheets to find the one
    they have not finished.

    `term_id` is optional and the current term is the default: §2.3 puts
    "which term is current" in the platform, and §5.2 gives the calendar to
    the admin alone, so a teacher has no endpoint that would let them look it
    up (docs/DECISIONS.md D51).
    """
    if term_id is None:
        current = await academic.current_term_or_none(db, actor)
        if current is None:
            raise Conflict(
                "No term has been marked as the current one yet. "
                "An administrator sets that up before scores can be entered."
            )
        term = current
    else:
        term = await one_or_404(db, scope.scoped_terms(actor).where(Term.id == term_id), "term")

    academic_session = await one_or_404(
        db,
        scope.scoped_academic_sessions(actor).where(AcademicSession.id == term.academic_session_id),
        "academic session",
    )

    offerings = await rows_of(
        db,
        select(ClassSubject, Class, Subject)
        .join(Class, Class.id == ClassSubject.class_id)
        .join(Subject, Subject.id == ClassSubject.subject_id)
        .where(
            ClassSubject.id.in_(
                scope.scoped_class_subjects(actor, term.academic_session_id).with_only_columns(
                    ClassSubject.id
                )
            ),
            ClassSubject.academic_session_id == term.academic_session_id,
        )
        .order_by(Class.level_order, Class.name, Subject.display_order),
    )

    ordered_periods = list(
        await all_of(
            db,
            scope.scoped_assessment_periods(actor)
            .where(AssessmentPeriod.term_id == term.id)
            .order_by(AssessmentPeriod.half),
        )
    )
    periods = {period.half: period for period in ordered_periods}

    my_classes = await all_of(
        db,
        select(Class)
        .where(
            Class.id.in_(scope.class_ids_where_class_teacher(actor, term.academic_session_id)),
            Class.school_id == actor.school_id,
        )
        .order_by(Class.level_order, Class.name),
    )

    roll = await _roll_sizes(db, actor, academic_session_id=term.academic_session_id)
    counts = await _entry_counts(db, actor, periods=periods)

    assignments: list[Assignment] = []
    for class_subject, klass, subject in offerings:
        state = await workflow.state_of(db, actor, class_id=klass.id, term_id=term.id)
        assignments.append(
            Assignment(
                class_subject_id=class_subject.id,
                class_id=klass.id,
                class_name=klass.name,
                subject_id=subject.id,
                subject_name=subject.name,
                pupil_count=roll.get(klass.id, 0),
                entered_count={
                    half.value: counts.get((half, class_subject.id), 0) for half in periods
                },
                state=state,
            )
        )

    return Workload(
        term=term,
        academic_session_name=academic_session.name,
        periods=ordered_periods,
        assignments=assignments,
        class_teacher_of=list(my_classes),
    )


async def _roll_sizes(
    db: AsyncSession, actor: User, *, academic_session_id: uuid.UUID
) -> dict[uuid.UUID, int]:
    from sqlalchemy import func

    rows = await rows_of(
        db,
        select(Enrollment.class_id, func.count())
        .join(Pupil, Pupil.id == Enrollment.pupil_id)
        .where(
            Enrollment.school_id == actor.school_id,
            Enrollment.academic_session_id == academic_session_id,
            Pupil.is_active.is_(True),
        )
        .group_by(Enrollment.class_id),
    )
    return {class_id: count for class_id, count in rows}


async def _entry_counts(
    db: AsyncSession, actor: User, *, periods: Mapping[TermHalf, AssessmentPeriod]
) -> dict[tuple[TermHalf, uuid.UUID], int]:
    """How many pupils have at least one score, per sheet.

    "At least one" rather than "complete": completeness is R10's question and
    milestone 8 answers it against every column. This is a progress hint on a
    list screen, and it says so by being a count rather than a tick.
    """
    from sqlalchemy import func

    by_period = {period.id: half for half, period in periods.items()}
    if not by_period:
        return {}

    visible = scope.scoped_result_entries(actor).with_only_columns(ResultEntry.id)
    rows = await rows_of(
        db,
        select(
            ResultEntry.assessment_period_id,
            ResultEntry.class_subject_id,
            func.count(),
        )
        .where(
            ResultEntry.id.in_(visible),
            ResultEntry.assessment_period_id.in_(by_period),
            ResultEntry.ca_test_total.is_not(None),
        )
        .group_by(ResultEntry.assessment_period_id, ResultEntry.class_subject_id),
    )
    return {
        (by_period[period_id], class_subject_id): count
        for period_id, class_subject_id, count in rows
    }


async def entries_of_pupil(
    db: AsyncSession, actor: User, *, pupil_id: uuid.UUID, assessment_period_id: uuid.UUID
) -> Sequence[ResultEntry]:
    """One pupil's rows across every subject, for the card and the review."""
    if not await db.scalar(
        select(Pupil.id).where(
            Pupil.id.in_(scope.scoped_pupils(actor).with_only_columns(Pupil.id)),
            Pupil.id == pupil_id,
        )
    ):
        raise NotFound("No such pupil.")

    return await all_of(
        db,
        scope.scoped_result_entries(actor).where(
            ResultEntry.pupil_id == pupil_id,
            ResultEntry.assessment_period_id == assessment_period_id,
        ),
    )
