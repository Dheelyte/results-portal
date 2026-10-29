"""Head teacher review (§7's review block, §8.4).

    GET  /review/queue?term_id=
    GET  /classes/{id}/review?term_id=
    PUT  /classes/{id}/remarks?term_id=
    POST /classes/{id}/approve?term_id=
    POST /classes/{id}/return?term_id=    { note }

The rules — R4's live-versus-snapshot grade, R11's never-computed position,
R14's transitions and §4.5's freeze — are in `services/review.py`.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.auth.dependencies import Context, DbSession
from app.authz.dependencies import ClassReviewer, RemarkWriter
from app.schemas.review import (
    ApprovalRead,
    CardAttendance,
    CardGrowth,
    CardHalf,
    CardPassage,
    CardRead,
    ClassReviewRead,
    QueueEntryRead,
    RemarksSave,
    ReturnRequest,
    SnapshotRead,
    SubjectRowRead,
)
from app.services import review as review_service
from app.services.review import RemarkInput

router = APIRouter(tags=["head teacher: review"])

TermQuery = Annotated[uuid.UUID, Query(description="Which term to review.")]
OptionalTermQuery = Annotated[
    uuid.UUID | None,
    Query(description="Defaults to the current term, which §2.3 sets in the platform."),
]


def _card(card: review_service.PupilCard, *, times_school_opened: int | None) -> CardRead:
    report = card.report
    attendance = card.attendance
    growth = card.growth

    return CardRead(
        pupil_id=card.pupil.id,
        admission_number=card.pupil.admission_number,
        first_name=card.pupil.first_name,
        middle_name=card.pupil.middle_name,
        last_name=card.pupil.last_name,
        house_name=card.house_name,
        no_in_class=report.no_in_class if report else None,
        subjects=[
            SubjectRowRead(
                class_subject_id=row.class_subject_id,
                subject_id=row.subject_id,
                subject_name=row.subject_name,
                is_group=row.is_group,
                display_order=row.display_order,
                parent_subject_id=row.parent_subject_id,
                parent_subject_name=row.parent_subject_name,
                halves={half: CardHalf(**values) for half, values in row.halves.items() if values},
            )
            for row in card.subjects
        ],
        narrative=[
            CardPassage(
                section_id=section.id,
                code=section.code,
                label=section.label,
                group_label=section.group_label,
                body=body,
            )
            for section, body in card.narrative
        ],
        attendance=(
            CardAttendance(
                times_school_opened=times_school_opened,
                times_present=attendance.times_present,
                times_absent=attendance.times_absent,
                times_late=attendance.times_late,
            )
            if attendance is not None
            else None
        ),
        growth=(
            CardGrowth(
                height_start_m=growth.height_start_m,
                height_end_m=growth.height_end_m,
                weight_start_kg=growth.weight_start_kg,
                weight_end_kg=growth.weight_end_kg,
            )
            if growth is not None
            else None
        ),
        class_teacher_comment=report.class_teacher_comment if report else None,
        overall_percentage=report.overall_percentage if report else None,
        head_teacher_remark=report.head_teacher_remark if report else None,
        position_text=report.position_text if report else None,
        promotion_decision=report.promotion_decision if report else None,
    )


def _read(review: review_service.ClassReview) -> ClassReviewRead:
    return ClassReviewRead(
        class_id=review.klass.id,
        class_name=review.klass.name,
        term_id=review.term.id,
        term_number=review.term.number.value,
        term_label=review.term_label,
        state=review.state,
        return_note=review.return_note,
        promotion_applies=review.promotion_applies,
        cards=[
            _card(card, times_school_opened=review.term.times_school_opened)
            for card in review.cards
        ],
    )


@router.get("/review/queue", response_model=list[QueueEntryRead])
async def read_queue(
    db: DbSession, head: ClassReviewer, term_id: OptionalTermQuery = None
) -> list[QueueEntryRead]:
    """Classes submitted for review, longest-waiting first."""
    return [
        QueueEntryRead(**vars(entry))
        for entry in await review_service.queue(db, head, term_id=term_id)
    ]


@router.get("/classes/{class_id}/review", response_model=ClassReviewRead)
async def read_class_review(
    db: DbSession, head: ClassReviewer, class_id: uuid.UUID, term_id: TermQuery
) -> ClassReviewRead:
    """Every pupil's card as the parent will see it (§8.4)."""
    return _read(await review_service.class_review(db, head, class_id=class_id, term_id=term_id))


@router.put("/classes/{class_id}/remarks", response_model=ClassReviewRead)
async def save_remarks(
    db: DbSession,
    head: RemarkWriter,
    context: Context,
    class_id: uuid.UUID,
    term_id: TermQuery,
    payload: RemarksSave,
) -> ClassReviewRead:
    """The remark, the position text and — in third term — the promotion."""
    return _read(
        await review_service.save_remarks(
            db,
            head,
            class_id=class_id,
            term_id=term_id,
            rows=[
                RemarkInput(
                    pupil_id=row.pupil_id,
                    head_teacher_remark=row.head_teacher_remark,
                    position_text=row.position_text,
                    promotion_decision=row.promotion_decision,
                )
                for row in payload.rows
            ],
            ip_address=context.ip_address,
            user_agent=context.user_agent,
        )
    )


@router.post("/classes/{class_id}/approve", response_model=ApprovalRead)
async def approve_class(
    db: DbSession,
    head: ClassReviewer,
    context: Context,
    class_id: uuid.UUID,
    term_id: TermQuery,
) -> ApprovalRead:
    """Approve the class, freezing every grade against the active scale.

    §12's criterion for this milestone. The snapshot comes back in the
    response rather than being left implicit: this is the one irreversible
    step in the workflow, and the head teacher should be able to see that it
    wrote what it says it wrote.
    """
    review, snapshot = await review_service.approve(
        db,
        head,
        class_id=class_id,
        term_id=term_id,
        ip_address=context.ip_address,
        user_agent=context.user_agent,
    )
    return ApprovalRead(
        review=_read(review),
        snapshot=SnapshotRead(
            grading_scale_id=snapshot.scale_id,
            grading_scale_name=snapshot.scale_name,
            rows=snapshot.rows,
            graded=snapshot.graded,
            ungraded=snapshot.ungraded,
            reports=snapshot.reports,
        ),
    )


@router.post("/classes/{class_id}/return", response_model=ClassReviewRead)
async def return_class(
    db: DbSession,
    head: ClassReviewer,
    context: Context,
    class_id: uuid.UUID,
    term_id: TermQuery,
    payload: ReturnRequest,
) -> ClassReviewRead:
    """Send the class back with a note, which is required (R10's lesson)."""
    return _read(
        await review_service.return_class(
            db,
            head,
            class_id=class_id,
            term_id=term_id,
            note=payload.note,
            ip_address=context.ip_address,
            user_agent=context.user_agent,
        )
    )
