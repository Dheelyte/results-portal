"""The progress page and the submission gate (§7's teacher block, §8.3).

    GET  /classes/{id}/progress?term_id=
    POST /classes/{id}/submit?term_id=

Both return the same object, which is the point: §8.3's screen shows what is
outstanding and R10's refusal carries the same list, so the button's state and
the reason for it can never disagree.

The rules are in `services/submission.py`.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.auth.dependencies import Context, DbSession
from app.authz.dependencies import ClassSubmitter
from app.schemas.submission import (
    OutstandingItem,
    ProgressRead,
    PupilProgressRead,
    SheetProgressRead,
)
from app.services import submission

router = APIRouter(tags=["teacher: progress and submission"])

TermQuery = Annotated[uuid.UUID, Query(description="Which term's progress.")]


def _read(progress: submission.Progress) -> ProgressRead:
    return ProgressRead(
        class_id=progress.klass.id,
        class_name=progress.klass.name,
        term_id=progress.term.id,
        state=progress.state,
        times_school_opened=progress.times_school_opened,
        sheets=[
            SheetProgressRead(
                class_subject_id=sheet.class_subject_id,
                subject_id=sheet.subject_id,
                subject_name=sheet.subject_name,
                teacher_name=sheet.teacher_name,
                half=sheet.half,
                assessment_period_id=sheet.assessment_period_id,
                columns=list(sheet.columns),
                complete=sheet.complete,
                roll=sheet.roll,
                is_complete=sheet.is_complete,
                missing_pupil_count=sheet.missing_pupil_count,
                missing_pupils=sheet.missing_pupils,
                not_configured=sheet.not_configured,
            )
            for sheet in progress.sheets
        ],
        pupils=[
            PupilProgressRead(
                pupil_id=pupil.pupil_id,
                name=pupil.name,
                admission_number=pupil.admission_number,
                sections_written=pupil.sections_written,
                sections_total=pupil.sections_total,
                missing_sections=pupil.missing_sections,
                has_comment=pupil.has_comment,
                has_attendance=pupil.has_attendance,
                has_growth=pupil.has_growth,
                is_complete=pupil.is_complete,
            )
            for pupil in progress.pupils
        ],
        outstanding=[OutstandingItem(**item) for item in progress.outstanding],
        ready=progress.ready,
        may_submit=progress.may_submit,
        return_note=progress.return_note,
    )


@router.get("/classes/{class_id}/progress", response_model=ProgressRead)
async def read_progress(
    db: DbSession,
    teacher: ClassSubmitter,
    class_id: uuid.UUID,
    term_id: TermQuery,
) -> ProgressRead:
    """What is done and what is left, for the whole class.

    Readable by any teacher the class is in scope for — a subject teacher
    needs to see that their sheet is the one holding the class up — while only
    the class teacher may submit, which `may_submit` reports.
    """
    return _read(await submission.class_progress(db, teacher, class_id=class_id, term_id=term_id))


@router.post("/classes/{class_id}/submit", response_model=ProgressRead)
async def submit_class(
    db: DbSession,
    teacher: ClassSubmitter,
    context: Context,
    class_id: uuid.UUID,
    term_id: TermQuery,
) -> ProgressRead:
    """Send the class to the head teacher, if R10 passes.

    422 with the outstanding list if not, 409 if the class has already gone,
    403 if the caller is not its class teacher.
    """
    return _read(
        await submission.submit(
            db,
            teacher,
            class_id=class_id,
            term_id=term_id,
            ip_address=context.ip_address,
            user_agent=context.user_agent,
        )
    )
