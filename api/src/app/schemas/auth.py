"""Auth request and response bodies.

Separate Create / Read models, never an ORM model exposed directly
(CLAUDE.md, Conventions). Nothing here carries `password_hash`.
"""

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.models import UserRole


class LoginRequest(BaseModel):
    """§5.1: parents sign in with email *or* phone against one password."""

    identifier: str = Field(
        min_length=1,
        max_length=320,
        description="Email address or phone number.",
    )
    password: str = Field(min_length=1, max_length=1024)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=1, max_length=1024)


class UserRead(BaseModel):
    """A user as the owner of the account may see themselves."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    school_id: uuid.UUID
    role: UserRole
    full_name: str
    email: str | None
    phone: str | None
    must_change_password: bool


class TokenResponse(BaseModel):
    """The access token and who it belongs to.

    The refresh token is **absent by design** — it travels only in an httpOnly
    cookie, where client JavaScript cannot read it. Returning it in the body
    would hand it to any successful XSS.
    """

    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Access token lifetime in seconds.")
    user: UserRead


class MessageResponse(BaseModel):
    detail: str


class AccountLockedResponse(BaseModel):
    detail: str
    locked_until: dt.datetime
