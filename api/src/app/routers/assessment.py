"""Admin setup: grading scales, narrative sections and the phrase bank (§7).

§5.2's third row: "Grading scale, marks obtainable, narrative sections,
comment bank — admin ✅". Marks obtainable sits with the assessment periods in
`routers/academic.py`; the rest is here.
"""

import uuid

from fastapi import APIRouter, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import Context, DbSession
from app.authz.dependencies import AssessmentConfigAdmin, UserAdmin
from app.models import GradingScale, User
from app.schemas.grading import (
    GradeBandRead,
    GradingScaleCreate,
    GradingScaleRead,
)
from app.schemas.narrative import (
    CommentCreate,
    CommentRead,
    NarrativeAssignmentRead,
    NarrativeAssignmentsSave,
    NarrativeSectionRead,
    NarrativeSectionsSave,
)
from app.services import grading as grading_service
from app.services import narrative as narrative_service
from app.services.grading import BandInput
from app.services.narrative import SectionInput

router = APIRouter(tags=["admin: assessment configuration"])


async def _scale_read(db: AsyncSession, admin: User, scale: GradingScale) -> GradingScaleRead:
    """A scale with its bands, highest band first — the card's key order."""
    bands = await grading_service.bands_of(db, admin, scale.id)
    read = GradingScaleRead.model_validate(scale)
    read.bands = [GradeBandRead.model_validate(band) for band in bands]
    return read


# ---------------------------------------------------------------------------
# Grading scales
# ---------------------------------------------------------------------------


@router.get("/grading-scales", response_model=list[GradingScaleRead], summary="List grading scales")
async def list_grading_scales(
    db: DbSession, admin: AssessmentConfigAdmin
) -> list[GradingScaleRead]:
    """Every scale the school has used, active one first.

    Old scales are kept because §4.5 requires it: a card printed last term
    must still agree with the portal, and its grades were resolved from the
    scale in force then.
    """
    scales = await grading_service.list_scales(db, admin)
    return [await _scale_read(db, admin, scale) for scale in scales]


@router.post(
    "/grading-scales",
    response_model=GradingScaleRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a grading scale",
)
async def create_grading_scale(
    payload: GradingScaleCreate,
    db: DbSession,
    admin: AssessmentConfigAdmin,
    context: Context,
) -> GradingScaleRead:
    """Create a new version of the grading scale.

    Bands must not overlap and must cover every mark from 0 to 100, so that
    every average resolves to exactly one grade.

    **N1 is unanswered**: the card prints seven bands with plus grades, the
    September requirements described six without. The school's answer arrives
    as a new scale here, never as an edit to an existing one — grades already
    snapshotted onto approved results are not touched (CLAUDE.md rule 6).
    """
    scale = await grading_service.create_scale(
        db,
        admin,
        name=payload.name,
        effective_from=payload.effective_from,
        bands=[
            BandInput(
                letter=band.letter,
                remark=band.remark,
                min_score=band.min_score,
                max_score=band.max_score,
            )
            for band in payload.bands
        ],
        activate=payload.activate,
        ip_address=context.ip_address,
        user_agent=context.user_agent,
    )
    return await _scale_read(db, admin, scale)


@router.post(
    "/grading-scales/{scale_id}/activate",
    response_model=GradingScaleRead,
    summary="Make a grading scale active",
)
async def activate_grading_scale(
    scale_id: uuid.UUID,
    db: DbSession,
    admin: AssessmentConfigAdmin,
    context: Context,
) -> GradingScaleRead:
    """Switch which scale new grades resolve from.

    Not in §7's list. Switching between versions is the point of versioning
    them, and answering N1 means saying "use this one from now on"
    (docs/DECISIONS.md D37).
    """
    scale = await grading_service.activate_scale(
        db, admin, scale_id, ip_address=context.ip_address, user_agent=context.user_agent
    )
    return await _scale_read(db, admin, scale)


# ---------------------------------------------------------------------------
# Narrative sections
# ---------------------------------------------------------------------------


@router.get(
    "/narrative-sections",
    response_model=list[NarrativeSectionRead],
    summary="The card's narrative sections",
)
async def list_narrative_sections(
    db: DbSession, admin: AssessmentConfigAdmin, include_inactive: bool = True
) -> list[NarrativeSectionRead]:
    """The sixteen sections of §1.4, in card order.

    Seven curriculum areas under "Area of Curriculum", then B through J.
    """
    records = await narrative_service.list_sections(db, admin, include_inactive=include_inactive)
    return [NarrativeSectionRead.model_validate(record) for record in records]


