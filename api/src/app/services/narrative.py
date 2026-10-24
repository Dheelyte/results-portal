"""Narrative sections, who writes them, and the phrase bank
(ARCHITECTURE.md §1.4, §4.6).

Sixteen written passages per pupil per term — seven curriculum areas under
"Area of Curriculum", then B through J (D27 corrected an earlier count of
seventeen). For a class of thirty that is **480 passages** falling to one
class teacher, which is why §4.6 calls the comment bank core rather than
optional, and why this module manages it in the same place as the sections it
is scoped to.

Authorship is data, not code (B1, D15): a section may be assigned to a
specialist for a given class, and where no assignment exists the class teacher
writes it. That default is what keeps the common case free of configuration —
`policy.can_write_narrative` needs no list of which sections are specialist.

Two halves, in one module because they are the same subject matter: the admin
half — sections, authorship, phrases — and from milestone 7 the writing
itself, below the second rule.
"""

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import policy, scope
from app.models import (
    AuditAction,
    Class,
    ClassTermState,
    CommentBank,
    Enrollment,
    NarrativeEntry,
    NarrativeSection,
    NarrativeSectionAssignment,
    Pupil,
    Term,
    User,
    UserRole,
)
from app.services import academic, audit, results, workflow
from app.services.errors import Invalid, NotFound, RowErrors
from app.services.support import all_of, integrity_guard, one_or_404, rows_of

logger = logging.getLogger(__name__)

SECTION_FIELDS = ("code", "label", "group_label", "display_order", "is_active")

# Comment bank scopes that are not a narrative section (§4.6): the two
# free-text comments in the card's footer.
FOOTER_SCOPES = frozenset({"class_teacher", "head_teacher"})

# A ceiling on one passage, so a section cannot become a document the card
# has no room for. Not in the specification: the card's assessment pages give
# each section a few lines, and §9's layout has to fit sixteen of them on two
# pages (§14 A20). Generous rather than tight — the limit exists to catch a
# paste accident, not to ration what a teacher says about a child.
MAX_PASSAGE_LENGTH = 2000


@dataclass(frozen=True)
class SectionInput:
    code: str
    label: str
    group_label: str | None
    display_order: int
    is_active: bool


async def list_sections(
    db: AsyncSession, actor: User, *, include_inactive: bool = True
) -> Sequence[NarrativeSection]:
    stmt = scope.scoped_narrative_sections(actor)
    if not include_inactive:
        stmt = stmt.where(NarrativeSection.is_active.is_(True))
    return await all_of(db, stmt.order_by(NarrativeSection.display_order))


