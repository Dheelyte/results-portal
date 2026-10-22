"""The setup checklist (§7).

One endpoint, and the one that answers milestone 5's done-when: "an admin
configures a full term from an empty database".
"""

import uuid

from fastapi import APIRouter

from app.auth.dependencies import DbSession
from app.authz.dependencies import AcademicStructureAdmin
from app.schemas.setup import ChecklistItemRead, ChecklistRead
from app.services import setup as setup_service

router = APIRouter(tags=["admin: setup"])


@router.get("/setup-checklist", response_model=ChecklistRead, summary="Is this term ready?")
async def setup_checklist(
    term_id: uuid.UUID, db: DbSession, admin: AcademicStructureAdmin
) -> ChecklistRead:
    """Everything standing between this term and a teacher entering a score.

    `ready` is true when every **blocking** item is done. Advisory items — an
    empty phrase bank, a parent account with no child attached — are real gaps
    that score entry can start without, and they are reported rather than
    enforced.

    Each item names what is outstanding, by class and by subject. "Setup
    incomplete" with no list generates a support call every term.
    """
    checklist = await setup_service.term_readiness(db, admin, term_id)
    return ChecklistRead(
        term_id=checklist.term_id,
        term_label=checklist.term_label,
        academic_session_id=checklist.academic_session_id,
        academic_session_name=checklist.academic_session_name,
        ready=checklist.ready,
        items=[
            ChecklistItemRead(
                key=item.key,
                label=item.label,
                done=item.done,
                blocking=item.blocking,
                detail=item.detail,
                outstanding=item.outstanding,
            )
            for item in checklist.items
        ],
    )