@router.put(
    "/narrative-sections",
    response_model=list[NarrativeSectionRead],
    summary="Edit the narrative sections",
)
async def save_narrative_sections(
    payload: NarrativeSectionsSave,
    db: DbSession,
    admin: AssessmentConfigAdmin,
    context: Context,
) -> list[NarrativeSectionRead]:
    """Relabel, reorder, add or retire sections, keyed on `code`.

    A section is retired with `is_active = false`, never deleted: a term's
    written passages point at it and last term's card must keep saying what it
    said. N7 may yet reduce the sixteen, and this is how.
    """
    records = await narrative_service.save_sections(
        db,
        admin,
        sections=[
            SectionInput(
                code=section.code,
                label=section.label,
                group_label=section.group_label,
                display_order=section.display_order,
                is_active=section.is_active,
            )
            for section in payload.sections
        ],
        ip_address=context.ip_address,
        user_agent=context.user_agent,
    )
    return [NarrativeSectionRead.model_validate(record) for record in records]


@router.get(
    "/classes/{class_id}/narrative-assignments",
    response_model=list[NarrativeAssignmentRead],
    summary="Who writes which section for this class",
)
async def list_narrative_assignments(
    class_id: uuid.UUID,
    db: DbSession,
    admin: UserAdmin,
    academic_session_id: uuid.UUID | None = None,
) -> list[NarrativeAssignmentRead]:
    """Only the explicit assignments.

    A section with no row here is written by the class teacher — that is the
    default by D15, not an omission, which is why the list is usually short.
    """
    records = await narrative_service.list_assignments(
        db, admin, class_id, academic_session_id=academic_session_id
    )
    return [NarrativeAssignmentRead.model_validate(record) for record in records]


@router.put(
    "/classes/{class_id}/narrative-assignments",
    response_model=list[NarrativeAssignmentRead],
    summary="Assign narrative sections to teachers",
)
async def set_narrative_assignments(
    class_id: uuid.UUID,
    payload: NarrativeAssignmentsSave,
    db: DbSession,
    admin: UserAdmin,
    context: Context,
) -> list[NarrativeAssignmentRead]:
    """Hand named sections of this class's card to named teachers (B1, D15).

    A specialist writes their own curriculum area; the class teacher writes
    everything else. A `teacher_user_id` of null clears an assignment, which
    hands that section back to the class teacher.

    Not in §7's list, which predates B1 being answered (docs/DECISIONS.md
    D37).
    """
    records = await narrative_service.set_assignments(
        db,
        admin,
        class_id,
        assignments={
            assignment.section_id: assignment.teacher_user_id for assignment in payload.assignments
        },
        academic_session_id=payload.academic_session_id,
        ip_address=context.ip_address,
        user_agent=context.user_agent,
    )
    return [NarrativeAssignmentRead.model_validate(record) for record in records]


# ---------------------------------------------------------------------------
# The phrase bank
# ---------------------------------------------------------------------------


@router.get("/comment-bank", response_model=list[CommentRead], summary="List phrases")
async def list_comments(
    db: DbSession,
    admin: AssessmentConfigAdmin,
    scope: str | None = Query(
        default=None,
        max_length=60,
        description="A narrative section code, 'class_teacher' or 'head_teacher'.",
    ),
    include_inactive: bool = True,
) -> list[CommentRead]:
    records = await narrative_service.list_comments(
        db, admin, comment_scope=scope, include_inactive=include_inactive
    )
    return [CommentRead.model_validate(record) for record in records]


@router.post(
    "/comment-bank",
    response_model=CommentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a phrase",
)
async def create_comment(
    payload: CommentCreate,
    db: DbSession,
    admin: AssessmentConfigAdmin,
    context: Context,
) -> CommentRead:
    """Add a phrase, scoped to one section or to a footer comment.

    §4.6 treats this as core, not optional: a class of thirty needs 480
    written passages a term from one class teacher, and without a phrase bank
    this is the feature that gets abandoned first.
    """
    record = await narrative_service.create_comment(
        db,
        admin,
        comment_scope=payload.scope,
        text=payload.text,
        ip_address=context.ip_address,
        user_agent=context.user_agent,
    )
    return CommentRead.model_validate(record)
