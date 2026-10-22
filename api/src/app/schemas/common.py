"""Types shared across the request and response models.

Separate `Create`, `Update` and `Read` models everywhere (CLAUDE.md,
Conventions). An ORM model is never exposed directly, which is what keeps
`password_hash` off the wire by construction rather than by vigilance.
"""

import decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

# Every score and every column maximum is numeric(5,2) — never a float
# (CLAUDE.md, Conventions). Declared once so no endpoint can quietly widen it.
ScoreValue = Annotated[decimal.Decimal, Field(max_digits=5, decimal_places=2, ge=0)]

# Names typed by an admin. Bounded because they print on a report card and
# because an unbounded text field is a denial-of-service waiting to happen.
Name = Annotated[str, Field(min_length=1, max_length=200)]
ShortText = Annotated[str, Field(min_length=1, max_length=2000)]


class OrmModel(BaseModel):
    """Base for the read models, which are built from ORM instances."""

    model_config = ConfigDict(from_attributes=True)


class MessageResponse(BaseModel):
    detail: str
