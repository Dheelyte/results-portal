"""SQLAlchemy models.

Every model module is imported here so that `Base.metadata` always sees the
whole schema — Alembic autogenerate works from this import and nothing else,
so a module missing from this list is a table missing from the next migration.
A test asserts the models and the migrations agree.

This is the full schema of ARCHITECTURE.md §4, plus two additions recorded in
docs/DECISIONS.md: `refresh_tokens` (D17) and `narrative_section_assignments`
(D15).
"""

from app.models.academic import (
    AcademicSession,
    AssessmentPeriod,
    Class,
    Enrollment,
    Term,
    TermHalf,
    TermNumber,
    term_half_enum,
    term_number_enum,
)
from app.models.audit import AuditAction, AuditLog
from app.models.base import Base
from app.models.grading import GradeBand, GradingScale, Score
from app.models.ids import uuid7
from app.models.narrative import (
    CommentBank,
    NarrativeEntry,
    NarrativeSection,
    NarrativeSectionAssignment,
)
from app.models.people import GuardianPupil, House, Pupil
from app.models.result import MarksObtainable, ResultEntry
from app.models.school import School
from app.models.subject import ClassSubject, ClassTeacher, Subject, TeachingAssignment
from app.models.user import RefreshToken, User, UserRole, user_role_enum
from app.models.wellbeing import AttendanceRecord, GrowthRecord
from app.models.workflow import (
    ClassTermState,
    ClassTermStatus,
    PublicationState,
    TermReport,
    class_term_state_enum,
    publication_state_enum,
)

__all__ = [
    "AcademicSession",
    "AssessmentPeriod",
    "AttendanceRecord",
    "AuditAction",
    "AuditLog",
    "Base",
    "Class",
    "ClassSubject",
    "ClassTeacher",
    "ClassTermState",
    "ClassTermStatus",
    "CommentBank",
    "Enrollment",
    "GradeBand",
    "GradingScale",
    "GrowthRecord",
    "GuardianPupil",
    "House",
    "MarksObtainable",
    "NarrativeEntry",
    "NarrativeSection",
    "NarrativeSectionAssignment",
    "PublicationState",
    "Pupil",
    "RefreshToken",
    "ResultEntry",
    "School",
    "Score",
    "Subject",
    "TeachingAssignment",
    "Term",
    "TermHalf",
    "TermNumber",
    "TermReport",
    "User",
    "UserRole",
    "class_term_state_enum",
    "publication_state_enum",
    "term_half_enum",
    "term_number_enum",
    "user_role_enum",
    "uuid7",
]
