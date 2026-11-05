"""Assembling one pupil's card (ARCHITECTURE.md §9, §1.4).

Everything the PDF prints, gathered once and handed to the template as plain
data. The template does no arithmetic and no lookups: §9's structure is a
layout concern, and every figure on the page was decided somewhere else —
R2 by Postgres, R3 and R4 by `services/grading.py`, R5 by
`services/cumulative.py`, R6 at approval.

The photographs in `docs/report-card/` are the specification, and two things
in them are easy to miss:

- The card is headed **"CONTINUOUS ASSESSMENT FOR {TERM} TERM"** with
  **"{HALF} HALF TERM"** beneath it. One card per half term, not one per
  term — which is why `half` is part of the key everywhere below.
- The second-half sheet's cumulative columns read **2ND TERM AVE., 1ST TERM
  AVE., ANNUAL SCORES (AVE.)** — second before first. That is the order
  printed, so it is the order here.

**The grade key is the snapshotted scale, not the current one** (§9 item 6).
A card reprinted a year later must carry the bands it was graded against, or
the letters on it stop being explicable.
"""

import datetime as dt
import decimal
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import scope
from app.models import (
    AcademicSession,
    AssessmentPeriod,
    AttendanceRecord,
    Class,
    ClassSubject,
    GradeBand,
    GradingScale,
    GrowthRecord,
    House,
    NarrativeEntry,
    NarrativeSection,
    Pupil,
    ResultEntry,
    School,
    Subject,
    Term,
    TermHalf,
    TermNumber,
    TermReport,
    User,
)
from app.services import cumulative, marks
from app.services.errors import Conflict, NotFound
from app.services.support import all_of, one_or_404, rows_of

logger = logging.getLogger(__name__)

TERM_NAMES = {
    TermNumber.FIRST: "FIRST",
    TermNumber.SECOND: "SECOND",
    TermNumber.THIRD: "THIRD",
}
HALF_NAMES = {TermHalf.FIRST_HALF: "FIRST", TermHalf.SECOND_HALF: "SECOND"}

# The score columns each sheet prints, in the photographed order. These are
# the *printed* columns, which is more than the enterable ones: CA Test Total
# is generated (R2) and the average and grade are derived.
PRINTED_COLUMNS = {
    TermHalf.FIRST_HALF: (
        ("ca_test_1", "CA TEST 1"),
        ("ca_test_2", "CA TEST 2"),
        ("ca_test_3", "CA TEST 3"),
        ("ca_test_4", "CA TEST 4"),
        ("ca_test_5", "CA TEST 5"),
        ("ca_test_total", "CA TEST TOTAL"),
        ("mid_term_test", "MID TERM TEST"),
        ("period_average", "MID TERM AVE."),
    ),
    TermHalf.SECOND_HALF: (
        ("ca_test_1", "CA TEST 1"),
        ("ca_test_2", "CA TEST 2"),
        ("ca_test_3", "CA TEST 3"),
        ("ca_test_4", "CA TEST 4"),
        ("ca_test_5", "CA TEST 5"),
        ("ca_test_total", "CA TEST TOTAL"),
        ("exam", "EXAM"),
        ("period_average", "TOTAL WEIGHTED AVERAGE"),
    ),
}


@dataclass(frozen=True)
class SubjectLine:
    """One row of the score table, as printed."""

    subject_id: uuid.UUID
    name: str
    # The spanning heading this row sits under, on the first row of the group
    # only — the template draws a vertical label down the merged cell.
    group_name: str | None
    group_size: int
    # True for every row inside a group, including the first. Rows after the
    # first emit no rail cell at all — the first row's rowspan covers them.
    in_group: bool
    values: dict[str, decimal.Decimal | None]
    # Keyed by the printed column label: "2ND TERM AVE." and so on.
    cumulative: dict[str, decimal.Decimal | None]
    grade: str | None


@dataclass(frozen=True)
class Card:
    """Everything §9 prints, ready for the template."""

    school_name: str
    title: str
    subtitle: str

    date: dt.date | None
    pupil_name: str
    admission_number: str
    overall_percentage: decimal.Decimal | None
    position_text: str | None
    class_name: str
    session_name: str
    no_in_class: int | None
    house_name: str | None

    times_school_opened: int | None
    times_present: int | None
    times_absent: int | None
    times_late: int | None

    height_start_m: decimal.Decimal | None
    height_end_m: decimal.Decimal | None
    weight_start_kg: decimal.Decimal | None
    weight_end_kg: decimal.Decimal | None

    columns: list[tuple[str, str]]
    # §9: render a cumulative column only when the pupil has results for that
    # term. None in first term, one in second, both plus the annual in third.
    cumulative_columns: list[str]
    maxima: dict[str, decimal.Decimal | None]
    lines: list[SubjectLine]
    grand_total: dict[str, decimal.Decimal | None]

    key: list[tuple[str, str, str]]

    # (letter, group label or None, [(code, label, body)]). The letter comes
    # from the section codes — "A.english_language_arts" is in block A — so
    # the template prints what the school configured rather than counting.
    narrative_groups: list[tuple[str, str | None, list[tuple[str, str, str | None]]]]

    class_teacher_comment: str | None
    head_teacher_remark: str | None
    promotion_decision: str | None
    return_date: dt.date | None

    # For the object key (§9) and the filename.
    version: int


