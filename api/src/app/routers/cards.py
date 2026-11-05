"""The report card PDF (§7, §9).

    GET /api/v1/my/children/{pupil_id}/reports/{term_id}/pdf   302 → signed URL
    GET /api/v1/pupils/{pupil_id}/card                          302 → signed URL
    GET /reports/download/{token}                               the file

The download route is **deliberately outside `/api/v1` and deliberately
unauthenticated**. The signed token is the authority: that is what makes the
link usable by a browser's download manager, a print dialog and a PDF viewer,
none of which carry an Authorization header. It is also why the token lasts
five minutes and why a guessed key gets nothing (§9).

Mounting it outside the versioned prefix keeps it out of
`test_route_coverage.py`'s capability scan by construction rather than by
exemption — and `test_cards.py` asserts the scan's rule still holds for
everything that is inside.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status
from fastapi.responses import RedirectResponse

from app.auth.dependencies import DbSession
from app.authz.dependencies import ParentReader, Publisher
from app.models import TermHalf
from app.services import cards

router = APIRouter(tags=["report card"])
download_router = APIRouter(tags=["report card"])

HalfQuery = Annotated[TermHalf, Query(description="Which half term's sheet.")]
TermQuery = Annotated[uuid.UUID, Query(description="Which term.")]

# §7: "302 → signed URL, 5 min TTL".
DOWNLOAD_PATH = "/reports/download"


@router.get(
    "/my/children/{pupil_id}/reports/{term_id}/pdf",
    status_code=status.HTTP_302_FOUND,
    response_class=RedirectResponse,
)
async def my_childs_card(
    db: DbSession,
    parent: ParentReader,
    pupil_id: uuid.UUID,
    term_id: uuid.UUID,
    half: HalfQuery = TermHalf.SECOND_HALF,
) -> RedirectResponse:
    """A parent's own child's card, as a five-minute link.

    `scoped_term_reports` filters a parent to published rows, so a withheld
    card is simply not found — R12 again: invisible, not forbidden.
    """
    await cards.ensure_published(db, parent, pupil_id=pupil_id, term_id=term_id)
    token = await cards.signed_link(db, parent, pupil_id=pupil_id, term_id=term_id, half=half)
    return RedirectResponse(url=f"{DOWNLOAD_PATH}/{token}", status_code=status.HTTP_302_FOUND)


@router.get(
    "/pupils/{pupil_id}/card",
    status_code=status.HTTP_302_FOUND,
    response_class=RedirectResponse,
)
async def pupils_card(
    db: DbSession,
    admin: Publisher,
    pupil_id: uuid.UUID,
    term_id: TermQuery,
    half: HalfQuery = TermHalf.SECOND_HALF,
) -> RedirectResponse:
    """The same card, for the school's own printing.

    §9 says the school will compare this output to the paper line by line,
    and §7 gives no staff route to a PDF — the admin would otherwise have to
    sign in as a parent to see what a parent gets (docs/DECISIONS.md D83).

    Unlike the parent's route this does **not** require publication: the
    point of checking a card is to check it before it goes out.
    """
    token = await cards.signed_link(db, admin, pupil_id=pupil_id, term_id=term_id, half=half)
    return RedirectResponse(url=f"{DOWNLOAD_PATH}/{token}", status_code=status.HTTP_302_FOUND)


@download_router.get(DOWNLOAD_PATH + "/{token}", response_class=Response)
async def download(token: str) -> Response:
    """The file a signed link points at. No session; the token is the authority.

    A forged, tampered or expired token gets the same 404 as a key that was
    never issued — telling them apart would tell whoever is trying which half
    to work on.
    """
    content = await cards.open_signed(token)
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'inline; filename="report-card.pdf"',
            # A signed URL that a cache could replay would outlive its own
            # expiry, which is the whole point of signing it.
            "Cache-Control": "private, no-store",
        },
    )
