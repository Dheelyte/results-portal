"""SQLAlchemy models.

Every model module is imported here so that `Base.metadata` always sees the
whole schema — Alembic autogenerate works from this import and nothing else,
so a module missing from this list is a table missing from the next migration.

Milestone 2 defines the subset auth needs (§4.1, §4.9, §5.1). The rest of §4
arrives in milestone 3.
"""

from app.models.audit import AuditAction, AuditLog
from app.models.base import Base
from app.models.ids import uuid7
from app.models.school import School
from app.models.user import RefreshToken, User, UserRole, user_role_enum

__all__ = [
    "AuditAction",
    "AuditLog",
    "Base",
    "RefreshToken",
    "School",
    "User",
    "UserRole",
    "user_role_enum",
    "uuid7",
]
