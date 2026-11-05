"""Publication, the post-publication edit and the audit log
(§7's publication block, §6 R12, R13, §4.9).

    GET    /classes/{id}/publication?term_id=
    POST   /classes/{id}/publish?term_id=      { withhold_pupil_ids, reason }
    POST   /reports/{id}/release
    POST   /reports/{id}/withhold              { reason }
    PATCH  /entries/{id}                       { reason, …scores }
    GET    /audit?entity_type=&entity_id=

§5.2 gives all of these to the **admin**, except the audit log which the head
teacher also reads. Publishing is deliberately not the head teacher's: §1.6
keeps approve and publish as two steps held by two people.

The rules are in `services/publication.py` and `services/auditlog.py`.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.auth.dependencies import Context, DbSession
from app.authz import scope
from app.authz.dependencies import AuditReader, Publisher
from app.models import Pupil
from app.schemas.publication import (
    AuditEntryRead,
    AuditPageRead,
    ClassPublicationRead,
    CorrectableRowRead,
    EntryEditRead,
    EntryEditRequest,
    PublishOutcomeRead,
    PublishRequest,
    PupilEntriesRead,
    ReportStateRead,
    WithholdRequest,
)
from app.services import auditlog, publication
from app.services.support import one_or_404

router = APIRouter(tags=["admin: publication"])

TermQuery = Annotated[uuid.UUID, Query(description="Which term to publish.")]


@router.get("/classes/{class_id}/publication", response_model=ClassPublicationRead)
async def read_publication(
    db: DbSession, admin: Publisher, class_id: uuid.UUID, term_id: TermQuery
) -> ClassPublicationRead:
    """Every report in the class with its publication state.

    Added beyond §7's list for the same reason D57's GETs were: the publish
    screen cannot show who is held back without reading it.
    """
    klass, term, state, reports = await publication.class_reports(
        db, admin, class_id=class_id, term_id=term_id
    )
    return ClassPublicationRead(
        class_id=klass.id,
        class_name=klass.name,
        term_id=term.id,
        workflow_state=state,
        reports=[ReportStateRead(**vars(report)) for report in reports],
    )


@router.post("/classes/{class_id}/publish", response_model=PublishOutcomeRead)
async def publish_class(
    db: DbSession,
    admin: Publisher,
    context: Context,
    class_id: uuid.UUID,
    term_id: TermQuery,
    payload: PublishRequest,
) -> PublishOutcomeRead:
    """Publish a class, optionally holding individuals back (R12)."""
    outcome = await publication.publish_class(
        db,
        admin,
        class_id=class_id,
        term_id=term_id,
        withhold_pupil_ids=payload.withhold_pupil_ids,
        reason=payload.reason,
        ip_address=context.ip_address,
        user_agent=context.user_agent,
    )
    return PublishOutcomeRead(**vars(outcome))


@router.post("/reports/{report_id}/release", response_model=ReportStateRead)
async def release_report(
    db: DbSession, admin: Publisher, context: Context, report_id: uuid.UUID
) -> ReportStateRead:
    """Release one withheld report (R12: "released individually later")."""
    report = await publication.release_report(
        db,
        admin,
        report_id=report_id,
        ip_address=context.ip_address,
        user_agent=context.user_agent,
    )
    return await _report_state(db, admin, report)


@router.post("/reports/{report_id}/withhold", response_model=ReportStateRead)
async def withhold_report(
    db: DbSession,
    admin: Publisher,
    context: Context,
    report_id: uuid.UUID,
    payload: WithholdRequest,
) -> ReportStateRead:
    """Pull one report back, with a reason the parent never sees (R12)."""
    report = await publication.withhold_report(
        db,
        admin,
        report_id=report_id,
        reason=payload.reason,
        ip_address=context.ip_address,
        user_agent=context.user_agent,
    )
    return await _report_state(db, admin, report)


async def _report_state(db: DbSession, admin, report) -> ReportStateRead:
    """One report's state with the pupil's name, for the screen's list."""

    pupil = await one_or_404(
        db, scope.scoped_pupils(admin).where(Pupil.id == report.pupil_id), "pupil"
    )
    return ReportStateRead(
        report_id=report.id,
        pupil_id=pupil.id,
        name=f"{pupil.last_name}, {pupil.first_name}",
        admission_number=pupil.admission_number,
        state=report.state,
        published_at=report.published_at,
        withheld_reason=report.withheld_reason,
        acknowledged_at=report.parent_acknowledged_at,
    )


@router.get("/pupils/{pupil_id}/entries", response_model=PupilEntriesRead)
async def read_pupil_entries(
    db: DbSession, admin: Publisher, pupil_id: uuid.UUID, term_id: TermQuery
) -> PupilEntriesRead:
    """One pupil's score rows, with the ids `PATCH /entries/{id}` needs.

    §7 lists the PATCH and no way to reach an id: the grid is teacher-only
    (§5.2) and the review payload is the head teacher's. The same missing half
    D37, D51 and D57 record (docs/DECISIONS.md D75).
    """
    pupil, rows = await publication.pupil_entries(db, admin, pupil_id=pupil_id, term_id=term_id)
    return PupilEntriesRead(
        pupil_id=pupil.id,
        first_name=pupil.first_name,
        last_name=pupil.last_name,
        term_id=term_id,
        rows=[
            CorrectableRowRead(
                entry_id=row.entry_id,
                class_subject_id=row.class_subject_id,
                subject_name=row.subject_name,
                half=row.half,
                columns=list(row.columns),
                period_average=row.period_average,
                grade_letter=row.grade_letter,
                is_snapshot=row.is_snapshot,
                **row.scores,
            )
            for row in rows
        ],
    )


@router.patch("/entries/{entry_id}", response_model=EntryEditRead)
async def edit_entry(
    db: DbSession,
    admin: Publisher,
    context: Context,
    entry_id: uuid.UUID,
    payload: EntryEditRequest,
) -> EntryEditRead:
    """Correct one score after approval (R13).

    Admin only, reason required, audited with before and after values — and
    the grade is re-resolved against the scale the row was **frozen** against,
    never today's (§4.5, CLAUDE.md rule 6).
    """
    outcome = await publication.edit_entry(
        db,
        admin,
        entry_id=entry_id,
        scores=payload.provided_scores(),
        reason=payload.reason,
        ip_address=context.ip_address,
        user_agent=context.user_agent,
    )
    return EntryEditRead(
        entry_id=outcome.entry.id,
        pupil_name=outcome.pupil_name,
        subject_name=outcome.subject_name,
        before=outcome.before,
        after=outcome.after,
        grade_changed=outcome.grade_changed,
        regraded_against=outcome.regraded_against,
    )


@router.get("/audit", response_model=AuditPageRead)
async def read_audit(
    db: DbSession,
    reader: AuditReader,
    entity_type: Annotated[str | None, Query(max_length=60)] = None,
    entity_id: uuid.UUID | None = None,
    action: Annotated[str | None, Query(max_length=80)] = None,
    limit: Annotated[int, Query(ge=1, le=auditlog.MAX_PAGE_SIZE)] = auditlog.DEFAULT_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AuditPageRead:
    """The audit log, newest first (§4.9).

    §5.2 gives this to the admin in full and the head teacher read-only. In a
    resource nothing writes through, those are the same rows — "read-only" is
    enforced by there being no verb here but GET, and by `services/audit.py`
    being the only writer in the codebase.
    """
    page = await auditlog.read(
        db,
        reader,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        limit=limit,
        offset=offset,
    )
    return AuditPageRead(
        entries=[AuditEntryRead(**vars(entry)) for entry in page.entries],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )
