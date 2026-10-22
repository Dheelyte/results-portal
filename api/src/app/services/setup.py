"""Is this term ready for teachers to start? (ARCHITECTURE.md §7, §12)

`GET /setup-checklist?term_id=` is the one endpoint that answers milestone 5's
done-when — "an admin configures a full term from an empty database" — in a
way an admin can act on and a test can assert.

It exists because the alternative is discovering on results night that one
class has no class teacher. Every item names what is missing and in which
class, because "setup incomplete" generates a support call and a list does
not.

**Blocking versus advisory.** A blocking item stops teachers working at all: no
current session, no half terms, no column maxima, a class with no teacher. An
advisory item is a real gap that work can start without — an empty phrase bank
makes sixteen passages per pupil harder, it does not make them impossible.
Only blocking items decide `ready`.
"""

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import scope
from app.models import AssessmentPeriod, ClassTeacher, House, Term, TermHalf, User, UserRole
from app.services import academic, accounts, grading, marks, narrative, pupils, subjects
from app.services.support import all_of

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChecklistItem:
    """One line of the admin's setup page.

    `outstanding` names what is missing — the classes with no teacher, the
    subjects with nobody assigned. It is the difference between a checklist an
    admin can finish and one they ring HSD about.
    """

    key: str
    label: str
    done: bool
    blocking: bool
    detail: str
    outstanding: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Checklist:
    term_id: uuid.UUID
    term_label: str
    academic_session_id: uuid.UUID
    academic_session_name: str
    ready: bool
    items: list[ChecklistItem]

    @property
    def blocking_outstanding(self) -> list[str]:
        return [item.key for item in self.items if item.blocking and not item.done]


def _item(
    key: str,
    label: str,
    *,
    done: bool,
    blocking: bool,
    detail: str,
    outstanding: Sequence[str] = (),
) -> ChecklistItem:
    return ChecklistItem(
        key=key,
        label=label,
        done=done,
        blocking=blocking,
        detail=detail,
        outstanding=list(outstanding),
    )


async def term_readiness(db: AsyncSession, actor: User, term_id: uuid.UUID) -> Checklist:
    """Everything standing between this term and a teacher entering a score."""
    term = await academic.get_term(db, actor, term_id)
    session_record = await academic.get_session_record(db, actor, term.academic_session_id)
    session_id = session_record.id

    items: list[ChecklistItem] = [
        await _current_session(db, actor, session_record),
        _current_term(term),
        _term_calendar(term),
        *await _assessment_periods(db, actor, term),
        await _grading_scale(db, actor),
        *await _classes_and_houses(db, actor),
        *await _roll(db, actor, session_id),
        *await _offerings(db, actor, session_id),
        await _class_teachers(db, actor, session_id),
        await _narrative_sections(db, actor),
        await _phrase_bank(db, actor),
        await _teacher_accounts(db, actor),
        await _parent_accounts(db, actor),
    ]

    return Checklist(
        term_id=term.id,
        term_label=f"{term.number.value.title()} Term",
        academic_session_id=session_id,
        academic_session_name=session_record.name,
        ready=all(item.done for item in items if item.blocking),
        items=items,
    )


# ---------------------------------------------------------------------------
# The individual checks
# ---------------------------------------------------------------------------


async def _current_session(db: AsyncSession, actor: User, session_record) -> ChecklistItem:
    return _item(
        "current_session",
        "The session is the current one",
        done=session_record.is_current,
        blocking=True,
        detail=(
            f"{session_record.name} is current."
            if session_record.is_current
            else f"{session_record.name} is not the current session. Everything a teacher "
            "sees is scoped to the current session, so nobody can work in this term "
            "until it is."
        ),
    )


def _current_term(term: Term) -> ChecklistItem:
    return _item(
        "current_term",
        "The term is the current one",
        done=term.is_current,
        blocking=True,
        detail=(
            "This is the current term."
            if term.is_current
            else "This term is not marked current, so teachers will not be offered it."
        ),
    )


def _term_calendar(term: Term) -> ChecklistItem:
    done = term.times_school_opened is not None
    return _item(
        "times_school_opened",
        "Times the school opened is recorded",
        done=done,
        blocking=True,
        detail=(
            f"The school opened {term.times_school_opened} times."
            if done
            else "Not set. R9 measures every pupil's attendance against this number, so "
            "attendance cannot be recorded without it — and it prints on the card."
        ),
    )


