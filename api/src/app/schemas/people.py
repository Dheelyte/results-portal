"""Pupils, accounts and the guardian link (§4.1).

The guardian link is the single most consequential record in this schema: §5.2
scopes a parent to exactly the pupils named in `guardian_pupils` and no others.
"""

import datetime as dt
import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.models import UserRole
from app.schemas.common import Name, OrmModel

AdmissionNumber = Annotated[str, Field(min_length=1, max_length=50)]


class PupilCreate(BaseModel):
    admission_number: AdmissionNumber
    first_name: Name
    last_name: Name
    middle_name: str | None = Field(default=None, max_length=200)
    sex: Literal["M", "F"] | None = Field(default=None, description="As the card records it.")
    date_of_birth: dt.date | None = None
    house_id: uuid.UUID | None = None

    class_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "Enrol the pupil into this class at the same time. Optional, but a pupil "
            "with no enrolment appears in no class list and gets no report."
        ),
    )
    joined_on: dt.date | None = Field(
        default=None, description="Defaults to the session's start date."
    )
    academic_session_id: uuid.UUID | None = Field(
        default=None, description="Defaults to the school's current session."
    )


class PupilRead(OrmModel):
    id: uuid.UUID
    admission_number: str
    first_name: str
    middle_name: str | None
    last_name: str
    sex: str | None
    date_of_birth: dt.date | None
    house_id: uuid.UUID | None
    is_active: bool


class PupilPageRead(BaseModel):
    """A page of the roll. Paged because the school has roughly 500 pupils."""

    items: list[PupilRead]
    total: int
    limit: int
    offset: int


class EnrollmentSave(BaseModel):
    class_id: uuid.UUID
    joined_on: dt.date | None = None
    academic_session_id: uuid.UUID | None = None


class EnrollmentRead(OrmModel):
    id: uuid.UUID
    pupil_id: uuid.UUID
    class_id: uuid.UUID
    academic_session_id: uuid.UUID
    joined_on: dt.date
    left_on: dt.date | None
    status: str


class UserCreate(BaseModel):
    """§5.1: accounts are admin-created. There is no self-registration."""

    role: UserRole
    full_name: Name
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(
        default=None,
        max_length=40,
        description=(
            "Either an email address or a phone number is required — many parents' "
            "email addresses are inactive, and both sign in against one password (A7)."
        ),
    )


class AccountRead(OrmModel):
    """An account as an admin sees it. Never carries the password hash."""

    id: uuid.UUID
    role: UserRole
    full_name: str
    email: str | None
    phone: str | None
    must_change_password: bool
    is_active: bool
    last_login_at: dt.datetime | None
    created_at: dt.datetime


class CreatedAccountRead(BaseModel):
    """A new or reset account, with its temporary password.

    The password is shown **once**, here. It is not stored in readable form,
    not logged and not audited, so if it is lost the only route is another
    reset. Pass it to the account holder out of band; they must change it
    before the portal will let them do anything else.
    """

    user: AccountRead
    temporary_password: str


class GuardianChild(BaseModel):
    pupil_id: uuid.UUID
    relationship: str | None = Field(default=None, max_length=50, examples=["Mother"])
    is_primary: bool = False


class GuardianChildrenSave(BaseModel):
    children: list[GuardianChild] = Field(min_length=1)