async def build(
    db: AsyncSession,
    actor: User,
    *,
    pupil_id: uuid.UUID,
    term_id: uuid.UUID,
    half: TermHalf,
) -> Card:
    """Gather one pupil's card for one half term.

    Scope-filtered throughout, so a parent reaches only their own child's and
    a member of staff only what §5.2 allows. `scoped_term_reports` already
    restricts a parent to published rows, so an unpublished card is simply
    not found rather than refused (R12).
    """
    pupil = await one_or_404(db, scope.scoped_pupils(actor).where(Pupil.id == pupil_id), "pupil")
    term = await one_or_404(db, scope.scoped_terms(actor).where(Term.id == term_id), "term")
    session_name = await db.scalar(
        scope.scoped_academic_sessions(actor)
        .where(AcademicSession.id == term.academic_session_id)
        .with_only_columns(AcademicSession.name)
    )

    report = await db.scalar(
        scope.scoped_term_reports(actor).where(
            TermReport.term_id == term.id, TermReport.pupil_id == pupil_id
        )
    )
    if report is None:
        raise NotFound("No report for this pupil and term.")

    period = await db.scalar(
        scope.scoped_assessment_periods(actor).where(
            AssessmentPeriod.term_id == term.id, AssessmentPeriod.half == half
        )
    )
    if period is None:
        raise Conflict("That half term has no assessment period.")

    klass = await one_or_404(
        db, scope.scoped_classes(actor).where(Class.id == report.class_id), "class"
    )
    house = (
        await db.scalar(
            scope.scoped_houses(actor)
            .where(House.id == pupil.house_id)
            .with_only_columns(House.name)
        )
        if pupil.house_id
        else None
    )

    # **The report is the gate, not the row.** `scoped_result_entries`
    # deliberately returns nothing to a parent — milestone 6 made that choice
    # because a parent must not reach the score table directly — and the
    # report above is what grants sight of these figures: `scoped_term_reports`
    # already refused unless this caller may see it, which for a parent means
    # their own child and `state = 'published'` (R12).
    #
    # So the query is filtered by school, pupil and period rather than by the
    # row scope. Reaching here at all means the card may be read; narrowing
    # again would mean a parent's own published card came back empty
    # (docs/DECISIONS.md D88).
    rows = await rows_of(
        db,
        select(ResultEntry, Subject)
        .join(ClassSubject, ClassSubject.id == ResultEntry.class_subject_id)
        .join(Subject, Subject.id == ClassSubject.subject_id)
        .where(
            ResultEntry.school_id == actor.school_id,
            ResultEntry.pupil_id == pupil_id,
            ResultEntry.assessment_period_id == period.id,
        )
        .order_by(Subject.display_order, Subject.name),
    )

    headings = {
        subject.id: subject
        for subject in await all_of(
            db, scope.scoped_subjects(actor).where(Subject.is_group.is_(True))
        )
    }

    prior, prior_terms = await cumulative.prior_term_averages(
        db, actor, pupil_id=pupil_id, term=term
    )
    cumulative_columns = _cumulative_columns(half, prior_terms)

    maxima = await _maxima(db, actor, period_id=period.id, class_id=klass.id)
    columns = list(PRINTED_COLUMNS[half])

    lines = _subject_lines(rows, headings=headings, prior=prior, prior_terms=prior_terms)

    attendance = await db.scalar(
        scope.scoped_attendance(actor).where(
            AttendanceRecord.term_id == term.id, AttendanceRecord.pupil_id == pupil_id
        )
    )
    growth = await db.scalar(
        scope.scoped_growth(actor).where(
            GrowthRecord.term_id == term.id, GrowthRecord.pupil_id == pupil_id
        )
    )

    return Card(
        school_name=await _school_name(db, actor),
        title=f"CONTINUOUS ASSESSMENT FOR {TERM_NAMES.get(term.number, '')} TERM",
        subtitle=f"{HALF_NAMES[half]} HALF TERM",
        date=report.published_at.date() if report.published_at else None,
        pupil_name=_full_name(pupil),
        admission_number=pupil.admission_number,
        overall_percentage=report.overall_percentage,
        position_text=report.position_text,
        class_name=klass.name,
        session_name=session_name or "",
        no_in_class=report.no_in_class,
        house_name=house,
        times_school_opened=term.times_school_opened,
        times_present=attendance.times_present if attendance else None,
        times_absent=attendance.times_absent if attendance else None,
        times_late=attendance.times_late if attendance else None,
        height_start_m=growth.height_start_m if growth else None,
        height_end_m=growth.height_end_m if growth else None,
        weight_start_kg=growth.weight_start_kg if growth else None,
        weight_end_kg=growth.weight_end_kg if growth else None,
        columns=columns,
        cumulative_columns=cumulative_columns,
        maxima=maxima,
        lines=lines,
        grand_total=_grand_total(lines, columns=columns, cumulative=cumulative_columns),
        key=await _key(db, actor, rows),
        narrative_groups=await _narrative(db, actor, pupil_id=pupil_id, term_id=term.id),
        class_teacher_comment=report.class_teacher_comment,
        head_teacher_remark=report.head_teacher_remark,
        promotion_decision=report.promotion_decision,
        return_date=_return_date(term),
        version=1 if report.pdf_object_key is None else _next_version(report.pdf_object_key),
    )


