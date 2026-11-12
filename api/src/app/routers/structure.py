"""Admin setup: classes, houses, subjects, offerings and teachers (§7).

Thin translation over `services/academic.py` and `services/subjects.py`.
Admin-only, per §5.2's first two rows.
"""

import uuid
from collections.abc import Sequence

from fastapi import APIRouter, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import Context, DbSession
from app.authz.dependencies import AcademicStructureAdmin, UserAdmin
from app.models import ClassSubject, User
from app.schemas.academic import (
    ClassCreate,
    ClassRead,
    ClassUpdate,
    HouseCreate,
    HouseRead,
    HouseUpdate,
)
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


async def _class_subjects_read(
    db: AsyncSession, admin: User, records: Sequence[ClassSubject]
) -> list[ClassSubjectRead]:
    """Each class-subject with the teacher who enters its scores, if any."""
    teachers = await subjects_service.teachers_of(db, admin, [record.id for record in records])
    return [
        ClassSubjectRead.model_validate(record).model_copy(
            update={"teacher_user_id": teachers.get(record.id)}
        )
        for record in records
    ]


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
    return await _class_subjects_read(db, admin, records)


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
    return await _class_subjects_read(db, admin, records)


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


@router.get(
    "/classes/{class_id}/class-teacher",
    response_model=ClassTeacherRead | None,
    summary="A class's class teacher",
)
async def get_class_teacher(
    class_id: uuid.UUID,
    db: DbSession,
    admin: UserAdmin,
    academic_session_id: uuid.UUID | None = None,
) -> ClassTeacherRead | None:
    """This session's class teacher, or null when nobody has been assigned."""
    record = await subjects_service.get_class_teacher(
        db, admin, class_id, academic_session_id=academic_session_id
    )
    return None if record is None else ClassTeacherRead.model_validate(record)


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


# ---------------------------------------------------------------------------
# Editing and deleting (docs/DECISIONS.md D121)
# ---------------------------------------------------------------------------


@router.patch("/classes/{class_id}", response_model=ClassRead, summary="Update a class")
async def update_class(
    class_id: uuid.UUID,
    payload: ClassUpdate,
    db: DbSession,
    admin: AcademicStructureAdmin,
    context: Context,
) -> ClassRead:
    """Rename, reorder, deactivate or reactivate a class."""
    record = await academic_service.update_class(
        db,
        admin,
        class_id,
        changes=payload.model_dump(exclude_unset=True),
        ip_address=context.ip_address,
        user_agent=context.user_agent,
    )
    return ClassRead.model_validate(record)


@router.delete(
    "/classes/{class_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an unused class",
)
async def delete_class(
    class_id: uuid.UUID,
    db: DbSession,
    admin: AcademicStructureAdmin,
    context: Context,
) -> None:
    """Delete a class no pupil was enrolled in. Refused with 409, naming what is in the way, once
    anything depends on it (D121).
    """
    await academic_service.delete_class(
        db,
        admin,
        class_id,
        ip_address=context.ip_address,
        user_agent=context.user_agent,
    )


@router.patch("/houses/{house_id}", response_model=HouseRead, summary="Rename a house")
async def update_house(
    house_id: uuid.UUID,
    payload: HouseUpdate,
    db: DbSession,
    admin: AcademicStructureAdmin,
    context: Context,
) -> HouseRead:
    """Rename a house."""
    record = await academic_service.update_house(
        db,
        admin,
        house_id,
        name=payload.name,
        ip_address=context.ip_address,
        user_agent=context.user_agent,
    )
    return HouseRead.model_validate(record)


@router.delete(
    "/houses/{house_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an empty house",
)
async def delete_house(
    house_id: uuid.UUID,
    db: DbSession,
    admin: AcademicStructureAdmin,
    context: Context,
) -> None:
    """Delete a house no pupil belongs to. Refused with 409, naming what is in the way, once
    anything depends on it (D121).
    """
    await academic_service.delete_house(
        db,
        admin,
        house_id,
        ip_address=context.ip_address,
        user_agent=context.user_agent,
    )


@router.delete(
    "/subjects/{subject_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an unused subject",
)
async def delete_subject(
    subject_id: uuid.UUID,
    db: DbSession,
    admin: AcademicStructureAdmin,
    context: Context,
) -> None:
    """Delete a subject no class was given. Refused with 409, naming what is in the way, once
    anything depends on it (D121).
    """
    await subjects_service.delete_subject(
        db,
        admin,
        subject_id,
        ip_address=context.ip_address,
        user_agent=context.user_agent,
    )
