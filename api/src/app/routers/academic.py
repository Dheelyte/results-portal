"""Admin setup: sessions, terms, half terms and column maxima (§7).

Translation only — HTTP in, service call, HTTP out. Every rule is in
`services/academic.py` and `services/marks.py` (CLAUDE.md rule 2), and no
query here touches a model directly (rule 4, §5.2).

§5.2's first row gives this whole surface to the admin alone: "Sessions, terms,
assessment periods, classes, subjects — admin ✅, everyone else —". The
capability is declared in each signature rather than checked in each body.
"""

import uuid

from fastapi import APIRouter, Response, status

from app.auth.dependencies import Context, DbSession
from app.authz.dependencies import AcademicStructureAdmin, AssessmentConfigAdmin
from app.schemas.academic import (
    AcademicSessionCreate,
    AcademicSessionRead,
    AssessmentPeriodRead,
    AssessmentPeriodSave,
    TermCreate,
    TermRead,
    TermUpdate,
)
from app.schemas.marks import MarksObtainableRead, MarksObtainableSave
from app.services import academic as academic_service
from app.services import marks as marks_service

router = APIRouter(tags=["admin: academic structure"])


# ---------------------------------------------------------------------------
# Academic sessions
# ---------------------------------------------------------------------------


@router.get("/sessions", response_model=list[AcademicSessionRead], summary="List sessions")
async def list_sessions(db: DbSession, admin: AcademicStructureAdmin) -> list[AcademicSessionRead]:
    records = await academic_service.list_sessions(db, admin)
    return [AcademicSessionRead.model_validate(record) for record in records]


@router.post(
    "/sessions",
    response_model=AcademicSessionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a session",
)
async def create_session(
    payload: AcademicSessionCreate,
    db: DbSession,
    admin: AcademicStructureAdmin,
    context: Context,
) -> AcademicSessionRead:
    record = await academic_service.create_session(
        db,
        admin,
        name=payload.name,
        starts_on=payload.starts_on,
        ends_on=payload.ends_on,
        is_current=payload.is_current,
        ip_address=context.ip_address,
        user_agent=context.user_agent,
    )
    return AcademicSessionRead.model_validate(record)


@router.post(
    "/sessions/{session_id}/current",
    response_model=AcademicSessionRead,
    summary="Make a session the current one",
)
async def make_session_current(
    session_id: uuid.UUID,
    db: DbSession,
    admin: AcademicStructureAdmin,
    context: Context,
) -> AcademicSessionRead:
    """Switch the school into another academic year.

    Not in §7's list, which has only GET and POST for sessions. §2.3 requires
    the active session to be set in the platform rather than derived from the
    clock, so the verb has to exist somewhere (docs/DECISIONS.md D37).
    """
    record = await academic_service.make_session_current(
        db,
        admin,
        session_id,
        ip_address=context.ip_address,
        user_agent=context.user_agent,
    )
    return AcademicSessionRead.model_validate(record)


# ---------------------------------------------------------------------------
# Terms
# ---------------------------------------------------------------------------


@router.get("/terms", response_model=list[TermRead], summary="List terms")
async def list_terms(
    db: DbSession,
    admin: AcademicStructureAdmin,
    academic_session_id: uuid.UUID | None = None,
) -> list[TermRead]:
    records = await academic_service.list_terms(db, admin, academic_session_id=academic_session_id)
    return [TermRead.model_validate(record) for record in records]


@router.post(
    "/terms",
    response_model=TermRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a term and its two half terms",
)
async def create_term(
    payload: TermCreate,
    db: DbSession,
    admin: AcademicStructureAdmin,
    context: Context,
) -> TermRead:
    """Create a term. Both assessment periods are created with it.

    §1.1 states the two halves as a fact about the domain, not an option, so a
    term can never exist with nowhere to enter scores.
    """
    record = await academic_service.create_term(
        db,
        admin,
        academic_session_id=payload.academic_session_id,
        number=payload.number,
        starts_on=payload.starts_on,
        ends_on=payload.ends_on,
        times_school_opened=payload.times_school_opened,
        next_resumption_on=payload.next_resumption_on,
        card_return_on=payload.card_return_on,
        is_current=payload.is_current,
        ip_address=context.ip_address,
        user_agent=context.user_agent,
    )
    return TermRead.model_validate(record)


