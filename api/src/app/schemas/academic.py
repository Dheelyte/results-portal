"""Sessions, terms, assessment periods, classes and houses (§4.2)."""

import datetime as dt
import uuid

from pydantic import BaseModel, Field

from app.models import TermHalf, TermNumber
from app.schemas.common import Name, OrmModel


class AcademicSessionCreate(BaseModel):
    name: Name = Field(description="As the school writes it, e.g. 2026/2027.")
    starts_on: dt.date
    ends_on: dt.date
    is_current: bool = Field(
        default=False,
        description=(
            "Make this the current session, demoting any other. Everything a "
            "teacher or parent sees is scoped to the current session."
        ),
    )


class AcademicSessionRead(OrmModel):
    id: uuid.UUID
    name: str
    starts_on: dt.date
    ends_on: dt.date
    is_current: bool


class TermCreate(BaseModel):
    academic_session_id: uuid.UUID
    number: TermNumber
    starts_on: dt.date
    ends_on: dt.date
    times_school_opened: int | None = Field(
        default=None,
        ge=0,
        description="R9 measures attendance against this. Can be filled in later.",
    )
    next_resumption_on: dt.date | None = None
    card_return_on: dt.date | None = Field(
        default=None,
        description='Prints as "return this card to the School on …".',
    )
    is_current: bool = False


class TermUpdate(BaseModel):
    """Every field optional; only what is sent is changed."""

    starts_on: dt.date | None = None
    ends_on: dt.date | None = None
    times_school_opened: int | None = Field(default=None, ge=0)
    next_resumption_on: dt.date | None = None
    card_return_on: dt.date | None = None
    is_current: bool | None = None


class TermRead(OrmModel):
    id: uuid.UUID
    academic_session_id: uuid.UUID
    number: TermNumber
    starts_on: dt.date
    ends_on: dt.date
    times_school_opened: int | None
    next_resumption_on: dt.date | None
    card_return_on: dt.date | None
    is_current: bool


class AssessmentPeriodSave(BaseModel):
    half: TermHalf
    opens_on: dt.date | None = None
    closes_on: dt.date | None = None


class AssessmentPeriodRead(OrmModel):
    id: uuid.UUID
    term_id: uuid.UUID
    half: TermHalf
    opens_on: dt.date | None
    closes_on: dt.date | None


class ClassCreate(BaseModel):
    name: Name = Field(description="As the school names it, e.g. Primary 4.")
    level_order: int = Field(
        ge=0,
        le=100,
        description="Display order only. Never a rank of pupils (R11).",
    )


class ClassRead(OrmModel):
    id: uuid.UUID
    name: str
    level_order: int
    is_active: bool


class HouseCreate(BaseModel):
    name: Name


class HouseRead(OrmModel):
    id: uuid.UUID
    name: str
