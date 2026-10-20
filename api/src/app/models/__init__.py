"""SQLAlchemy declarative base.

Milestone 1 defines no tables.  `Base.metadata` exists so Alembic has a stable
autogenerate target from the first migration onward; milestone 3 fills it with
the schema of ARCHITECTURE.md §4, importing each model module here so that
`Base.metadata` always sees the whole schema.
"""

from app.models.base import Base

__all__ = ["Base"]
