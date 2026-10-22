"""The Marks Obtainable row (§4.4).

Every column is optional and nothing has a default. **N2 is unanswered** — the
row is blank on both photographed cards — so a default here would be this
system inventing the school's marking scheme.
"""

import uuid

from pydantic import BaseModel, Field

from app.schemas.common import OrmModel, ScoreValue


class MarksObtainableSave(BaseModel):
    """One sheet's column maxima.

    `class_id = null` sets the school-wide row. A class's own row overrides it
    entirely for that class — R1 resolves "per-class row if present, otherwise
    the school-wide row", so there is no partial override.

    The sheet's own columns only: the first-half sheet has Mid Term Test and
    no Exam, the second-half sheet the reverse (§1.2).
    """

    class_id: uuid.UUID | None = Field(
        default=None, description="null for every class; a class id to override one class."
    )
    ca_test_1: ScoreValue | None = None
    ca_test_2: ScoreValue | None = None
    ca_test_3: ScoreValue | None = None
    ca_test_4: ScoreValue | None = None
    ca_test_5: ScoreValue | None = None
    mid_term_test: ScoreValue | None = Field(default=None, description="First half term only.")
    exam: ScoreValue | None = Field(default=None, description="Second half term only.")

    def column_values(self) -> dict[str, ScoreValue | None]:
        return self.model_dump(exclude={"class_id"})


class MarksObtainableRead(OrmModel):
    id: uuid.UUID
    assessment_period_id: uuid.UUID
    class_id: uuid.UUID | None
    ca_test_1: ScoreValue | None
    ca_test_2: ScoreValue | None
    ca_test_3: ScoreValue | None
    ca_test_4: ScoreValue | None
    ca_test_5: ScoreValue | None
    mid_term_test: ScoreValue | None
    exam: ScoreValue | None