def _full_name(pupil: Pupil) -> str:
    parts = [pupil.last_name, pupil.first_name, pupil.middle_name or ""]
    return " ".join(part for part in parts if part).strip()


async def _school_name(db: AsyncSession, actor: User) -> str:

    return await db.scalar(select(School.name).where(School.id == actor.school_id)) or ""


def _cumulative_columns(half: TermHalf, prior_terms: Sequence[TermNumber]) -> list[str]:
    """§9: a cumulative column only when the pupil has results for that term.

    First-half sheets carry none at all — the photographed first-half card has
    no such columns. On a second-half sheet: none in first term, one in
    second, both plus the annual in third.
    """
    if half is not TermHalf.SECOND_HALF or not prior_terms:
        return []

    columns = [cumulative.TERM_COLUMN_LABELS[number] for number in prior_terms]
    # The annual figure needs more than one term to average over, which is
    # exactly third term.
    if len(prior_terms) > 1:
        columns.append("ANNUAL SCORES (AVE.)")
    return columns


async def _maxima(
    db: AsyncSession, actor: User, *, period_id: uuid.UUID, class_id: uuid.UUID
) -> dict[str, decimal.Decimal | None]:
    """The Marks Obtainable row the card prints at the top of the table."""
    row = await marks.applicable_maxima(
        db, actor, assessment_period_id=period_id, class_id=class_id
    )
    if row is None:
        return {}
    return {column: getattr(row, column) for column in marks.ALL_COLUMNS}


def _subject_lines(
    rows: Sequence[tuple[ResultEntry, Subject]],
    *,
    headings: dict[uuid.UUID, Subject],
    prior: dict[uuid.UUID, dict[TermNumber, decimal.Decimal]],
    prior_terms: Sequence[TermNumber],
) -> list[SubjectLine]:
    """One line per scored subject, with the group heading on its first row.

    R7 keeps a heading out of `class_subjects`, so the English row is drawn
    from its children rather than existing as a row of its own — the
    `group_name`/`group_size` pair tells the template where to start the
    spanning cell and how far to take it.
    """
    group_counts: dict[uuid.UUID, int] = {}
    for _, subject in rows:
        if subject.parent_subject_id:
            group_counts[subject.parent_subject_id] = (
                group_counts.get(subject.parent_subject_id, 0) + 1
            )

    seen: set[uuid.UUID] = set()
    lines: list[SubjectLine] = []
    for entry, subject in rows:
        parent = subject.parent_subject_id
        starts_group = bool(parent) and parent not in seen
        if parent:
            seen.add(parent)

        values = {
            column: getattr(entry, column)
            for column in (*marks.ALL_COLUMNS, "ca_test_total", "period_average")
        }
        by_term = prior.get(subject.id, {})
        cumulative_values: dict[str, decimal.Decimal | None] = {
            cumulative.TERM_COLUMN_LABELS[number]: by_term.get(number) for number in prior_terms
        }
        if len(prior_terms) > 1:
            annual = cumulative.annual_average(
                [*(by_term.get(number) for number in prior_terms), entry.period_average]
            )
            cumulative_values["ANNUAL SCORES (AVE.)"] = annual.value if annual else None

        lines.append(
            SubjectLine(
                subject_id=subject.id,
                name=subject.name.upper(),
                group_name=(
                    headings[parent].name.upper() if starts_group and parent in headings else None
                ),
                group_size=group_counts.get(parent, 0) if starts_group else 0,
                in_group=bool(parent),
                values=values,
                cumulative=cumulative_values,
                grade=entry.grade_letter,
            )
        )
    return lines


