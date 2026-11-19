"""The early-years progress report (docs/DECISIONS.md D128).

Preparatory, Nursery and Kindergarten don't get the scored card. Their class
teacher fills in the school's **Nursery Progress Report Form** instead: a
header (dominance, years in school) and some thirty written answers, under
five headings. There are no subjects, no scores and no halves: one report
per pupil per term, published through the same submit → approve → publish
path as every other class.

The written answers *are* narrative sections — the same table, the same
editor, the same completeness rule (R8) — tagged `report_type =
early_years`. A class sees only the sections of its own report type, which
is the whole of the separation.

**Headings.** A section's `group_label` is its heading on the form. Where the
form has a heading inside a heading ("III. Curriculum Areas", then "3.
Sensorial"), the two are joined with `HEADING_SEPARATOR` and the card prints
the outer one once and the inner one above its questions.
"""

import logging
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import scope
from app.models import (
    AuditAction,
    Class,
    ClassTermState,
    Dominance,
    NarrativeSection,
    Pupil,
    ReportType,
    Term,
    TermReport,
    User,
)
from app.services import audit, reports, workflow
from app.services.errors import Invalid, RowErrors
from app.services.support import all_of, one_or_404

logger = logging.getLogger(__name__)

HEADING_SEPARATOR = " — "

# "Years in School" is typed as the paper form is filled in: "2", "1½",
# "Second year". A short line on the card, not a paragraph.
MAX_YEARS_LENGTH = 30

DOMINANCE_LABELS = {
    Dominance.RIGHT: "Right",
    Dominance.LEFT: "Left",
    Dominance.NOT_ESTABLISHED: "Not Established",
}

_LEARNING = "I. Learning Style"
_SOCIAL = "II. Social Behaviour"
_CURRICULUM = "III. Curriculum Areas"
_DAILY = "1. Daily Living Activities"


def _under(outer: str, inner: str) -> str:
    return f"{outer}{HEADING_SEPARATOR}{inner}"


# The school's form, in its order (pasted 2026-11-18). Item I.1 was blank on
# the form and is left out, as the school asked; an admin can add a question
# there from the assessment page.
STANDARD_SECTIONS: tuple[tuple[str, str], ...] = (
    (_LEARNING, "What kind of activities will she/he do with friend(s)?"),
    (_LEARNING, "What kind of activities will she/he do with teacher(s)?"),
    (_LEARNING, "Describe child's organizational style when working with an activity."),
    (_LEARNING, "Describe child's internalization of work cycle."),
    (_LEARNING, "Describe and give examples of how child works with peers."),
    (_LEARNING, "Discuss child's general emotional state."),
    (_LEARNING, "Describe how child responds to stress."),
    (_LEARNING, "Describe how child responds to frustration."),
    (_LEARNING, "Describe how child responds to challenges."),
    (_under(_SOCIAL, "1. Peers"), "Parallel play"),
    (_under(_SOCIAL, "1. Peers"), "Leader, follower or both (gives & takes)"),
    (_under(_SOCIAL, "2. Adults"), "Follows directions"),
    (
        _under(_SOCIAL, "2. Adults"),
        "Relates informally (How does child initiate contact with adults?)",
    ),
    (_under(_CURRICULUM, _DAILY), "What activities does child choose to do?"),
    (_under(_CURRICULUM, _DAILY), "How does child work with these materials?"),
    (_under(_CURRICULUM, "2. Small Motor/Perceptual"), "What activities does child choose to do?"),
    (
        _under(_CURRICULUM, "2. Small Motor/Perceptual"),
        "How does child use (work with) these materials?",
    ),
    (_under(_CURRICULUM, "3. Sensorial"), "What activities does child choose to do?"),
    (_under(_CURRICULUM, "3. Sensorial"), "Can child replicate a classical presentation?"),
    (_under(_CURRICULUM, "3. Sensorial"), "Can child use materials conceptually?"),
    (_under(_CURRICULUM, "4. Mathematics"), "One to one correspondence"),
    (_under(_CURRICULUM, "4. Mathematics"), "Rote counting"),
    (_under(_CURRICULUM, "4. Mathematics"), "Number/numeral correspondence"),
    (
        _under(_CURRICULUM, "4. Mathematics"),
        "Operations (addition, subtraction, multiplication, division)",
    ),
    (
        _under(_CURRICULUM, "4. Mathematics"),
        "How child uses math in everyday activities, e.g. snack time",
    ),
    (_under(_CURRICULUM, "5. Language"), "Oral language"),
    (_under(_CURRICULUM, "5. Language"), "Writing development"),
    (_under(_CURRICULUM, "5. Language"), "Reading development"),
    (_under(_CURRICULUM, "5. Language"), "Phonemic abilities"),
    (
        _under(_CURRICULUM, "6. Art"),
        "How does child incorporate art media in his/her projects?",
    ),
    (_under(_CURRICULUM, "6. Art"), "How does child use (work with) these materials?"),
    (
        _under(_CURRICULUM, "7. Science/Nature"),
        "What themes or units has the child explored?",
    ),
    (_under(_CURRICULUM, "8. Large Motor Development"), "Areas of proficiency"),
    (_under(_CURRICULUM, "8. Large Motor Development"), "Problem areas"),
    ("IV. What Are Key Issues in This Child's Development", "Key issues"),
    ("V. What Are His/Her Strengths", "Strengths"),
)


def section_code(label: str, group_label: str | None, taken: set[str]) -> str:
    """A unique code for an early-years section: `EY.<slug>`.

    The early-years card prints no codes, so this only has to be unique in
    the school and recognisable in the audit log as early years.
    """
    text = f"{group_label or ''} {label}".lower()
    slug = "_".join(part for part in re.split(r"[^a-z0-9]+", text) if part)[:60] or "section"
    code, suffix = f"EY.{slug}", 2
    while code in taken:
        code, suffix = f"EY.{slug}_{suffix}", suffix + 1
    return code


