"""Score entry (§7's teacher block, §8.1's grid).

Three endpoints, and the middle one is the busiest write in the system:

    GET /my/assignments?term_id=
    GET /class-subjects/{id}/entries?assessment_period_id=
    PUT /class-subjects/{id}/entries

Thin, like every router here: the rules are R1-R4, R7 and R14 and they live in
`services/results.py`. What this file does own is the shape of the response —
the grid renders `columns` as given rather than deciding which of §8.1's two
layouts applies, so the first-half and second-half sheets are one component.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.auth.dependencies import Context, DbSession
from app.authz.dependencies import ScoreEntrant
from app.models import ResultEntry
from app.schemas.results import (
    AssignmentRead,
    EntriesSave,
    EntryRead,
    GradeRead,
    MaximaRead,
    PeriodSummary,
    SheetRead,
    TermSummary,
    WorkloadRead,
)
from app.services import results
from app.services.marks import ALL_COLUMNS

router = APIRouter(tags=["teacher: score entry"])


def _row_read(row: results.SheetRow) -> EntryRead:
    entry: ResultEntry | None = row.entry
    scores = (
        {column: getattr(entry, column) for column in (*ALL_COLUMNS, "ca_test_total")}
        if entry is not None
        else {}
    )
    return EntryRead(
        pupil_id=row.pupil.id,
        admission_number=row.pupil.admission_number,
        first_name=row.pupil.first_name,
        middle_name=row.pupil.middle_name,
        last_name=row.pupil.last_name,
        period_average=entry.period_average if entry else None,
        grade=(
            GradeRead(letter=row.grade.letter, remark=row.grade.remark)
            if row.grade is not None
            else None
        ),
        grade_letter=entry.grade_letter if entry else None,
        updated_at=entry.updated_at if entry else None,
        **scores,
    )


def _sheet_read(sheet: results.Sheet) -> SheetRead:
    maxima = None
    if sheet.maxima is not None:
        maxima = MaximaRead.model_validate(sheet.maxima)
        maxima.is_class_override = sheet.maxima.class_id is not None

    return SheetRead(
        class_subject_id=sheet.class_subject.id,
        class_id=sheet.klass.id,
        class_name=sheet.klass.name,
        subject_id=sheet.subject.id,
        subject_name=sheet.subject.name,
        assessment_period_id=sheet.period.id,
        term_id=sheet.term.id,
        half=sheet.period.half,
        columns=list(sheet.columns),
        maxima=maxima,
        maxima_configured=sheet.configured,
        state=sheet.state,
        editable=sheet.editable,
        rows=[_row_read(row) for row in sheet.rows],
    )


@router.get("/my/assignments", response_model=WorkloadRead)
async def my_assignments(
    db: DbSession,
    teacher: ScoreEntrant,
    term_id: Annotated[
        uuid.UUID | None,
        Query(description="Defaults to the current term, which §2.3 sets in the platform."),
    ] = None,
) -> WorkloadRead:
    """Every sheet this teacher is responsible for, with its progress.

    Carries the term and its two assessment periods as well, because §5.2
    gives the calendar to the admin alone and the grid cannot be opened
    without those ids (docs/DECISIONS.md D51).
    """
    work = await results.my_work(db, teacher, term_id=term_id)

    return WorkloadRead(
        term=TermSummary(
            id=work.term.id,
            number=work.term.number.value,
            academic_session_name=work.academic_session_name,
            starts_on=work.term.starts_on,
            ends_on=work.term.ends_on,
            times_school_opened=work.term.times_school_opened,
        ),
        periods=[
            PeriodSummary(
                id=period.id,
                half=period.half,
                opens_on=period.opens_on,
                closes_on=period.closes_on,
            )
            for period in work.periods
        ],
        assignments=[AssignmentRead(**vars(assignment)) for assignment in work.assignments],
    )


@router.get("/class-subjects/{class_subject_id}/entries", response_model=SheetRead)
async def read_entries(
    db: DbSession,
    teacher: ScoreEntrant,
    class_subject_id: uuid.UUID,
    assessment_period_id: Annotated[uuid.UUID, Query(description="Which half's sheet.")],
) -> SheetRead:
    """The grid: the class roll, the scores so far, and the column maxima."""
    sheet = await results.load_sheet(
        db,
        teacher,
        class_subject_id=class_subject_id,
        assessment_period_id=assessment_period_id,
    )
    return _sheet_read(sheet)


@router.put("/class-subjects/{class_subject_id}/entries", response_model=SheetRead)
async def save_entries(
    db: DbSession,
    teacher: ScoreEntrant,
    context: Context,
    class_subject_id: uuid.UUID,
    payload: EntriesSave,
) -> SheetRead:
    """Save a set of score rows, applying all of them or none (§7).

    Returns the whole sheet rather than an acknowledgement, so the grid's
    computed columns — CA Test Total, the period average and the grade — come
    back from the database that generated them instead of being guessed at in
    the browser.
    """
    sheet = await results.save_entries(
        db,
        teacher,
        class_subject_id=class_subject_id,
        assessment_period_id=payload.assessment_period_id,
        rows=[
            results.Row(pupil_id=row.pupil_id, scores=row.provided_scores()) for row in payload.rows
        ],
        ip_address=context.ip_address,
        user_agent=context.user_agent,
    )
    return _sheet_read(sheet)