async def _assessment_periods(db: AsyncSession, actor: User, term: Term) -> list[ChecklistItem]:
    periods = {
        period.half: period
        for period in await all_of(
            db,
            scope.scoped_assessment_periods(actor).where(AssessmentPeriod.term_id == term.id),
        )
    }
    missing = [half for half in TermHalf if half not in periods]

    items = [
        _item(
            "assessment_periods",
            "Both half terms exist",
            done=not missing,
            blocking=True,
            detail=(
                "First Half Term and Second Half Term are both present."
                if not missing
                else "A term has two sheets, each with its own columns (§1.1)."
            ),
            outstanding=[_half_label(half) for half in missing],
        )
    ]

    unconfigured: list[str] = []
    for half in TermHalf:
        period = periods.get(half)
        if period is None:
            unconfigured.append(_half_label(half))
            continue
        configured, classes_missing = await marks.sheet_configuration(db, actor, period)
        if configured:
            continue
        if classes_missing:
            unconfigured.extend(
                f"{_half_label(half)} — {class_name}" for class_name in classes_missing
            )
        else:
            unconfigured.append(_half_label(half))

    items.append(
        _item(
            "marks_obtainable",
            "Marks Obtainable is set for both sheets",
            done=not unconfigured,
            blocking=True,
            detail=(
                "Each sheet's column maxima are set."
                if not unconfigured
                else "Each column's maximum is what R1 validates a score against, and the "
                "row prints on the card. The school has not supplied these numbers "
                "yet — see N2."
            ),
            outstanding=unconfigured,
        )
    )
    return items


async def _grading_scale(db: AsyncSession, actor: User) -> ChecklistItem:
    scale = await grading.active_scale(db, actor)
    bands = [] if scale is None else await grading.bands_of(db, actor, scale.id)

    detail = "No grading scale is active."
    if scale is not None and bands:
        detail = f"{scale.name}, {len(bands)} bands."
    elif scale is not None:
        detail = f"{scale.name} has no bands, so no score resolves to a grade."

    return _item(
        "grading_scale",
        "A grading scale is active",
        done=scale is not None and bool(bands),
        blocking=True,
        detail=detail,
    )


async def _classes_and_houses(db: AsyncSession, actor: User) -> list[ChecklistItem]:
    classes = await academic.list_classes(db, actor)
    houses = await all_of(db, scope.scoped_houses(actor).with_only_columns(House.name))

    return [
        _item(
            "classes",
            "At least one class exists",
            done=bool(classes),
            blocking=True,
            detail=(
                f"{len(classes)} active {'class' if len(classes) == 1 else 'classes'}."
                if classes
                else "No active classes."
            ),
        ),
        _item(
            "houses",
            "Houses are set up",
            done=bool(houses),
            blocking=False,
            detail=(
                f"{len(houses)} {'house' if len(houses) == 1 else 'houses'}."
                if houses
                else "No houses. The card has a House field in its header, so it will print empty."
            ),
        ),
    ]


async def _roll(db: AsyncSession, actor: User, session_id: uuid.UUID) -> list[ChecklistItem]:
    enrolled = await pupils.count_enrolled_per_class(db, actor, academic_session_id=session_id)
    total_enrolled = sum(enrolled.values())
    unenrolled = await pupils.count_unenrolled(db, actor, academic_session_id=session_id)
    empty_classes = await pupils.classes_with_no_pupils(db, actor, academic_session_id=session_id)

    return [
        _item(
            "pupils_enrolled",
            "Pupils are enrolled",
            done=total_enrolled > 0,
            blocking=True,
            detail=(
                f"{total_enrolled} pupils enrolled this session."
                if total_enrolled
                else "Nobody is enrolled this session, so there is nothing to assess."
            ),
        ),
        _item(
            "every_pupil_placed",
            "Every pupil has a class",
            done=unenrolled == 0,
            blocking=False,
            detail=(
                "Every active pupil is enrolled."
                if unenrolled == 0
                else f"{unenrolled} active "
                f"{'pupil' if unenrolled == 1 else 'pupils'} have no place this session, "
                "so they appear in no class list and will get no report."
            ),
        ),
        _item(
            "no_empty_classes",
            "No class is empty",
            done=not empty_classes,
            blocking=False,
            detail=(
                "Every class has pupils."
                if not empty_classes
                else "These classes have nobody enrolled."
            ),
            outstanding=list(empty_classes),
        ),
    ]