async def save_sections(
    db: AsyncSession,
    actor: User,
    *,
    sections: Sequence[SectionInput],
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> Sequence[NarrativeSection]:
    """Upsert the card's narrative sections, keyed on `code`.

    A bulk PUT, because reordering is the common edit and one section's order
    only means anything relative to the others.

    Sections are retired with `is_active = false`, never deleted: a term's
    `narrative_entries` point at them, and last term's card has to keep saying
    what it said. N7 may yet reduce the sixteen, and this is how — without a
    migration and without losing history.
    """
    if not sections:
        raise Invalid("Send at least one section.")

    codes = [section.code.strip() for section in sections]
    if "" in codes:
        raise Invalid("Every section needs a code.")
    duplicates = sorted({code for code in codes if codes.count(code) > 1})
    if duplicates:
        raise Invalid(f"Section code {', '.join(duplicates)} appears twice.")

    for section in sections:
        if not section.label.strip():
            raise Invalid(f"Section {section.code} needs a label — it prints on the card.")

    existing = {record.code: record for record in await list_sections(db, actor)}
    before = {code: audit.snapshot(record, SECTION_FIELDS) for code, record in existing.items()}

    for section in sections:
        code = section.code.strip()
        record = existing.get(code)
        if record is None:
            record = NarrativeSection(
                school_id=actor.school_id, code=code, label="", display_order=0
            )
            db.add(record)
        record.label = section.label.strip()
        record.group_label = (section.group_label or "").strip() or None
        record.display_order = section.display_order
        record.is_active = section.is_active

    async with integrity_guard(db, "Two sections cannot share a code."):
        await db.flush()

    await audit.record(
        db,
        school_id=actor.school_id,
        actor_id=actor.id,
        action=AuditAction.NARRATIVE_SECTIONS_SAVED,
        entity_type="narrative_section",
        before={"sections": before},
        after={
            "sections": {
                section.code.strip(): {
                    "label": section.label.strip(),
                    "display_order": section.display_order,
                    "is_active": section.is_active,
                }
                for section in sections
            }
        },
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()
    return await list_sections(db, actor)


async def count_active_sections(db: AsyncSession, actor: User) -> int:
    return (
        await db.scalar(
            scope.scoped_narrative_sections(actor)
            .with_only_columns(func.count(NarrativeSection.id))
            .where(NarrativeSection.is_active.is_(True))
        )
        or 0
    )


# ---------------------------------------------------------------------------
# Who writes which section, for one class
# ---------------------------------------------------------------------------


async def list_assignments(
    db: AsyncSession,
    actor: User,
    class_id: uuid.UUID,
    *,
    academic_session_id: uuid.UUID | None = None,
) -> Sequence[NarrativeSectionAssignment]:
    await academic.get_class(db, actor, class_id)
    session_id = await academic.resolve_session_id(db, actor, academic_session_id)
    return await all_of(
        db,
        scope.scoped_narrative_section_assignments(actor).where(
            NarrativeSectionAssignment.class_id == class_id,
            NarrativeSectionAssignment.academic_session_id == session_id,
        ),
    )


async def set_assignments(
    db: AsyncSession,
    actor: User,
    class_id: uuid.UUID,
    *,
    assignments: dict[uuid.UUID, uuid.UUID | None],
    academic_session_id: uuid.UUID | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> Sequence[NarrativeSectionAssignment]:
    """Hand named sections of one class's card to named teachers (D15).

    A teacher of `None` **removes** the assignment, which is not the same as
    assigning nobody: by D15, absence of a row means the class teacher writes
    that section. That is the default the school gets without configuring
    anything, so clearing an assignment has to be expressible.

    Not in §7's list, which predates B1 being answered. Recorded in
    docs/DECISIONS.md.
    """
    await academic.get_class(db, actor, class_id)
    session_id = await academic.resolve_session_id(db, actor, academic_session_id)

    known = {
        section.id
        for section in await all_of(
            db,
            scope.scoped_narrative_sections(actor).where(
                NarrativeSection.id.in_(list(assignments))
            ),
        )
    }
    unknown = set(assignments) - known
    if unknown:
        raise Invalid("One or more of those narrative sections does not exist.")

    for teacher_user_id in assignments.values():
        if teacher_user_id is not None:
            teacher = await one_or_404(
                db, scope.scoped_users(actor).where(User.id == teacher_user_id), "user"
            )
            if teacher.role is not UserRole.TEACHER:
                raise Invalid(
                    f"{teacher.full_name} is not a teacher, so cannot be given a section to write."
                )

    existing = {
        record.section_id: record
        for record in await list_assignments(db, actor, class_id, academic_session_id=session_id)
    }
    before = {
        str(section_id): str(record.teacher_user_id) for section_id, record in existing.items()
    }

    for section_id, teacher_user_id in assignments.items():
        record = existing.get(section_id)
        if teacher_user_id is None:
            if record is not None:
                await db.delete(record)
            continue
        if record is None:
            record = NarrativeSectionAssignment(
                school_id=actor.school_id,
                class_id=class_id,
                section_id=section_id,
                academic_session_id=session_id,
                teacher_user_id=teacher_user_id,
            )
            db.add(record)
        else:
            record.teacher_user_id = teacher_user_id

    async with integrity_guard(db, "That section is already assigned for this class."):
        await db.flush()

    await audit.record(
        db,
        school_id=actor.school_id,
        actor_id=actor.id,
        action=AuditAction.NARRATIVE_ASSIGNMENTS_SET,
        entity_type="class",
        entity_id=class_id,
        before={"assignments": before},
        after={
            "assignments": {
                str(section_id): (None if teacher is None else str(teacher))
                for section_id, teacher in assignments.items()
            }
        },
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()
    return await list_assignments(db, actor, class_id, academic_session_id=session_id)


# ---------------------------------------------------------------------------
# The phrase bank
# ---------------------------------------------------------------------------


async def list_comments(
    db: AsyncSession,
    actor: User,
    *,
    comment_scope: str | None = None,
    include_inactive: bool = True,
) -> Sequence[CommentBank]:
    stmt = scope.scoped_comment_bank(actor)
    if comment_scope is not None:
        stmt = stmt.where(CommentBank.scope == comment_scope)
    if not include_inactive:
        stmt = stmt.where(CommentBank.is_active.is_(True))
    return await all_of(db, stmt.order_by(CommentBank.scope, CommentBank.text))


async def create_comment(
    db: AsyncSession,
    actor: User,
    *,
    comment_scope: str,
    text: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> CommentBank:
    """Add a phrase, scoped to one narrative section or to a footer comment.

    §4.6: "scope its entries to each section so the suggestions are
    relevant". A bank of three hundred generic phrases is a bank nobody
    scrolls through, so the scope is checked against the sections that
    actually exist rather than accepted as free text.
    """
    comment_scope = comment_scope.strip()
    text = text.strip()

    if not text:
        raise Invalid("A phrase cannot be empty.")

    if comment_scope not in FOOTER_SCOPES:
        known = await db.scalar(
            scope.scoped_narrative_sections(actor).where(NarrativeSection.code == comment_scope)
        )
        if known is None:
            raise Invalid(
                f"{comment_scope!r} is not a narrative section code. Use a section's code, "
                "or 'class_teacher' or 'head_teacher' for the footer comments."
            )

    record = CommentBank(school_id=actor.school_id, scope=comment_scope, text=text)
    db.add(record)

    async with integrity_guard(db, "That phrase could not be saved."):
        await db.flush()

    await audit.record(
        db,
        school_id=actor.school_id,
        actor_id=actor.id,
        action=AuditAction.COMMENT_BANK_ENTRY_CREATED,
        entity_type="comment_bank",
        entity_id=record.id,
        after={"scope": record.scope},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()
    await db.refresh(record)
    return record


async def count_comments_by_scope(db: AsyncSession, actor: User) -> dict[str, int]:
    stmt = (
        scope.scoped_comment_bank(actor)
        .with_only_columns(CommentBank.scope, func.count(CommentBank.id))
        .where(CommentBank.is_active.is_(True))
        .group_by(CommentBank.scope)
    )
    return {row[0]: row[1] for row in (await db.execute(stmt)).all()}


# ---------------------------------------------------------------------------
# Writing the passages (milestone 7, §8.2, R8)
# ---------------------------------------------------------------------------
#
# §8.2 is blunt about the shape of this: "This is the heaviest task in the
# system — sixteen passages per pupil, 480 for a class of 30 — and it belongs
# to one person, the class teacher." Everything below is arranged around
# working **pupil by pupil**, because that is what the screen does.


@dataclass(frozen=True)
class PassageInput:
    """One section's text as submitted. Absent sections are left alone."""

    section_id: uuid.UUID
    body: str | None


@dataclass(frozen=True)
class Passage:
    """One section of one pupil's narrative, ready to render."""

    section: NarrativeSection
    entry: NarrativeEntry | None
    # False when this section belongs to somebody else for this class (D15).
    writable: bool

    @property
    def is_complete(self) -> bool:
        """R8: complete means a non-empty body."""
        return bool(self.entry is not None and (self.entry.body or "").strip())


@dataclass(frozen=True)
class PupilNarrative:
    """One pupil's page, with the navigation §8.2 asks for."""

    pupil: Pupil
    klass: Class
    term: Term
    passages: list[Passage]
    state: ClassTermState
    editable: bool
    previous_pupil_id: uuid.UUID | None
    next_pupil_id: uuid.UUID | None
    position: int
    roll_size: int

    @property
    def complete_count(self) -> int:
        return sum(1 for passage in self.passages if passage.is_complete)


@dataclass(frozen=True)
class PupilProgress:
    """One line of the class list: how far this pupil's narrative has got."""

    pupil_id: uuid.UUID
    admission_number: str
    first_name: str
    middle_name: str | None
    last_name: str
    written: int
    total: int

    @property
    def is_complete(self) -> bool:
        return self.total > 0 and self.written >= self.total


@dataclass(frozen=True)
class ClassNarrative:
    """The class list §8.2 wants: "12 of 30 pupils complete"."""

    klass: Class
    term: Term
    sections: list[NarrativeSection]
    writable_section_ids: list[uuid.UUID]
    pupils: list[PupilProgress]
    state: ClassTermState
    editable: bool

    @property
    def complete_pupils(self) -> int:
        return sum(1 for pupil in self.pupils if pupil.is_complete)


async def _class_and_term(
    db: AsyncSession, actor: User, class_id: uuid.UUID, term_id: uuid.UUID
) -> tuple[Class, Term]:
    klass = await one_or_404(db, scope.scoped_classes(actor).where(Class.id == class_id), "class")
    term = await one_or_404(db, scope.scoped_terms(actor).where(Term.id == term_id), "term")
    return klass, term


async def active_sections(db: AsyncSession, actor: User) -> Sequence[NarrativeSection]:
    """The sections in card order. Inactive ones are not part of R8."""
    return await all_of(
        db,
        scope.scoped_narrative_sections(actor)
        .where(NarrativeSection.is_active.is_(True))
        .order_by(NarrativeSection.display_order),
    )


async def class_narrative(
    db: AsyncSession, actor: User, *, class_id: uuid.UUID, term_id: uuid.UUID
) -> ClassNarrative:
    """The class roll with each pupil's progress through the sixteen sections."""
    klass, term = await _class_and_term(db, actor, class_id, term_id)
    sections = list(await active_sections(db, actor))
    section_ids = [section.id for section in sections]

    writable = await policy.writable_narrative_sections(
        db, actor, class_id, term.academic_session_id
    )

    pupils = await results.pupils_of(
        db, actor, class_id=class_id, academic_session_id=term.academic_session_id
    )

    # One query for the whole class rather than one per pupil: thirty round
    # trips to paint a progress list is the kind of thing that makes a screen
    # unusable on a phone (§8.1's assumptions apply here too).
    written = dict(
        await rows_of(
            db,
            select(NarrativeEntry.pupil_id, func.count())
            .where(
                NarrativeEntry.id.in_(
                    scope.scoped_narrative_entries(
                        actor, term.academic_session_id
                    ).with_only_columns(NarrativeEntry.id)
                ),
                NarrativeEntry.term_id == term.id,
                NarrativeEntry.section_id.in_(section_ids),
                func.btrim(func.coalesce(NarrativeEntry.body, "")) != "",
            )
            .group_by(NarrativeEntry.pupil_id),
        )
    )

    state = await workflow.state_of(db, actor, class_id=class_id, term_id=term.id)

    return ClassNarrative(
        klass=klass,
        term=term,
        sections=sections,
        writable_section_ids=[section.id for section in sections if section.id in writable],
        pupils=[
            PupilProgress(
                pupil_id=pupil.id,
                admission_number=pupil.admission_number,
                first_name=pupil.first_name,
                middle_name=pupil.middle_name,
                last_name=pupil.last_name,
                written=written.get(pupil.id, 0),
                total=len(sections),
            )
            for pupil in pupils
        ],
        state=state,
        editable=workflow.teacher_may_edit(state),
    )


async def _enrolled_class_of(
    db: AsyncSession, actor: User, *, pupil_id: uuid.UUID, academic_session_id: uuid.UUID
) -> Class:
    """The class this pupil is in, within the caller's scope.

    The narrative is keyed on pupil and term, but authorship is per class
    (D15), so the class has to be resolved before anything can be written.
    """
    visible = scope.scoped_pupils(actor, academic_session_id).with_only_columns(Pupil.id)
    klass = await db.scalar(
        select(Class)
        .join(Enrollment, Enrollment.class_id == Class.id)
        .where(
            Enrollment.pupil_id == pupil_id,
            Enrollment.pupil_id.in_(visible),
            Enrollment.academic_session_id == academic_session_id,
        )
    )
    if klass is None:
        raise NotFound("No such pupil in your classes for this session.")
    return klass


async def pupil_narrative(
    db: AsyncSession, actor: User, *, pupil_id: uuid.UUID, term_id: uuid.UUID
) -> PupilNarrative:
    """One pupil's sixteen sections, with previous/next for the next pupil."""
    term = await one_or_404(db, scope.scoped_terms(actor).where(Term.id == term_id), "term")
    klass = await _enrolled_class_of(
        db, actor, pupil_id=pupil_id, academic_session_id=term.academic_session_id
    )

    sections = list(await active_sections(db, actor))
    writable = await policy.writable_narrative_sections(
        db, actor, klass.id, term.academic_session_id
    )

    entries = {
        entry.section_id: entry
        for entry in await all_of(
            db,
            scope.scoped_narrative_entries(actor, term.academic_session_id)
            .where(
                NarrativeEntry.term_id == term.id,
                NarrativeEntry.pupil_id == pupil_id,
            )
            .execution_options(populate_existing=True),
        )
    }

    # The roll drives §8.2's previous/next, and it is the *active* roll —
    # `pupils_of` filters on `is_active`. A pupil who has since been withdrawn
    # is still enrolled for the session, so their page must open (the term's
    # narrative is part of their record) but they sit outside the navigation.
    roll = list(
        await results.pupils_of(
            db, actor, class_id=klass.id, academic_session_id=term.academic_session_id
        )
    )
    ids = [pupil.id for pupil in roll]

    if pupil_id in ids:
        index = ids.index(pupil_id)
        pupil = roll[index]
    else:
        index = -1
        pupil = await one_or_404(
            db, scope.scoped_pupils(actor).where(Pupil.id == pupil_id), "pupil"
        )

    state = await workflow.state_of(db, actor, class_id=klass.id, term_id=term.id)

    return PupilNarrative(
        pupil=pupil,
        klass=klass,
        term=term,
        passages=[
            Passage(
                section=section,
                entry=entries.get(section.id),
                writable=section.id in writable,
            )
            for section in sections
        ],
        state=state,
        editable=workflow.teacher_may_edit(state),
        previous_pupil_id=ids[index - 1] if index > 0 else None,
        next_pupil_id=ids[index + 1] if 0 <= index < len(ids) - 1 else None,
        position=index + 1 if index >= 0 else 0,
        roll_size=len(ids),
    )


async def save_pupil_narrative(
    db: AsyncSession,
    actor: User,
    *,
    pupil_id: uuid.UUID,
    term_id: uuid.UUID,
    passages: Sequence[PassageInput],
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> PupilNarrative:
    """Upsert a set of passages, all or none.

    Per-section refusals, keyed by section id, for the same reason the score
    grid gets them per cell: a specialist's section sitting in the class
    teacher's draft must say *which* section was refused, not merely that
    something was.
    """
    term = await one_or_404(db, scope.scoped_terms(actor).where(Term.id == term_id), "term")
    klass = await _enrolled_class_of(
        db, actor, pupil_id=pupil_id, academic_session_id=term.academic_session_id
    )

    state = await workflow.state_of(db, actor, class_id=klass.id, term_id=term.id)
    workflow.refuse_if_locked(state)

    sections = {section.id: section for section in await active_sections(db, actor)}
    writable = await policy.writable_narrative_sections(
        db, actor, klass.id, term.academic_session_id
    )

    errors: dict[str, dict[str, str]] = {}
    for passage in passages:
        key = str(passage.section_id)
        if passage.section_id not in sections:
            errors[key] = {"section_id": "That section is not part of this card."}
        elif passage.section_id not in writable:
            # Names the section, which is the school's own configuration, and
            # no pupil (CLAUDE.md).
            errors[key] = {
                "section_id": (
                    f"{sections[passage.section_id].label} is written by another teacher "
                    "for this class."
                )
            }
        elif passage.body is not None and len(passage.body) > MAX_PASSAGE_LENGTH:
            errors[key] = {
                "body": (
                    f"{sections[passage.section_id].label} is longer than "
                    f"{MAX_PASSAGE_LENGTH} characters, which will not fit on the card."
                )
            }

    if errors:
        raise RowErrors(
            f"{len(errors)} of {len(passages)} sections were rejected, so nothing was saved.",
            errors,
        )

    existing = {
        entry.section_id: entry
        for entry in await all_of(
            db,
            scope.scoped_narrative_entries(actor, term.academic_session_id).where(
                NarrativeEntry.term_id == term.id, NarrativeEntry.pupil_id == pupil_id
            ),
        )
    }

    created = 0
    for passage in passages:
        entry = existing.get(passage.section_id)
        if entry is None:
            entry = NarrativeEntry(
                school_id=actor.school_id,
                term_id=term.id,
                pupil_id=pupil_id,
                section_id=passage.section_id,
            )
            db.add(entry)
            created += 1
        # Stored as typed, apart from trailing whitespace: the body is printed
        # on the card and a stray newline shows.
        entry.body = None if passage.body is None else passage.body.rstrip()
        entry.written_by = actor.id

    await db.flush()
    await workflow.mark_in_progress(
        db,
        actor,
        class_id=klass.id,
        term_id=term.id,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    await audit.record(
        db,
        school_id=actor.school_id,
        action=AuditAction.NARRATIVE_SAVED,
        entity_type="pupil",
        entity_id=pupil_id,
        actor_id=actor.id,
        # Counts and section codes only. A narrative passage is a comment
        # about a named child, and CLAUDE.md forbids both from a log.
        after={
            "term_id": str(term.id),
            "sections_saved": len(passages),
            "sections_created": created,
            "codes": sorted(sections[p.section_id].code for p in passages),
        },
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()

    return await pupil_narrative(db, actor, pupil_id=pupil_id, term_id=term_id)


async def narrative_is_complete(
    db: AsyncSession, actor: User, *, pupil_id: uuid.UUID, term_id: uuid.UUID
) -> bool:
    """R8: every active section has a non-empty body."""
    total = await count_active_sections(db, actor)
    if total == 0:
        return False

    written = await db.scalar(
        select(func.count()).where(
            NarrativeEntry.id.in_(
                scope.scoped_narrative_entries(actor).with_only_columns(NarrativeEntry.id)
            ),
            NarrativeEntry.term_id == term_id,
            NarrativeEntry.pupil_id == pupil_id,
            func.btrim(func.coalesce(NarrativeEntry.body, "")) != "",
        )
    )
    return (written or 0) >= total
