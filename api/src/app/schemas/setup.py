"""The setup checklist (§7, §12)."""

import uuid

from pydantic import BaseModel, Field


class ChecklistItemRead(BaseModel):
    key: str
    label: str
    done: bool
    blocking: bool = Field(
        description=(
            "A blocking item stops teachers working at all. An advisory one is a real "
            "gap that work can start without."
        )
    )
    detail: str
    outstanding: list[str] = Field(
        default_factory=list,
        description="What is missing, named — the classes with no teacher, and so on.",
    )


class ChecklistRead(BaseModel):
    term_id: uuid.UUID
    term_label: str
    academic_session_id: uuid.UUID
    academic_session_name: str
    ready: bool = Field(description="True when every blocking item is done.")
    items: list[ChecklistItemRead]
