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

Writing the passages themselves is milestone 7. This module is the admin half:
the sections, their authorship and the phrases.
"""

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import scope
from app.models import (
    AuditAction,
    CommentBank,
    NarrativeSection,
    NarrativeSectionAssignment,
    User,
    UserRole,
)
from app.services import academic, audit
from app.services.errors import Invalid
from app.services.support import all_of, integrity_guard, one_or_404

logger = logging.getLogger(__name__)

SECTION_FIELDS = ("code", "label", "group_label", "display_order", "is_active")

# Comment bank scopes that are not a narrative section (§4.6): the two
# free-text comments in the card's footer.
FOOTER_SCOPES = frozenset({"class_teacher", "head_teacher"})


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
