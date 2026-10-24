"""The term report's own fields (ARCHITECTURE.md §4.8, §1.6).

`term_reports` is the publication unit, and it carries the parts of the card
that belong to no subject and no section: the class teacher's comment, the
head teacher's remark, the position text and the promotion decision.

Milestone 7 needs the first of those. The rest arrive with review and
approval in milestone 9, and they belong here when they do — one module for
"the fields on the report itself" rather than each one landing wherever its
endpoint happened to be built (docs/DECISIONS.md D56).

Two rules already apply and are enforced below:

- **R11.** Position is never computed. `position_text` is free text, and
  nothing in this module or anywhere else ranks a pupil.
- **R14.** A submitted or approved class is read-only for teachers.
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
    Pupil,
    Term,
    TermReport,
    User,
)
from app.services import audit, results, workflow
from app.services.errors import NotPermitted, RowErrors
from app.services.support import all_of, one_or_404

logger = logging.getLogger(__name__)

# The card gives the class teacher's comment a few lines, not a page.
# Not in the specification — see §14 A20, the same reasoning as a narrative
# passage's ceiling.
MAX_COMMENT_LENGTH = 1000


@dataclass(frozen=True)
class CommentInput:
    pupil_id: uuid.UUID
    comment: str | None


@dataclass(frozen=True)
class ClassComments:
    klass: Class
    term: Term
    pupils: Sequence[Pupil]
    reports: dict[uuid.UUID, TermReport]
    state: ClassTermState
    editable: bool


async def _ensure_report(
    db: AsyncSession, actor: User, *, term: Term, pupil_id: uuid.UUID, class_id: uuid.UUID
) -> TermReport:
    """The pupil's report for this term, created if it does not exist yet.

    A report row is bookkeeping rather than a decision: it exists from the
    moment anybody writes anything about the pupil, and `state` keeps it a
    draft until an admin publishes it (R12).
    """
    report = await db.scalar(
        scope.scoped_term_reports(actor).where(
            TermReport.term_id == term.id, TermReport.pupil_id == pupil_id
        )
    )
    if report is None:
        report = TermReport(
            school_id=actor.school_id, term_id=term.id, pupil_id=pupil_id, class_id=class_id
        )
        db.add(report)
        await db.flush()
    return report


async def _refuse_unless_class_teacher(
    db: AsyncSession, actor: User, *, class_id: uuid.UUID, academic_session_id: uuid.UUID
) -> None:
    """§5.2: these three belong to the class teacher and nobody else.

    A subject teacher of the same class may **read** the page — they can see
    the class, and seeing it is how they know whose attendance is missing —
    but recording it is not theirs. A 403 rather than a 404 because the class
    is already in their scope: there is nothing left to conceal, and saying
    which relationship is missing is more use than pretending the class does
    not exist.
    """
    if await policy.is_class_teacher_of(db, actor, class_id, academic_session_id):
        return
    raise NotPermitted(
        "Only the class teacher records this for a class. "
        "If you should be the class teacher, an administrator sets that."
    )


async def class_comments(
    db: AsyncSession, actor: User, *, class_id: uuid.UUID, term_id: uuid.UUID
) -> ClassComments:
    """The class roll with whatever comment each pupil has so far."""
    klass = await one_or_404(db, scope.scoped_classes(actor).where(Class.id == class_id), "class")
    term = await one_or_404(db, scope.scoped_terms(actor).where(Term.id == term_id), "term")

    pupils = await results.pupils_of(
        db, actor, class_id=class_id, academic_session_id=term.academic_session_id
    )
    reports = {
        report.pupil_id: report
        for report in await all_of(
            db,
            scope.scoped_term_reports(actor, term.academic_session_id)
            .where(
                TermReport.term_id == term.id,
                TermReport.pupil_id.in_([pupil.id for pupil in pupils]),
            )
            .execution_options(populate_existing=True),
        )
    }
    state = await workflow.state_of(db, actor, class_id=class_id, term_id=term.id)

    return ClassComments(
        klass=klass,
        term=term,
        pupils=pupils,
        reports=reports,
        state=state,
        editable=workflow.teacher_may_edit(state),
    )


async def save_class_comments(
    db: AsyncSession,
    actor: User,
    *,
    class_id: uuid.UUID,
    term_id: uuid.UUID,
    rows: Sequence[CommentInput],
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> ClassComments:
    """Upsert the class teacher's comment for a set of pupils, all or none."""
    comments = await class_comments(db, actor, class_id=class_id, term_id=term_id)
    await _refuse_unless_class_teacher(
        db, actor, class_id=class_id, academic_session_id=comments.term.academic_session_id
    )
    workflow.refuse_if_locked(comments.state)

    known = {pupil.id for pupil in comments.pupils}
    errors: dict[str, dict[str, str]] = {}
    for row in rows:
        if row.pupil_id not in known:
            errors[str(row.pupil_id)] = {
                "pupil_id": "This pupil is not in this class for this session."
            }
        elif row.comment is not None and len(row.comment) > MAX_COMMENT_LENGTH:
            errors[str(row.pupil_id)] = {
                "comment": (
                    f"The comment is longer than {MAX_COMMENT_LENGTH} characters, "
                    "which will not fit on the card."
                )
            }

    if errors:
        raise RowErrors(
            f"{len(errors)} of {len(rows)} comments were rejected, so nothing was saved.",
            errors,
        )

    written = 0
    for row in rows:
        report = comments.reports.get(row.pupil_id) or await _ensure_report(
            db, actor, term=comments.term, pupil_id=row.pupil_id, class_id=class_id
        )
        report.class_teacher_comment = None if row.comment is None else row.comment.rstrip()
        written += 1

    await db.flush()
    await workflow.mark_in_progress(
        db,
        actor,
        class_id=class_id,
        term_id=term_id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await audit.record(
        db,
        school_id=actor.school_id,
        action=AuditAction.CLASS_TEACHER_COMMENTS_SAVED,
        entity_type="class",
        entity_id=class_id,
        actor_id=actor.id,
        # A count, never the text: the comment is written about a named child.
        after={"term_id": str(term_id), "comments_saved": written},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()

    return await class_comments(db, actor, class_id=class_id, term_id=term_id)


async def has_comment(
    db: AsyncSession, actor: User, *, pupil_id: uuid.UUID, term_id: uuid.UUID
) -> bool:
    """R10: "every pupil has a class teacher comment".

    A count rather than a loaded row, which matters more than it looks. The
    session's identity map may already hold this `TermReport` from an earlier
    read, and `SessionLocal` is built with `expire_on_commit=False` — so
    loading the entity can answer from a copy taken before the comment was
    written. A submission gate that reports yesterday's state is worse than
    no gate.

    `narrative.narrative_is_complete` counts for the same reason, and the two
    are deliberately the same shape.
    """
    found = await db.scalar(
        select(func.count()).where(
            TermReport.id.in_(scope.scoped_term_reports(actor).with_only_columns(TermReport.id)),
            TermReport.term_id == term_id,
            TermReport.pupil_id == pupil_id,
            func.btrim(func.coalesce(TermReport.class_teacher_comment, "")) != "",
        )
    )
    return bool(found)
