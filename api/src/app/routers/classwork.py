"""The class teacher's own tasks (§7's teacher block, §8.2, §8.3).

    GET  /classes/{id}/narrative?term_id=
    GET  /pupils/{id}/narrative?term_id=
    PUT  /pupils/{id}/narrative?term_id=
    GET  /classes/{id}/attendance?term_id=
    PUT  /classes/{id}/attendance?term_id=
    GET  /classes/{id}/growth?term_id=
    PUT  /classes/{id}/growth?term_id=
    GET  /classes/{id}/comments?term_id=
    PUT  /classes/{id}/comments?term_id=
    GET  /phrases?scope=

§7 lists only the PUT for attendance, growth and comments, and no GET for one
pupil's narrative. The screens cannot work without reading what is already
there, so each PUT has the matching GET beside it — the missing half of a
stated requirement, as D37 and D51 were (docs/DECISIONS.md D57).

Thin, as always: R8, R9 and R14 live in `services/narrative.py`,
`services/wellbeing.py` and `services/reports.py`.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.auth.dependencies import Context, DbSession
from app.authz.dependencies import CommentBankReader, NarrativeWriter, WellbeingRecorder
from app.models import AttendanceRecord, GrowthRecord, Pupil, TermReport
from app.schemas.classwork import (
    AttendanceRead,
    AttendanceSave,
    ClassAttendanceRead,
    ClassCommentsRead,
    ClassCommentsSave,
    ClassGrowthRead,
    ClassNarrativeRead,
    GrowthRead,
    GrowthSave,
    NarrativeProgressRead,
    NarrativeSave,
    PassageRead,
    PhraseRead,
    PupilCommentRead,
    PupilNarrativeRead,
    SectionHeadingRead,
)
from app.services import narrative as narrative_service
from app.services import reports as reports_service
from app.services import wellbeing as wellbeing_service
from app.services.narrative import PassageInput
from app.services.reports import CommentInput
from app.services.wellbeing import AttendanceInput, GrowthInput

router = APIRouter(tags=["teacher: narrative and class records"])

TermQuery = Annotated[uuid.UUID, Query(description="Which term's records.")]


def _identity(pupil: Pupil) -> dict[str, object]:
    """The four fields every one of these rows carries about a pupil."""
    return {
        "pupil_id": pupil.id,
        "admission_number": pupil.admission_number,
        "first_name": pupil.first_name,
        "middle_name": pupil.middle_name,
        "last_name": pupil.last_name,
    }


# ---------------------------------------------------------------------------
# The narrative (§8.2)
# ---------------------------------------------------------------------------


@router.get("/classes/{class_id}/narrative", response_model=ClassNarrativeRead)
async def read_class_narrative(
    db: DbSession,
    teacher: NarrativeWriter,
    class_id: uuid.UUID,
    term_id: TermQuery,
) -> ClassNarrativeRead:
    """The class list with each pupil's progress — §8.2's "12 of 30"."""
    found = await narrative_service.class_narrative(db, teacher, class_id=class_id, term_id=term_id)
    writable = set(found.writable_section_ids)

    return ClassNarrativeRead(
        class_id=found.klass.id,
        class_name=found.klass.name,
        term_id=found.term.id,
        sections=[
            SectionHeadingRead(
                section_id=section.id,
                code=section.code,
                label=section.label,
                group_label=section.group_label,
                display_order=section.display_order,
                writable=section.id in writable,
            )
            for section in found.sections
        ],
        pupils=[
            NarrativeProgressRead(
                pupil_id=pupil.pupil_id,
                admission_number=pupil.admission_number,
                first_name=pupil.first_name,
                middle_name=pupil.middle_name,
                last_name=pupil.last_name,
                written=pupil.written,
                total=pupil.total,
                is_complete=pupil.is_complete,
            )
            for pupil in found.pupils
        ],
        complete_pupils=found.complete_pupils,
        roll_size=len(found.pupils),
        state=found.state,
        editable=found.editable,
    )


def _pupil_narrative_read(found: narrative_service.PupilNarrative) -> PupilNarrativeRead:
    return PupilNarrativeRead(
        **_identity(found.pupil),
        class_id=found.klass.id,
        class_name=found.klass.name,
        term_id=found.term.id,
        passages=[
            PassageRead(
                section_id=passage.section.id,
                code=passage.section.code,
                label=passage.section.label,
                group_label=passage.section.group_label,
                display_order=passage.section.display_order,
                body=passage.entry.body if passage.entry else None,
                writable=passage.writable,
                is_complete=passage.is_complete,
                updated_at=passage.entry.updated_at if passage.entry else None,
            )
            for passage in found.passages
        ],
        complete_count=found.complete_count,
        section_count=len(found.passages),
        state=found.state,
        editable=found.editable,
        previous_pupil_id=found.previous_pupil_id,
        next_pupil_id=found.next_pupil_id,
        position=found.position,
        roll_size=found.roll_size,
    )


@router.get("/pupils/{pupil_id}/narrative", response_model=PupilNarrativeRead)
async def read_pupil_narrative(
    db: DbSession,
    teacher: NarrativeWriter,
    pupil_id: uuid.UUID,
    term_id: TermQuery,
) -> PupilNarrativeRead:
    """One pupil, all sixteen sections — the page §8.2 describes."""
    return _pupil_narrative_read(
        await narrative_service.pupil_narrative(db, teacher, pupil_id=pupil_id, term_id=term_id)
    )


@router.put("/pupils/{pupil_id}/narrative", response_model=PupilNarrativeRead)
async def save_pupil_narrative(
    db: DbSession,
    teacher: NarrativeWriter,
    context: Context,
    pupil_id: uuid.UUID,
    term_id: TermQuery,
    payload: NarrativeSave,
) -> PupilNarrativeRead:
    """Save a set of passages for one pupil, applying all of them or none."""
    found = await narrative_service.save_pupil_narrative(
        db,
        teacher,
        pupil_id=pupil_id,
        term_id=term_id,
        passages=[
            PassageInput(section_id=passage.section_id, body=passage.body)
            for passage in payload.passages
        ],
        ip_address=context.ip_address,
        user_agent=context.user_agent,
    )
    return _pupil_narrative_read(found)


# ---------------------------------------------------------------------------
# Attendance and growth (§4.7, R9)
# ---------------------------------------------------------------------------


def _attendance_read(found: wellbeing_service.ClassRecords) -> ClassAttendanceRead:
    return ClassAttendanceRead(
        class_id=found.klass.id,
        class_name=found.klass.name,
        term_id=found.term.id,
        times_school_opened=found.times_school_opened,
        rows=[
            AttendanceRead(
                **_identity(pupil),
                **_counts(found.attendance.get(pupil.id)),
            )
            for pupil in found.pupils
        ],
        state=found.state,
        editable=found.editable,
    )


def _counts(record: AttendanceRecord | None) -> dict[str, int | None]:
    if record is None:
        return {"times_present": None, "times_absent": None, "times_late": None}
    return {
        "times_present": record.times_present,
        "times_absent": record.times_absent,
        "times_late": record.times_late,
    }


@router.get("/classes/{class_id}/attendance", response_model=ClassAttendanceRead)
async def read_attendance(
    db: DbSession,
    teacher: WellbeingRecorder,
    class_id: uuid.UUID,
    term_id: TermQuery,
) -> ClassAttendanceRead:
    return _attendance_read(
        await wellbeing_service.class_records(db, teacher, class_id=class_id, term_id=term_id)
    )


@router.put("/classes/{class_id}/attendance", response_model=ClassAttendanceRead)
async def save_attendance(
    db: DbSession,
    teacher: WellbeingRecorder,
    context: Context,
    class_id: uuid.UUID,
    term_id: TermQuery,
    payload: AttendanceSave,
) -> ClassAttendanceRead:
    """R9: present + absent must equal the times the school opened."""
    return _attendance_read(
        await wellbeing_service.save_attendance(
            db,
            teacher,
            class_id=class_id,
            term_id=term_id,
            rows=[
                AttendanceInput(
                    pupil_id=row.pupil_id,
                    times_present=row.times_present,
                    times_absent=row.times_absent,
                    times_late=row.times_late,
                )
                for row in payload.rows
            ],
            ip_address=context.ip_address,
            user_agent=context.user_agent,
        )
    )


def _growth_read(found: wellbeing_service.ClassRecords) -> ClassGrowthRead:
    return ClassGrowthRead(
        class_id=found.klass.id,
        class_name=found.klass.name,
        term_id=found.term.id,
        rows=[
            GrowthRead(**_identity(pupil), **_measurements(found.growth.get(pupil.id)))
            for pupil in found.pupils
        ],
        state=found.state,
        editable=found.editable,
    )


def _measurements(record: GrowthRecord | None) -> dict[str, object]:
    return {
        column: getattr(record, column) if record is not None else None
        for column in wellbeing_service.GROWTH_COLUMNS
    }


@router.get("/classes/{class_id}/growth", response_model=ClassGrowthRead)
async def read_growth(
    db: DbSession,
    teacher: WellbeingRecorder,
    class_id: uuid.UUID,
    term_id: TermQuery,
) -> ClassGrowthRead:
    return _growth_read(
        await wellbeing_service.class_records(db, teacher, class_id=class_id, term_id=term_id)
    )


@router.put("/classes/{class_id}/growth", response_model=ClassGrowthRead)
async def save_growth(
    db: DbSession,
    teacher: WellbeingRecorder,
    context: Context,
    class_id: uuid.UUID,
    term_id: TermQuery,
    payload: GrowthSave,
) -> ClassGrowthRead:
    return _growth_read(
        await wellbeing_service.save_growth(
            db,
            teacher,
            class_id=class_id,
            term_id=term_id,
            rows=[
                GrowthInput(
                    pupil_id=row.pupil_id,
                    height_start_m=row.height_start_m,
                    height_end_m=row.height_end_m,
                    weight_start_kg=row.weight_start_kg,
                    weight_end_kg=row.weight_end_kg,
                )
                for row in payload.rows
            ],
            ip_address=context.ip_address,
            user_agent=context.user_agent,
        )
    )


# ---------------------------------------------------------------------------
# The class teacher's comment (§1.6)
# ---------------------------------------------------------------------------


def _comments_read(found: reports_service.ClassComments) -> ClassCommentsRead:
    return ClassCommentsRead(
        class_id=found.klass.id,
        class_name=found.klass.name,
        term_id=found.term.id,
        rows=[
            PupilCommentRead(
                **_identity(pupil),
                comment=_comment_of(found.reports.get(pupil.id)),
            )
            for pupil in found.pupils
        ],
        state=found.state,
        editable=found.editable,
    )


def _comment_of(report: TermReport | None) -> str | None:
    return report.class_teacher_comment if report is not None else None


@router.get("/classes/{class_id}/comments", response_model=ClassCommentsRead)
async def read_comments(
    db: DbSession,
    teacher: WellbeingRecorder,
    class_id: uuid.UUID,
    term_id: TermQuery,
) -> ClassCommentsRead:
    return _comments_read(
        await reports_service.class_comments(db, teacher, class_id=class_id, term_id=term_id)
    )


@router.put("/classes/{class_id}/comments", response_model=ClassCommentsRead)
async def save_comments(
    db: DbSession,
    teacher: WellbeingRecorder,
    context: Context,
    class_id: uuid.UUID,
    term_id: TermQuery,
    payload: ClassCommentsSave,
) -> ClassCommentsRead:
    return _comments_read(
        await reports_service.save_class_comments(
            db,
            teacher,
            class_id=class_id,
            term_id=term_id,
            rows=[CommentInput(pupil_id=row.pupil_id, comment=row.comment) for row in payload.rows],
            ip_address=context.ip_address,
            user_agent=context.user_agent,
        )
    )


# ---------------------------------------------------------------------------
# The phrase bank (§4.6, §8.2)
# ---------------------------------------------------------------------------


@router.get("/phrases", response_model=list[PhraseRead])
async def read_phrases(
    db: DbSession,
    staff: CommentBankReader,
    scope: Annotated[
        str | None,
        Query(description="A narrative section code, or 'class_teacher' | 'head_teacher'."),
    ] = None,
) -> list[PhraseRead]:
    """The active phrases, optionally for one section only.

    A separate path from the admin's `GET /comment-bank` rather than a widened
    gate on it: this one returns only the active entries, takes no part in
    managing them, and is the one §8.2's phrase-bank button calls
    (docs/DECISIONS.md D55).
    """
    phrases = await narrative_service.list_comments(
        db, staff, comment_scope=scope, include_inactive=False
    )
    return [PhraseRead.model_validate(phrase) for phrase in phrases]
