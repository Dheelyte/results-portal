"""Grading scales and their bands (§4.5).

Scales are versioned and never edited in place, so there is no update model
here on purpose: the school's answer to N1 arrives as a new scale.
"""

import datetime as dt
import uuid

from pydantic import BaseModel, Field

from app.schemas.common import Name, OrmModel, ScoreValue


class GradeBandWrite(BaseModel):
    letter: str = Field(min_length=1, max_length=10, examples=["A+"])
    remark: str = Field(min_length=1, max_length=100, examples=["Excellence"])
    min_score: ScoreValue
    max_score: ScoreValue


class GradeBandRead(OrmModel):
    id: uuid.UUID
    letter: str
    remark: str
    min_score: ScoreValue
    max_score: ScoreValue
    sort_order: int


class GradingScaleCreate(BaseModel):
    name: Name = Field(examples=["Card scale (seven bands)"])
    effective_from: dt.date
    bands: list[GradeBandWrite] = Field(
        min_length=1,
        description=(
            "Must not overlap and must cover every mark from 0 to 100, so that "
            "every average resolves to exactly one grade."
        ),
    )
    activate: bool = Field(
        default=False, description="Make this the active scale, deactivating any other."
    )


class GradingScaleRead(OrmModel):
    id: uuid.UUID
    name: str
    effective_from: dt.date
    is_active: bool
    created_at: dt.datetime
    bands: list[GradeBandRead] = Field(default_factory=list)
