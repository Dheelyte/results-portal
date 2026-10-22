"""Admin setup: classes, houses, subjects, offerings and teachers (§7).

Thin translation over `services/academic.py` and `services/subjects.py`.
Admin-only, per §5.2's first two rows.
"""

import uuid

from fastapi import APIRouter, status

from app.auth.dependencies import Context, DbSession
from app.authz.dependencies import AcademicStructureAdmin, UserAdmin
from app.schemas.academic import ClassCreate, ClassRead, HouseCreate, HouseRead
from app.schemas.subjects import (
    ClassSubjectRead,
    ClassSubjectsSave,
    ClassTeacherRead,
    ClassTeacherSave,
    SubjectCreate,
    SubjectRead,
    SubjectUpdate,
    TeacherAssignmentSave,
    TeachingAssignmentRead,
)
from app.services import academic as academic_service
from app.services import subjects as subjects_service

router = APIRouter(tags=["admin: classes and subjects"])


# ---------------------------------------------------------------------------
# Classes and houses
# ---------------------------------------------------------------------------


@router.get("/classes", response_model=list[ClassRead], summary="List classes")
async def list_classes(
    db: DbSession, admin: AcademicStructureAdmin, include_inactive: bool = False
) -> list[ClassRead]:
    records = await academic_service.list_classes(db, admin, include_inactive=include_inactive)
    return [ClassRead.model_validate(record) for record in records]


@router.post(
    "/classes",
    response_model=ClassRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a class",
)
async def create_class(
    payload: ClassCreate,
    db: DbSession,
    admin: AcademicStructureAdmin,
    context: Context,
) -> ClassRead:
    record = await academic_service.create_class(
        db,
        admin,
        name=payload.name,
        level_order=payload.level_order,
        ip_address=context.ip_address,
        user_agent=context.user_agent,
    )
    return ClassRead.model_validate(record)


@router.get("/houses", response_model=list[HouseRead], summary="List houses")
async def list_houses(db: DbSession, admin: AcademicStructureAdmin) -> list[HouseRead]:
    records = await academic_service.list_houses(db, admin)
    return [HouseRead.model_validate(record) for record in records]


@router.post(
    "/houses",
    response_model=HouseRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a house",
)
async def create_house(
    payload: HouseCreate,
    db: DbSession,
    admin: AcademicStructureAdmin,
    context: Context,
) -> HouseRead:
    record = await academic_service.create_house(
        db,
        admin,
        name=payload.name,
        ip_address=context.ip_address,
        user_agent=context.user_agent,
    )
    return HouseRead.model_validate(record)


# ---------------------------------------------------------------------------
# Subjects
# ---------------------------------------------------------------------------


@router.get("/subjects", response_model=list[SubjectRead], summary="List subjects")
async def list_subjects(
    db: DbSession, admin: AcademicStructureAdmin, include_inactive: bool = False
) -> list[SubjectRead]:
    """The subject tree in display order, group headings included."""
    records = await subjects_service.list_subjects(db, admin, include_inactive=include_inactive)
    return [SubjectRead.model_validate(record) for record in records]


@router.post(
    "/subjects",
    response_model=SubjectRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a subject",
)
async def create_subject(
    payload: SubjectCreate,
    db: DbSession,
    admin: AcademicStructureAdmin,
    context: Context,
) -> SubjectRead:
    record = await subjects_service.create_subject(
        db,
        admin,
        name=payload.name,
        parent_subject_id=payload.parent_subject_id,
        is_group=payload.is_group,
        is_specialist=payload.is_specialist,
        display_order=payload.display_order,
        ip_address=context.ip_address,
        user_agent=context.user_agent,
    )
    return SubjectRead.model_validate(record)


