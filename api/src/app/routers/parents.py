"""What a parent may read (§7's parent block, §6 R12).

    GET /my/children
    GET /my/children/{pupil_id}/reports
    GET /my/children/{pupil_id}/reports/{term_id}

Milestone 10's criterion is that a withheld pupil's parent sees R12's message,
so these three exist now. §8.5's screens, the PDF link and the
acknowledgement are milestone 12 (docs/DECISIONS.md D73).
"""

import uuid

from fastapi import APIRouter

from app.auth.dependencies import DbSession
from app.authz.dependencies import ParentReader
from app.schemas.publication import (
    AvailabilityRead,
    ChildRead,
    ChildReportsRead,
)
from app.services import parents

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


@router.get("/my/children/{pupil_id}/reports/{term_id}", response_model=AvailabilityRead)
async def my_childs_report(
    db: DbSession, parent: ParentReader, pupil_id: uuid.UUID, term_id: uuid.UUID
) -> AvailabilityRead:
    """One term's availability, or R12's sentence.

    A 200 with the message rather than a 404: "not yet available" is a normal
    answer to a reasonable question, and the single most common thing a parent
    will do in this system is open a result the evening before it is released.
    A 403 would confirm the report exists, which R12 is careful not to do.

    The card itself arrives in milestone 12 with §8.5's screens; what this
    settles now is whether it may be opened at all.
    """
    pupil, term, report, message = await parents.report_or_message(
        db, parent, pupil_id=pupil_id, term_id=term_id
    )
    return AvailabilityRead(
        term_id=term.id,
        term_label=parents.TERM_NAMES.get(term.number, term.number.value),
        available=report is not None,
        published_at=report.published_at if report else None,
        acknowledged_at=report.parent_acknowledged_at if report else None,
        message=message,
    )
