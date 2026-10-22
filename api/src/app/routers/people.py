"""Admin setup: pupils, accounts and the guardian link (§7).

N8, answered: everything here is typed in by hand. There is no import
endpoint, and §7 marks the CSV route descoped rather than impossible.
"""

import uuid

from fastapi import APIRouter, Query, status

from app.auth.dependencies import Context, DbSession
from app.authz.dependencies import AcademicStructureAdmin, UserAdmin
from app.models import UserRole
from app.schemas.people import (
    AccountRead,
    CreatedAccountRead,
    EnrollmentRead,
    EnrollmentSave,
    GuardianChildrenSave,
    PupilCreate,
    PupilPageRead,
    PupilRead,
    UserCreate,
)
from app.services import accounts as accounts_service
from app.services import pupils as pupils_service

router = APIRouter(tags=["admin: people"])


# ---------------------------------------------------------------------------
# Pupils
# ---------------------------------------------------------------------------


@router.get("/pupils", response_model=PupilPageRead, summary="List pupils")
async def list_pupils(
    db: DbSession,
    admin: AcademicStructureAdmin,
    class_id: uuid.UUID | None = None,
    academic_session_id: uuid.UUID | None = None,
    search: str | None = Query(default=None, max_length=100),
    include_inactive: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> PupilPageRead:
    """A page of the roll, filterable by class and searchable by name or number."""
    page = await pupils_service.list_pupils(
        db,
        admin,
        class_id=class_id,
        academic_session_id=academic_session_id,
        search=search,
        include_inactive=include_inactive,
        limit=limit,
        offset=offset,
    )
    return PupilPageRead(
        items=[PupilRead.model_validate(pupil) for pupil in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post(
    "/pupils",
    response_model=PupilRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a pupil",
)
async def create_pupil(
    payload: PupilCreate,
    db: DbSession,
    admin: AcademicStructureAdmin,
    context: Context,
) -> PupilRead:
    record = await pupils_service.create_pupil(
        db,
        admin,
        admission_number=payload.admission_number,
        first_name=payload.first_name,
        last_name=payload.last_name,
        middle_name=payload.middle_name,
        sex=payload.sex,
        date_of_birth=payload.date_of_birth,
        house_id=payload.house_id,
        class_id=payload.class_id,
        joined_on=payload.joined_on,
        academic_session_id=payload.academic_session_id,
        ip_address=context.ip_address,
        user_agent=context.user_agent,
    )
    return PupilRead.model_validate(record)


@router.put(
    "/pupils/{pupil_id}/enrollment",
    response_model=EnrollmentRead,
    summary="Place a pupil in a class",
)
async def set_enrollment(
    pupil_id: uuid.UUID,
    payload: EnrollmentSave,
    db: DbSession,
    admin: AcademicStructureAdmin,
    context: Context,
) -> EnrollmentRead:
    """Enrol a pupil, or move them to another class this session.

    Not in §7's list, which assumed enrolment always happened alongside pupil
    creation. A roll typed in before the classes were settled needs placing,
    and pupils do change class mid-year (docs/DECISIONS.md D37).
    """
    record = await pupils_service.set_enrollment(
        db,
        admin,
        pupil_id,
        class_id=payload.class_id,
        joined_on=payload.joined_on,
        academic_session_id=payload.academic_session_id,
        ip_address=context.ip_address,
        user_agent=context.user_agent,
    )
    return EnrollmentRead.model_validate(record)


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------


@router.get("/users", response_model=list[AccountRead], summary="List accounts")
async def list_users(
    db: DbSession,
    admin: UserAdmin,
    role: UserRole | None = None,
    include_inactive: bool = True,
) -> list[AccountRead]:
    records = await accounts_service.list_users(
        db, admin, role=role, include_inactive=include_inactive
    )
    return [AccountRead.model_validate(record) for record in records]


@router.post(
    "/users",
    response_model=CreatedAccountRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account",
)
async def create_user(
    payload: UserCreate,
    db: DbSession,
    admin: UserAdmin,
    context: Context,
) -> CreatedAccountRead:
    """Create an account and return its temporary password **once**.

    §5.1: accounts are admin-created and never self-registered. The temporary
    password is shown here and nowhere else — it is not stored readably, not
    logged and not audited. The holder must change it before the portal will
    let them do anything else.
    """
    created = await accounts_service.create_user(
        db,
        admin,
        role=payload.role,
        full_name=payload.full_name,
        email=payload.email,
        phone=payload.phone,
        ip_address=context.ip_address,
        user_agent=context.user_agent,
    )
    return CreatedAccountRead(
        user=AccountRead.model_validate(created.user),
        temporary_password=created.temporary_password,
    )


@router.post(
    "/users/{user_id}/reset-password",
    response_model=CreatedAccountRead,
    summary="Reset someone's password",
)
async def reset_password(
    user_id: uuid.UUID,
    db: DbSession,
    admin: UserAdmin,
    context: Context,
) -> CreatedAccountRead:
    """Issue a fresh temporary password and revoke every live session.

    What an admin does when a parent's phone is lost or a password has been
    passed around. Audited, as §4.9 requires of every reset.
    """
    created = await accounts_service.reset_password(
        db,
        admin,
        user_id,
        ip_address=context.ip_address,
        user_agent=context.user_agent,
    )
    return CreatedAccountRead(
        user=AccountRead.model_validate(created.user),
        temporary_password=created.temporary_password,
    )


@router.get(
    "/guardians/{guardian_user_id}/children",
    response_model=list[PupilRead],
    summary="A parent's children",
)
async def list_children(
    guardian_user_id: uuid.UUID, db: DbSession, admin: UserAdmin
) -> list[PupilRead]:
    records = await accounts_service.list_children(db, admin, guardian_user_id)
    return [PupilRead.model_validate(record) for record in records]


@router.post(
    "/guardians/{guardian_user_id}/children",
    response_model=list[PupilRead],
    summary="Attach children to a parent account",
)
async def link_children(
    guardian_user_id: uuid.UUID,
    payload: GuardianChildrenSave,
    db: DbSession,
    admin: UserAdmin,
    context: Context,
) -> list[PupilRead]:
    """Attach pupils to a parent account.

    This is the link §5.2's most important filter rests on: a parent sees
    exactly the pupils named here. Additive, so adding a second child later
    does not detach the first.
    """
    records = await accounts_service.link_children(
        db,
        admin,
        guardian_user_id,
        children=[
            (child.pupil_id, child.relationship, child.is_primary) for child in payload.children
        ],
        ip_address=context.ip_address,
        user_agent=context.user_agent,
    )
    return [PupilRead.model_validate(record) for record in records]