@router.patch("/subjects/{subject_id}", response_model=SubjectRead, summary="Update a subject")
async def update_subject(
    subject_id: uuid.UUID,
    payload: SubjectUpdate,
    db: DbSession,
    admin: AcademicStructureAdmin,
    context: Context,
) -> SubjectRead:
    """Rename, reorder, retire or regroup a subject.

    Not in §7's list, which has only GET and POST. §1.5 requires it: "the list
    must be admin-editable and the display order must be configurable", and
    the card leaves blank rows for additions (docs/DECISIONS.md D37).
    """
    record = await subjects_service.update_subject(
        db,
        admin,
        subject_id,
        changes=payload.model_dump(exclude_unset=True),
        ip_address=context.ip_address,
        user_agent=context.user_agent,
    )
    return SubjectRead.model_validate(record)


# ---------------------------------------------------------------------------
# What each class offers, and who teaches it
# ---------------------------------------------------------------------------


@router.get(
    "/classes/{class_id}/subjects",
    response_model=list[ClassSubjectRead],
    summary="A class's subject list",
)
async def list_class_subjects(
    class_id: uuid.UUID,
    db: DbSession,
    admin: AcademicStructureAdmin,
    academic_session_id: uuid.UUID | None = None,
) -> list[ClassSubjectRead]:
    records = await subjects_service.list_class_subjects(
        db, admin, class_id, academic_session_id=academic_session_id
    )
    return [ClassSubjectRead.model_validate(record) for record in records]


@router.put(
    "/classes/{class_id}/subjects",
    response_model=list[ClassSubjectRead],
    summary="Set a class's subject list",
)
async def set_class_subjects(
    class_id: uuid.UUID,
    payload: ClassSubjectsSave,
    db: DbSession,
    admin: AcademicStructureAdmin,
    context: Context,
) -> list[ClassSubjectRead]:
    """Replace the whole set of subjects this class is taught.

    A group heading is refused (R7) — English prints as a heading over its
    five sub-subjects and carries no scores of its own. A subject that already
    has scores entered cannot be removed; retire it instead, so the record
    survives.
    """
    records = await subjects_service.set_class_subjects(
        db,
        admin,
        class_id,
        subject_ids=payload.subject_ids,
        academic_session_id=payload.academic_session_id,
        ip_address=context.ip_address,
        user_agent=context.user_agent,
    )
    return [ClassSubjectRead.model_validate(record) for record in records]


@router.put(
    "/class-subjects/{class_subject_id}/teacher",
    response_model=TeachingAssignmentRead,
    summary="Assign the teacher who enters scores",
)
async def set_class_subject_teacher(
    class_subject_id: uuid.UUID,
    payload: TeacherAssignmentSave,
    db: DbSession,
    admin: UserAdmin,
    context: Context,
) -> TeachingAssignmentRead:
    """One teacher per class-subject (§4.3).

    §5.2 limits score entry to "own class-subjects", so this is the record
    that decides who can fill the sheet in — being class teacher of the class
    is not enough.
    """
    record = await subjects_service.set_class_subject_teacher(
        db,
        admin,
        class_subject_id,
        teacher_user_id=payload.teacher_user_id,
        ip_address=context.ip_address,
        user_agent=context.user_agent,
    )
    return TeachingAssignmentRead.model_validate(record)


@router.put(
    "/classes/{class_id}/class-teacher",
    response_model=ClassTeacherRead,
    summary="Assign a class teacher",
)
async def set_class_teacher(
    class_id: uuid.UUID,
    payload: ClassTeacherSave,
    db: DbSession,
    admin: UserAdmin,
    context: Context,
) -> ClassTeacherRead:
    """The most consequential assignment in setup.

    §5.2 hands this person the narrative sections, attendance, growth, the
    class teacher's comment and the submission gate for every pupil in the
    class.
    """
    record = await subjects_service.set_class_teacher(
        db,
        admin,
        class_id,
        teacher_user_id=payload.teacher_user_id,
        academic_session_id=payload.academic_session_id,
        ip_address=context.ip_address,
        user_agent=context.user_agent,
    )
    return ClassTeacherRead.model_validate(record)