async def ensure_standard_sections(db: AsyncSession, actor: User) -> int:
    """Create the form's sections if the school has no early-years sections.

    Called when a class is first set to early years. "No early-years
    sections at all", retired ones included: once a school has them, they
    are the admin's to edit, and putting back a question the admin retired
    would undo that.
    """
    existing = await db.scalar(
        scope.scoped_narrative_sections(actor)
        .where(NarrativeSection.report_type == ReportType.EARLY_YEARS)
        .limit(1)
    )
    if existing is not None:
        return 0

    taken = set(
        await all_of(
            db, scope.scoped_narrative_sections(actor).with_only_columns(NarrativeSection.code)
        )
    )
    for order, (group, label) in enumerate(STANDARD_SECTIONS):
        code = section_code(label, group, taken)
        taken.add(code)
        db.add(
            NarrativeSection(
                school_id=actor.school_id,
                code=code,
                label=label,
                group_label=group,
                display_order=order,
                report_type=ReportType.EARLY_YEARS,
            )
        )
    await db.flush()
    return len(STANDARD_SECTIONS)


async def report_type_of(db: AsyncSession, actor: User, class_id: uuid.UUID) -> ReportType:
    klass = await one_or_404(db, scope.scoped_classes(actor).where(Class.id == class_id), "class")
    return klass.report_type


# ---------------------------------------------------------------------------
# The form's header: dominance and years in school, per pupil per term
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DetailsInput:
    pupil_id: uuid.UUID
    dominance: Dominance | None
    years_in_school: str | None


@dataclass(frozen=True)
class ClassDetails:
    klass: Class
    term: Term
    pupils: Sequence[Pupil]
    reports: dict[uuid.UUID, TermReport]
    state: ClassTermState
    editable: bool


def refuse_unless_early_years(klass: Class) -> None:
    if klass.report_type is not ReportType.EARLY_YEARS:
        raise Invalid(
            f"{klass.name} gets the primary card, which has no dominance or years in school. "
            "An administrator sets a class's report type."
        )


async def class_details(
    db: AsyncSession, actor: User, *, class_id: uuid.UUID, term_id: uuid.UUID
) -> ClassDetails:
    """The class roll with each pupil's header lines so far."""
    found = await reports.class_comments(db, actor, class_id=class_id, term_id=term_id)
    refuse_unless_early_years(found.klass)
    return ClassDetails(
        klass=found.klass,
        term=found.term,
        pupils=found.pupils,
        reports=found.reports,
        state=found.state,
        editable=found.editable,
    )


async def save_class_details(
    db: AsyncSession,
    actor: User,
    *,
    class_id: uuid.UUID,
    term_id: uuid.UUID,
    rows: Sequence[DetailsInput],
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> ClassDetails:
    """Upsert dominance and years in school for a set of pupils, all or none.

    The class teacher's, like the comment (§5.2), and locked once the class
    is submitted (R14).
    """
    details = await class_details(db, actor, class_id=class_id, term_id=term_id)
    await reports.refuse_unless_class_teacher(
        db, actor, class_id=class_id, academic_session_id=details.term.academic_session_id
    )
    workflow.refuse_if_locked(details.state)

    known = {pupil.id for pupil in details.pupils}
    errors: dict[str, dict[str, str]] = {}
    for row in rows:
        if row.pupil_id not in known:
            errors[str(row.pupil_id)] = {
                "pupil_id": "This pupil is not in this class for this session."
            }
        elif row.years_in_school is not None and len(row.years_in_school) > MAX_YEARS_LENGTH:
            errors[str(row.pupil_id)] = {
                "years_in_school": (
                    f"Keep this under {MAX_YEARS_LENGTH} characters; it is one line on the card."
                )
            }
    if errors:
        raise RowErrors(
            f"{len(errors)} of {len(rows)} rows were rejected, so nothing was saved.", errors
        )

    for row in rows:
        report = details.reports.get(row.pupil_id) or await reports.ensure_report(
            db, actor, term=details.term, pupil_id=row.pupil_id, class_id=class_id
        )
        report.dominance = row.dominance
        report.years_in_school = (row.years_in_school or "").strip() or None

    await db.flush()
    await workflow.mark_in_progress(
        db, actor, class_id=class_id, term_id=term_id, ip_address=ip_address, user_agent=user_agent
    )
    await audit.record(
        db,
        school_id=actor.school_id,
        action=AuditAction.EARLY_YEARS_DETAILS_SAVED,
        entity_type="class",
        entity_id=class_id,
        actor_id=actor.id,
        # A count only, as for the comments: these are facts about named children.
        after={"term_id": str(term_id), "rows_saved": len(rows)},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()
    return await class_details(db, actor, class_id=class_id, term_id=term_id)


async def pupils_with_details(
    db: AsyncSession, actor: User, *, term_id: uuid.UUID, pupil_ids: Sequence[uuid.UUID]
) -> set[uuid.UUID]:
    """Pupils whose header is filled in: a dominance and a years-in-school line."""
    if not pupil_ids:
        return set()
    return set(
        await all_of(
            db,
            select(TermReport.pupil_id).where(
                TermReport.id.in_(
                    scope.scoped_term_reports(actor).with_only_columns(TermReport.id)
                ),
                TermReport.term_id == term_id,
                TermReport.pupil_id.in_(pupil_ids),
                TermReport.dominance.is_not(None),
                TermReport.years_in_school.is_not(None),
            ),
        )
    )