def _grand_total(
    lines: Sequence[SubjectLine], *, columns: Sequence[tuple[str, str]], cumulative: Sequence[str]
) -> dict[str, decimal.Decimal | None]:
    """R6: "the column-wise sum down the subject rows, excluding group headings".

    Headings are already excluded because they are not rows here (R7). A
    column with nothing in it stays empty rather than printing zero — §9 is
    explicit that an empty column is never zero-filled.
    """
    totals: dict[str, decimal.Decimal | None] = {}
    for key, _ in columns:
        present = [line.values.get(key) for line in lines if line.values.get(key) is not None]
        totals[key] = sum(present, start=decimal.Decimal(0)) if present else None
    for label in cumulative:
        present = [
            line.cumulative.get(label) for line in lines if line.cumulative.get(label) is not None
        ]
        totals[label] = sum(present, start=decimal.Decimal(0)) if present else None
    return totals


async def _key(
    db: AsyncSession, actor: User, rows: Sequence[tuple[ResultEntry, Subject]]
) -> list[tuple[str, str, str]]:
    """§9 item 6: the bands **in force for that report**, not today's.

    Read from the scale snapshotted on the rows at approval. A card reprinted
    a year later carries the key it was graded against, or the letters on it
    stop being explicable (§4.5).
    """
    scale_ids = {entry.grading_scale_id for entry, _ in rows if entry.grading_scale_id}
    scale_id = next(iter(scale_ids), None)

    if scale_id is None:
        # Not yet approved: the card is a preview, so the active scale is the
        # honest thing to print.
        scale = await db.scalar(
            scope.scoped_grading_scales(actor).where(GradingScale.is_active.is_(True))
        )
        scale_id = scale.id if scale else None
    if scale_id is None:
        return []

    bands = await all_of(
        db,
        scope.scoped_grade_bands(actor)
        .where(GradeBand.scale_id == scale_id)
        .order_by(GradeBand.sort_order),
    )
    # "(90 - 100)", as the card prints it. `:g` leaves a Decimal's trailing
    # zeros alone — unlike a float — so the bounds are normalised first.
    return [
        (
            band.letter,
            band.remark.upper(),
            f"({band.min_score.normalize():f} - {band.max_score.normalize():f})",
        )
        for band in bands
    ]


async def _narrative(
    db: AsyncSession, actor: User, *, pupil_id: uuid.UUID, term_id: uuid.UUID
) -> list[tuple[str, str | None, list[tuple[str, str, str | None]]]]:
    """The sixteen sections, grouped as §1.4 groups them on the page."""
    sections = await all_of(
        db,
        scope.scoped_narrative_sections(actor)
        .where(NarrativeSection.is_active.is_(True))
        .order_by(NarrativeSection.display_order),
    )
    bodies = {
        entry.section_id: entry.body
        for entry in await all_of(
            db,
            select(NarrativeEntry).where(
                NarrativeEntry.school_id == actor.school_id,
                NarrativeEntry.term_id == term_id,
                NarrativeEntry.pupil_id == pupil_id,
            ),
        )
    }

    grouped: list[tuple[str, str | None, list[tuple[str, str, str | None]]]] = []
    for section in sections:
        label = section.group_label
        # "A.english_language_arts" sits in block A; "B" is its own block.
        letter = section.code.split(".", 1)[0]
        item = (section.code, section.label, bodies.get(section.id))
        if grouped and grouped[-1][1] == label and grouped[-1][0] == letter:
            grouped[-1][2].append(item)
        else:
            grouped.append((letter, label, [item]))
    return grouped


def _return_date(term: Term) -> dt.date | None:
    """ "Please return this card to the School on ___ when next term begins".

    The card asks for a date and the schema holds none, so the term's end date
    is the closest honest answer and the template words it as the card does.
    """
    return term.ends_on


def _next_version(object_key: str) -> int:
    """R13 keeps the previous PDF: a new one gets the next version number."""
    stem = object_key.rsplit("/", 1)[-1].removesuffix(".pdf")
    _, _, suffix = stem.rpartition("-")
    try:
        return int(suffix) + 1
    except ValueError:  # pragma: no cover - a key we did not write
        return 1