@router.patch("/terms/{term_id}", response_model=TermRead, summary="Update a term")
async def update_term(
    term_id: uuid.UUID,
    payload: TermUpdate,
    db: DbSession,
    admin: AcademicStructureAdmin,
    context: Context,
) -> TermRead:
    """Change a term's dates or its calendar figures.

    `times_school_opened` is why this exists: R9 measures every pupil's
    attendance against it and it is rarely known on the day a term is created.
    """
    record = await academic_service.update_term(
        db,
        admin,
        term_id,
        changes=payload.model_dump(exclude_unset=True),
        ip_address=context.ip_address,
        user_agent=context.user_agent,
    )
    return TermRead.model_validate(record)


@router.post(
    "/terms/{term_id}/current", response_model=TermRead, summary="Make a term the current one"
)
async def make_term_current(
    term_id: uuid.UUID,
    db: DbSession,
    admin: AcademicStructureAdmin,
    context: Context,
) -> TermRead:
    record = await academic_service.make_term_current(
        db, admin, term_id, ip_address=context.ip_address, user_agent=context.user_agent
    )
    return TermRead.model_validate(record)


# ---------------------------------------------------------------------------
# Assessment periods
# ---------------------------------------------------------------------------


@router.get(
    "/terms/{term_id}/assessment-periods",
    response_model=list[AssessmentPeriodRead],
    summary="The term's two half terms",
)
async def list_assessment_periods(
    term_id: uuid.UUID, db: DbSession, admin: AcademicStructureAdmin
) -> list[AssessmentPeriodRead]:
    records = await academic_service.list_assessment_periods(db, admin, term_id)
    return [AssessmentPeriodRead.model_validate(record) for record in records]


@router.post(
    "/terms/{term_id}/assessment-periods",
    response_model=AssessmentPeriodRead,
    summary="Set a half term's window",
)
async def save_assessment_period(
    term_id: uuid.UUID,
    payload: AssessmentPeriodSave,
    db: DbSession,
    admin: AcademicStructureAdmin,
    context: Context,
    response: Response,
) -> AssessmentPeriodRead:
    """Set the opening and closing dates of one half term.

    An upsert keyed on `half`: `POST /terms` already created both rows, so the
    only thing this can mean is "these are the dates". 201 if a row had to be
    created, 200 if an existing one was updated.
    """
    record, created = await academic_service.save_assessment_period(
        db,
        admin,
        term_id,
        half=payload.half,
        opens_on=payload.opens_on,
        closes_on=payload.closes_on,
        ip_address=context.ip_address,
        user_agent=context.user_agent,
    )
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return AssessmentPeriodRead.model_validate(record)


# ---------------------------------------------------------------------------
# Marks obtainable
# ---------------------------------------------------------------------------


@router.get(
    "/assessment-periods/{assessment_period_id}/marks-obtainable",
    response_model=list[MarksObtainableRead],
    summary="A sheet's column maxima",
)
async def list_marks_obtainable(
    assessment_period_id: uuid.UUID, db: DbSession, admin: AssessmentConfigAdmin
) -> list[MarksObtainableRead]:
    """The school-wide row first, then any per-class overrides."""
    records = await marks_service.list_marks_obtainable(db, admin, assessment_period_id)
    return [MarksObtainableRead.model_validate(record) for record in records]


@router.put(
    "/assessment-periods/{assessment_period_id}/marks-obtainable",
    response_model=MarksObtainableRead,
    summary="Set a sheet's column maxima",
)
async def save_marks_obtainable(
    assessment_period_id: uuid.UUID,
    payload: MarksObtainableSave,
    db: DbSession,
    admin: AssessmentConfigAdmin,
    context: Context,
) -> MarksObtainableRead:
    """Set what each column on one sheet is out of.

    The card's "Marks Obtainable" row. R1 validates every score against these
    numbers and names the applicable maximum when it refuses one, so until
    they are set no score entry is really being checked.

    **N2 is unanswered.** The row is blank on both photographed cards, so only
    the school can supply these figures; nothing in the system defaults them.
    """
    record = await marks_service.save_marks_obtainable(
        db,
        admin,
        assessment_period_id,
        values=payload.column_values(),
        class_id=payload.class_id,
        ip_address=context.ip_address,
        user_agent=context.user_agent,
    )
    return MarksObtainableRead.model_validate(record)