async def _offerings(db: AsyncSession, actor: User, session_id: uuid.UUID) -> list[ChecklistItem]:
    classes = await academic.list_classes(db, actor)
    counts = await subjects.count_class_subjects(db, actor, academic_session_id=session_id)

    without_subjects = [klass.name for klass in classes if not counts.get(klass.id)]
    unassigned = await subjects.class_subjects_without_a_teacher(
        db, actor, academic_session_id=session_id
    )

    return [
        _item(
            "class_subjects",
            "Every class offers subjects",
            done=bool(classes) and not without_subjects,
            blocking=True,
            detail=(
                "Every class has a subject list."
                if classes and not without_subjects
                else "A class offering nothing has no score sheet."
            ),
            outstanding=without_subjects,
        ),
        _item(
            "teaching_assignments",
            "Every class subject has a teacher",
            done=not unassigned,
            blocking=True,
            detail=(
                "Every subject has somebody to enter its scores."
                if not unassigned
                else "Only the assigned teacher may enter scores for a class subject "
                "(§5.2), so an unassigned one can never be filled in."
            ),
            outstanding=[f"{class_name} — {subject}" for class_name, subject in unassigned],
        ),
    ]


async def _class_teachers(db: AsyncSession, actor: User, session_id: uuid.UUID) -> ChecklistItem:
    classes = await academic.list_classes(db, actor)
    assigned = {
        record.class_id
        for record in await all_of(
            db,
            scope.scoped_class_teachers(actor).where(
                ClassTeacher.academic_session_id == session_id
            ),
        )
    }
    missing = [klass.name for klass in classes if klass.id not in assigned]

    return _item(
        "class_teachers",
        "Every class has a class teacher",
        done=bool(classes) and not missing,
        blocking=True,
        detail=(
            "Every class has one."
            if classes and not missing
            else "The class teacher writes the narrative, records attendance and growth, "
            "writes the class teacher's comment and submits the class (§5.2). Without "
            "one, none of that can happen."
        ),
        outstanding=missing,
    )


async def _narrative_sections(db: AsyncSession, actor: User) -> ChecklistItem:
    count = await narrative.count_active_sections(db, actor)
    return _item(
        "narrative_sections",
        "Narrative sections are set up",
        done=count > 0,
        blocking=True,
        detail=(
            f"{count} active sections."
            if count
            else "No active sections, so the assessment pages of the card would be blank."
        ),
    )


async def _phrase_bank(db: AsyncSession, actor: User) -> ChecklistItem:
    by_scope = await narrative.count_comments_by_scope(db, actor)
    total = sum(by_scope.values())
    return _item(
        "comment_bank",
        "The phrase bank has entries",
        done=total > 0,
        blocking=False,
        detail=(
            f"{total} phrases across {len(by_scope)} sections."
            if total
            else "Empty. A class of thirty needs 480 written passages a term from one "
            "teacher (§4.6); without a phrase bank this is the feature that gets "
            "abandoned first."
        ),
    )


async def _teacher_accounts(db: AsyncSession, actor: User) -> ChecklistItem:
    count = await db.scalar(
        scope.scoped_users(actor)
        .with_only_columns(func.count(User.id))
        .where(User.role == UserRole.TEACHER, User.is_active.is_(True))
    )
    count = count or 0
    return _item(
        "teacher_accounts",
        "Teachers have accounts",
        done=count > 0,
        blocking=True,
        detail=(
            f"{count} active teacher {'account' if count == 1 else 'accounts'}."
            if count
            else "No teacher accounts, so there is nobody to assign a class or a subject to."
        ),
    )


async def _parent_accounts(db: AsyncSession, actor: User) -> ChecklistItem:
    orphans = await accounts.parents_without_children(db, actor)
    return _item(
        "parent_accounts",
        "Every parent account has a child attached",
        done=not orphans,
        blocking=False,
        detail=(
            "Every parent account has at least one child."
            if not orphans
            else "These accounts would sign in and see nothing. Parents are not needed "
            "until publication, so this does not block score entry."
        ),
        outstanding=[user.full_name for user in orphans],
    )


def _half_label(half: TermHalf) -> str:
    return "First Half Term" if half is TermHalf.FIRST_HALF else "Second Half Term"
