"""What a parent may read (§7's parent block, §6 R12).

    GET /my/children
    GET /my/children/{pupil_id}/reports
    GET /my/children/{pupil_id}/reports/{term_id}

Milestone 10's criterion is that a withheld pupil's parent sees R12's message,
so these three exist now. §8.5's screens, the PDF link and the
acknowledgement are milestone 12 (docs/DECISIONS.md D73).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.auth.dependencies import Context, DbSession
from app.authz.dependencies import ParentReader
from app.models import TermHalf
from app.schemas.publication import (
    AvailabilityRead,
    CardLineRead,
    ChildRead,
    ChildReportRead,
    ChildReportsRead,
    ParentCardRead,
)
from app.services import parents, reportcard

router = APIRouter(tags=["parent"])


@router.get("/my/children", response_model=list[ChildRead])
async def my_children(db: DbSession, parent: ParentReader) -> list[ChildRead]:
    """The caller's own children — §10: a parent may have several, in
    different classes."""
    return [ChildRead(**vars(child)) for child in await parents.children(db, parent)]


@router.get("/my/children/{pupil_id}/reports", response_model=ChildReportsRead)
async def my_childs_reports(
    db: DbSession, parent: ParentReader, pupil_id: uuid.UUID
) -> ChildReportsRead:
    """Each term of the current session, and whether its result is available.

    Unpublished terms are listed as unavailable rather than hidden: a parent
    looking for a result needs to see that the term exists and the result is
    not there yet. R12's sentence is the whole explanation, deliberately.
    """
    pupil, availability = await parents.reports(db, parent, pupil_id=pupil_id)
    return ChildReportsRead(
        pupil_id=pupil.id,
        first_name=pupil.first_name,
        last_name=pupil.last_name,
        terms=[AvailabilityRead(**vars(term)) for term in availability],
    )


@router.get("/my/children/{pupil_id}/reports/{term_id}", response_model=ChildReportRead)
async def my_childs_report(
    db: DbSession,
    parent: ParentReader,
    pupil_id: uuid.UUID,
    term_id: uuid.UUID,
    half: Annotated[TermHalf, Query(description="Which half term's sheet.")] = TermHalf.SECOND_HALF,
) -> ChildReportRead:
    """One term's card, or R12's sentence.

    A 200 with the message rather than a 404: "not yet available" is a normal
    answer to a reasonable question, and the single most common thing a parent
    will do in this system is open a result the evening before it is released.
    A 403 would confirm the report exists, which R12 is careful not to do.

    The card is assembled by `services/reportcard.py` — the same function the
    PDF renders from, so the page and the download cannot disagree.
    """
    pupil, term, report, message = await parents.report_or_message(
        db, parent, pupil_id=pupil_id, term_id=term_id
    )

    card = None
    if report is not None:
        card = _card_read(
            await reportcard.build(db, parent, pupil_id=pupil_id, term_id=term_id, half=half)
        )

    return ChildReportRead(
        pupil_id=pupil.id,
        term_id=term.id,
        term_label=parents.TERM_NAMES.get(term.number, term.number.value),
        available=report is not None,
        published_at=report.published_at if report else None,
        acknowledged_at=report.parent_acknowledged_at if report else None,
        message=message,
        card=card,
    )


def _card_read(card: reportcard.Card) -> ParentCardRead:
    """The assembled card as a response model, field for field.

    Written out rather than reflected, so adding a field to the card is a
    deliberate act here too — this is the boundary a parent's data crosses.
    """
    return ParentCardRead(
        title=card.title,
        subtitle=card.subtitle,
        school_name=card.school_name,
        date=card.date,
        pupil_name=card.pupil_name,
        admission_number=card.admission_number,
        overall_percentage=card.overall_percentage,
        position_text=card.position_text,
        class_name=card.class_name,
        session_name=card.session_name,
        no_in_class=card.no_in_class,
        house_name=card.house_name,
        times_school_opened=card.times_school_opened,
        times_present=card.times_present,
        times_absent=card.times_absent,
        times_late=card.times_late,
        height_start_m=card.height_start_m,
        height_end_m=card.height_end_m,
        weight_start_kg=card.weight_start_kg,
        weight_end_kg=card.weight_end_kg,
        columns=card.columns,
        cumulative_columns=card.cumulative_columns,
        maxima=card.maxima,
        lines=[
            CardLineRead(
                subject_name=line.name,
                group_name=line.group_name,
                group_size=line.group_size,
                in_group=line.in_group,
                values=line.values,
                cumulative=line.cumulative,
                grade=line.grade,
            )
            for line in card.lines
        ],
        grand_total=card.grand_total,
        key=card.key,
        narrative_groups=card.narrative_groups,
        class_teacher_comment=card.class_teacher_comment,
        head_teacher_remark=card.head_teacher_remark,
        promotion_decision=card.promotion_decision,
        return_date=card.return_date,
    )


@router.post(
    "/my/children/{pupil_id}/reports/{term_id}/acknowledge",
    response_model=ChildReportRead,
)
async def acknowledge(
    db: DbSession,
    parent: ParentReader,
    context: Context,
    pupil_id: uuid.UUID,
    term_id: uuid.UUID,
) -> ChildReportRead:
    """A8: this replaces the signature and the physical return of the card.

    Idempotent — a parent who taps twice, or opens the page on a phone and
    again on a laptop, has acknowledged once, and the first moment stands.
    """
    await parents.acknowledge(
        db,
        parent,
        pupil_id=pupil_id,
        term_id=term_id,
        ip_address=context.ip_address,
        user_agent=context.user_agent,
    )
    # The whole card back, so the page that posted this can re-render from
    # one response rather than fetching again on a 3G connection (§8.5).
    return await my_childs_report(db, parent, pupil_id=pupil_id, term_id=term_id)
