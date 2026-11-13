"""Publication, withholding, release and the post-publication edit
(ARCHITECTURE.md §6 R12, R13, §4.8, §4.9).

R12 shapes the whole module:

    Publishing acts on a class, with an optional list of pupils to hold back.
    Withheld pupils may be released individually later. A parent opening a
    non-published report sees exactly:

    > Result not yet available. Please contact the school.

That asymmetry — publish a class, withhold and release individuals — is why
`term_reports.state` is per pupil while the action is per class (§4.8). A fee
arrears or a disciplinary matter holds one child back; it must not block the
other twenty-nine.

R13 is the other half, and it is the only route to a changed grade after
approval:

    Admin only, reason required, audited.

`edit_entry` below re-resolves the grade against the **snapshotted** scale on
the row, never against today's active scale. CLAUDE.md rule 6 forbids
recomputing a published grade, and the point of the snapshot is that a card
already in a parent's hands stays explicable: if the school has since changed
a band, the corrected score must still be graded the way the rest of that
card was.
"""

import asyncio
import datetime as dt
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import backup
from app.authz import scope
from app.config import get_settings
from app.models import (
    AssessmentPeriod,
    AuditAction,
    Class,
    ClassSubject,
    ClassTermState,
    ClassTermStatus,
    GradeBand,
    GradingScale,
    PublicationState,
    Pupil,
    ResultEntry,
    Subject,
    Term,
    TermHalf,
    TermReport,
    User,
)
from app.services import audit, grading, marks, results
from app.services.errors import Conflict, Invalid
from app.services.support import all_of, one_or_404, rows_of

logger = logging.getLogger(__name__)

# R12, word for word. A parent opening an unavailable report sees exactly
# this and nothing else — no hint of whether the report exists, whether it was
# withheld, or why. The school says why, in person.
UNAVAILABLE_MESSAGE = "Result not yet available. Please contact the school."

# The columns R13 may correct. `ca_test_total` is generated and
# `period_average` is derived; `grade_letter` and `grading_scale_id` belong to
# the snapshot and are rewritten below rather than accepted from a caller.
EDITABLE_COLUMNS = marks.ALL_COLUMNS


@dataclass(frozen=True)
class PublishOutcome:
    """What publication did, per pupil, so the screen can show it."""

    term_id: uuid.UUID
    class_id: uuid.UUID
    class_name: str
    published: list[uuid.UUID] = field(default_factory=list)
    withheld: list[uuid.UUID] = field(default_factory=list)
    already_published: list[uuid.UUID] = field(default_factory=list)


@dataclass(frozen=True)
class ReportState:
    """One pupil's publication state, for the admin's list."""

    report_id: uuid.UUID
    pupil_id: uuid.UUID
    name: str
    admission_number: str | None
    state: PublicationState
    published_at: dt.datetime | None
    withheld_reason: str | None
    acknowledged_at: dt.datetime | None


# ---------------------------------------------------------------------------
# R12 — publishing a class
# ---------------------------------------------------------------------------


async def _approved_class(
    db: AsyncSession, actor: User, *, class_id: uuid.UUID, term_id: uuid.UUID
) -> tuple[Class, Term]:
    """The class and term, with the one precondition publication has.

    §1.6: "Head teacher reviews → approves, or returns with a note → Admin
    publishes". Publishing an unapproved class would put a card in front of a
    parent that nobody had checked and whose grades were never frozen.
    """
    klass = await one_or_404(db, scope.scoped_classes(actor).where(Class.id == class_id), "class")
    term = await one_or_404(db, scope.scoped_terms(actor).where(Term.id == term_id), "term")

    state = await db.scalar(
        scope.scoped_class_term_status(actor)
        .where(ClassTermStatus.class_id == class_id, ClassTermStatus.term_id == term.id)
        .with_only_columns(ClassTermStatus.state)
    )
    if state is not ClassTermState.APPROVED:
        current = (state or ClassTermState.NOT_STARTED).value.replace("_", " ")
        raise Conflict(
            "Only an approved class can be published. This one is "
            f"{current} — the head teacher approves it first (§1.6)."
        )
    return klass, term


async def publish_class(
    db: AsyncSession,
    actor: User,
    *,
    class_id: uuid.UUID,
    term_id: uuid.UUID,
    withhold_pupil_ids: Sequence[uuid.UUID] = (),
    reason: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> PublishOutcome:
    """Publish a class, optionally holding individuals back (R12).

    Idempotent for the pupils already published: a second publish after a
    correction releases the rest rather than refusing the lot. The withhold
    list is what changes between two runs, and it is read as the current
    intention rather than as a delta.
    """
    klass, term = await _approved_class(db, actor, class_id=class_id, term_id=term_id)

    withhold = set(withhold_pupil_ids)
    if withhold and not (reason or "").strip():
        # Someone has to be able to answer the parent who rings up. The reason
        # is for the school's own record, not for the parent's screen — R12
        # gives the parent one sentence and no detail.
        raise Invalid(
            "Give a reason for holding a result back. The parent is not shown it, but the "
            "school needs to know why when they ask."
        )

    pupils = {
        pupil.id: pupil
        for pupil in await results.pupils_of(
            db, actor, class_id=class_id, academic_session_id=term.academic_session_id
        )
    }
    if not pupils:
        raise Conflict("No pupils are enrolled in this class for this session.")

    unknown = withhold - set(pupils)
    if unknown:
        raise Invalid(
            f"{len(unknown)} of the pupils to hold back are not in this class for this session."
        )

    reports = {
        report.pupil_id: report
        for report in await all_of(
            db,
            scope.scoped_term_reports(actor)
            .where(TermReport.term_id == term.id, TermReport.pupil_id.in_(pupils))
            .execution_options(populate_existing=True),
        )
    }
    missing = set(pupils) - set(reports)
    if missing:
        # Submission guarantees a row per pupil (A24), so this means a pupil
        # was enrolled after the class was submitted.
        raise Conflict(
            f"{len(missing)} pupils have no report for this term. They were enrolled after "
            "the class was submitted, so it needs returning and resubmitting before "
            "publication."
        )

    # §11: "a dump taken immediately before every publish". Here, and not a
    # line earlier: every refusal above has already happened, so a dump is
    # taken only when a publication is actually about to occur. And not a
    # line later either — nothing has been mutated yet, so what the dump
    # captures is the state to come back to.
    await _back_up_before_publishing(class_id=class_id, term_id=term.id)

    outcome = PublishOutcome(term_id=term.id, class_id=klass.id, class_name=klass.name)
    now = dt.datetime.now(dt.UTC)

    for pupil_id, report in reports.items():
        if pupil_id in withhold:
            report.state = PublicationState.WITHHELD
            report.withheld_reason = (reason or "").strip() or None
            report.published_at = None
            report.published_by = None
            outcome.withheld.append(pupil_id)
            continue

        if report.state is PublicationState.PUBLISHED:
            outcome.already_published.append(pupil_id)
            continue

        report.state = PublicationState.PUBLISHED
        report.published_at = now
        report.published_by = actor.id
        report.withheld_reason = None
        outcome.published.append(pupil_id)

    await db.flush()

    await audit.record(
        db,
        school_id=actor.school_id,
        action=AuditAction.CLASS_PUBLISHED,
        entity_type="class",
        entity_id=class_id,
        actor_id=actor.id,
        # Counts, not names. §4.9 wants the fact of the publication; the
        # per-pupil rows below carry the individual decisions.
        after={
            "term_id": str(term.id),
            "published": len(outcome.published),
            "withheld": len(outcome.withheld),
            "already_published": len(outcome.already_published),
        },
        reason=(reason or "").strip() or None,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    # A row per withheld pupil as well: §4.9 requires "every publish,
    # withhold and release", and "which child was held back, and why" is the
    # question asked when a parent rings.
    for pupil_id in outcome.withheld:
        await audit.record(
            db,
            school_id=actor.school_id,
            action=AuditAction.REPORT_WITHHELD,
            entity_type="term_report",
            entity_id=reports[pupil_id].id,
            actor_id=actor.id,
            after={"state": PublicationState.WITHHELD.value},
            reason=(reason or "").strip() or None,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    await db.commit()
    return outcome


async def _back_up_before_publishing(*, class_id: uuid.UUID, term_id: uuid.UUID) -> None:
    """Dump the database before a class is published (§11).

    §11's reason, in its own words: "Results data is irreplaceable — no
    teacher will rewrite 480 passages." Publication is the moment results
    become something parents have seen, and R13's correction path rewrites
    rows afterwards. A dump from a moment earlier is the only way back.

    A failure **refuses the publish**, because `require_prepublish_backup` is
    true by default: a safety net nobody checks is not a safety net, and the
    one time it matters is the time it was missing. An admin who must publish
    with a broken backup store can set the key false, which is the decision
    §14 records rather than a branch hidden in here.

    `to_thread` because `backup.take` shells out to pg_dump and blocks; left
    on the event loop it would stall every other request for the second or
    two the dump takes.
    """
    try:
        taken = await asyncio.to_thread(backup.take, reason="pre-publish")
    except backup.BackupFailed as exc:
        if get_settings().require_prepublish_backup:
            raise Conflict(
                "The pre-publication backup could not be taken, so nothing was published. "
                f"{exc} Fix the backup store and publish again."
            ) from None
        logger.warning("publishing without a pre-publication backup", extra={"reason": str(exc)})
        return

    logger.info(
        "pre-publication backup taken",
        extra={
            "key": taken.key,
            "bytes": taken.size_bytes,
            "class_id": str(class_id),
            "term_id": str(term_id),
        },
    )


async def _report(db: AsyncSession, actor: User, report_id: uuid.UUID) -> TermReport:
    return await one_or_404(
        db,
        scope.scoped_term_reports(actor).where(TermReport.id == report_id),
        "report",
    )


async def release_report(
    db: AsyncSession,
    actor: User,
    *,
    report_id: uuid.UUID,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> TermReport:
    """Release one withheld report (R12: "released individually later")."""
    report = await _report(db, actor, report_id)

    if report.state is PublicationState.PUBLISHED:
        raise Conflict("This report is already published.")

    before = report.state
    report.state = PublicationState.PUBLISHED
    report.published_at = dt.datetime.now(dt.UTC)
    report.published_by = actor.id
    # Kept until now so "why was this held back" survives in the audit row
    # written below; cleared on the report because it no longer applies.
    held_for = report.withheld_reason
    report.withheld_reason = None

    await db.flush()
    await audit.record(
        db,
        school_id=actor.school_id,
        action=AuditAction.REPORT_RELEASED,
        entity_type="term_report",
        entity_id=report.id,
        actor_id=actor.id,
        before={"state": before.value},
        after={"state": report.state.value},
        reason=held_for,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()
    return report


async def withhold_report(
    db: AsyncSession,
    actor: User,
    *,
    report_id: uuid.UUID,
    reason: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> TermReport:
    """Pull one report back after publication (R12).

    A reason is required here as it is on a publish: this one is more likely
    to be asked about, because the parent may already have seen the card.
    """
    if not reason.strip():
        raise Invalid(
            "Give a reason for withholding this result. The parent is not shown it, but the "
            "school needs to know why when they ask."
        )

    report = await _report(db, actor, report_id)
    before = report.state

    report.state = PublicationState.WITHHELD
    report.withheld_reason = reason.strip()
    report.published_at = None
    report.published_by = None

    await db.flush()
    await audit.record(
        db,
        school_id=actor.school_id,
        action=AuditAction.REPORT_WITHHELD,
        entity_type="term_report",
        entity_id=report.id,
        actor_id=actor.id,
        before={"state": before.value},
        after={"state": report.state.value},
        reason=reason.strip(),
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()
    return report


async def class_reports(
    db: AsyncSession, actor: User, *, class_id: uuid.UUID, term_id: uuid.UUID
) -> tuple[Class, Term, ClassTermState, list[ReportState]]:
    """Every report for a class, with its publication state."""
    klass = await one_or_404(db, scope.scoped_classes(actor).where(Class.id == class_id), "class")
    term = await one_or_404(db, scope.scoped_terms(actor).where(Term.id == term_id), "term")

    state = (
        await db.scalar(
            scope.scoped_class_term_status(actor)
            .where(ClassTermStatus.class_id == class_id, ClassTermStatus.term_id == term.id)
            .with_only_columns(ClassTermStatus.state)
        )
        or ClassTermState.NOT_STARTED
    )

    pupils = await results.pupils_of(
        db, actor, class_id=class_id, academic_session_id=term.academic_session_id
    )
    reports = {
        report.pupil_id: report
        for report in await all_of(
            db,
            scope.scoped_term_reports(actor)
            .where(TermReport.term_id == term.id)
            .execution_options(populate_existing=True),
        )
    }

    return (
        klass,
        term,
        state,
        [
            ReportState(
                report_id=reports[pupil.id].id,
                pupil_id=pupil.id,
                name=f"{pupil.last_name}, {pupil.first_name}",
                admission_number=pupil.admission_number,
                state=reports[pupil.id].state,
                published_at=reports[pupil.id].published_at,
                withheld_reason=reports[pupil.id].withheld_reason,
                acknowledged_at=reports[pupil.id].parent_acknowledged_at,
            )
            for pupil in pupils
            if pupil.id in reports
        ],
    )


# ---------------------------------------------------------------------------
# R13 — the post-publication edit
# ---------------------------------------------------------------------------
#
# "Admin only, reason required, audited." The only route to a changed score or
# grade once a class is approved, and the only other place in the codebase
# permitted to write `grade_letter` — see the allowlist in
# `tests/unit/test_grade_snapshot_is_sacred.py`.


@dataclass(frozen=True)
class EditOutcome:
    entry: ResultEntry
    pupil_name: str
    subject_name: str
    before: dict[str, object]
    after: dict[str, object]
    # True when the correction moved the grade, which is what makes a reprint
    # necessary rather than merely tidy.
    grade_changed: bool
    regraded_against: str | None


async def edit_entry(
    db: AsyncSession,
    actor: User,
    *,
    entry_id: uuid.UUID,
    scores: dict[str, object],
    reason: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> EditOutcome:
    """Correct one score row after approval (R13).

    Three things make this different from a teacher's save:

    - **A reason is required.** §4.9: "A post-publication edit **requires** a
      non-empty `reason`; reject the request without one." It is the only
      field in this system that exists purely so a human can be asked about a
      decision later.
    - **The grade is re-resolved against the row's own snapshotted scale**,
      not against whatever is active now. The rest of that card was graded
      against the snapshot, and a corrected row graded against a newer scale
      would make one line of the card unexplainable (CLAUDE.md rule 6, §4.5).
    - **R1 still applies.** A correction is still a score, and still has to
      fit the Marks Obtainable row.
    """
    if not reason.strip():
        raise Invalid(
            "Give a reason for this change. A score altered after publication is the one "
            "thing somebody will be asked to explain, and §4.9 requires it on the record."
        )

    entry = await one_or_404(
        db,
        scope.scoped_result_entries(actor)
        .where(ResultEntry.id == entry_id)
        .execution_options(populate_existing=True),
        "score row",
    )

    period = await one_or_404(
        db,
        scope.scoped_assessment_periods(actor).where(
            AssessmentPeriod.id == entry.assessment_period_id
        ),
        "assessment period",
    )
    offering = await one_or_404(
        db,
        select(ClassSubject).where(
            ClassSubject.id == entry.class_subject_id,
            ClassSubject.school_id == actor.school_id,
        ),
        "class-subject",
    )
    pupil = await one_or_404(
        db, scope.scoped_pupils(actor).where(Pupil.id == entry.pupil_id), "pupil"
    )
    subject_name = await db.scalar(
        scope.scoped_subjects(actor)
        .where(Subject.id == offering.subject_id)
        .with_only_columns(Subject.name)
    )

    columns = marks.COLUMNS_BY_HALF[period.half]
    maxima = await marks.applicable_maxima(
        db, actor, assessment_period_id=period.id, class_id=offering.class_id
    )
    if maxima is None:
        raise Conflict(
            "This sheet has no Marks Obtainable row, so a corrected score cannot be checked."
        )

    # R1, the same rule the grid enforces, reached by a different door.
    for column, value in scores.items():
        if period.half is TermHalf.SECOND_HALF and column in marks.CARRIED_COLUMNS:
            raise Invalid(
                "The second half's CA tests are carried over from the first half. Correct "
                "the first-half score and it carries over (D127)."
            )
        if column not in columns:
            raise Invalid(
                f"This sheet has no {column} column. Corrections must fit the sheet the "
                "score was entered on."
            )
        if value is None:
            continue
        maximum = getattr(maxima, column)
        if maximum is None:
            raise Invalid(f"{column} has no maximum set, so nothing can be entered against it.")
        if value < 0 or value > maximum:
            raise Invalid(f"{column} must be between 0 and {maximum:g}.")

    before = audit.snapshot(entry, (*EDITABLE_COLUMNS, "period_average", "grade_letter"))

    for column, value in scores.items():
        setattr(entry, column, value)

    entry.period_average = grading.period_average(
        period.half,
        {column: getattr(entry, column) for column in columns},
        {column: getattr(maxima, column) for column in marks.ALL_COLUMNS},
    )

    regraded_against = await _regrade_against_snapshot(db, actor, entry)

    # A corrected first-half CA test is the second half's too (D127).
    if period.half is TermHalf.FIRST_HALF and set(scores) & set(marks.CARRIED_COLUMNS):
        second = await results.carry_forward(
            db, actor, entry, period=period, class_id=offering.class_id
        )
        if second is not None:
            await _regrade_against_snapshot(db, actor, second)

    await db.flush()
    await db.refresh(entry)
    after = audit.snapshot(entry, (*EDITABLE_COLUMNS, "period_average", "grade_letter"))

    await audit.record(
        db,
        school_id=actor.school_id,
        action=AuditAction.ENTRY_EDITED_AFTER_PUBLICATION,
        entity_type="result_entry",
        entity_id=entry.id,
        actor_id=actor.id,
        # The one audited action whose payload carries scores, deliberately:
        # §4.9 asks for before/after values on a post-publication edit, and
        # the question it answers — "what did this card say before?" — cannot
        # be answered without them. The log is admin-and-head-teacher-only
        # (§5.2), which is the same audience as the cards themselves.
        before=before,
        after=after,
        reason=reason.strip(),
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await db.commit()
    await db.refresh(entry)

    return EditOutcome(
        entry=entry,
        pupil_name=f"{pupil.last_name}, {pupil.first_name}",
        subject_name=subject_name or "",
        before=before,
        after=after,
        grade_changed=before.get("grade_letter") != after.get("grade_letter"),
        regraded_against=regraded_against,
    )


async def _regrade_against_snapshot(
    db: AsyncSession, actor: User, entry: ResultEntry
) -> str | None:
    """Re-resolve this row's grade against the scale it was frozen against.

    The second and last writer of `grade_letter` in the codebase, and the
    reason it is permitted: a corrected score has to carry a grade, and the
    only defensible grade is the one the rest of that card was given.

    A row with no snapshot has not been approved, so there is nothing to
    preserve and nothing to write — a teacher's own save will recompute the
    average and the live grade follows the active scale as usual (R4).
    """
    if entry.grading_scale_id is None:
        return None

    scale = await db.scalar(
        scope.scoped_grading_scales(actor).where(GradingScale.id == entry.grading_scale_id)
    )
    if scale is None:  # pragma: no cover - a scale is never deleted
        return None

    bands = await all_of(
        db,
        scope.scoped_grade_bands(actor)
        .where(GradeBand.scale_id == scale.id)
        .order_by(GradeBand.sort_order),
    )
    band = grading.band_for(entry.period_average, bands)
    entry.grade_letter = band.letter if band is not None else None
    return scale.name


@dataclass(frozen=True)
class CorrectableRow:
    """One score row an admin could correct, with the id R13 needs."""

    entry_id: uuid.UUID
    class_subject_id: uuid.UUID
    subject_name: str
    half: str
    columns: tuple[str, ...]
    scores: dict[str, object]
    period_average: object | None
    grade_letter: str | None
    # True once approval has frozen the grade. A row without a snapshot is
    # still the teacher's to fix through the grid; R13 is for the ones that
    # are not.
    is_snapshot: bool


async def pupil_entries(
    db: AsyncSession, actor: User, *, pupil_id: uuid.UUID, term_id: uuid.UUID
) -> tuple[Pupil, list[CorrectableRow]]:
    """One pupil's score rows for a term, with their ids (R13).

    §7 lists `PATCH /entries/{id}` under the admin's publication block and no
    endpoint that yields an entry id: the grid is teacher-only (§5.2) and the
    review payload is the head teacher's. Without this the admin cannot reach
    R13's verb at all — the same missing half D37, D51 and D57 record
    (docs/DECISIONS.md D75).

    One pupil at a time, because that is the shape of a correction: "Ada's
    Mathematics exam mark is wrong."
    """
    pupil = await one_or_404(db, scope.scoped_pupils(actor).where(Pupil.id == pupil_id), "pupil")
    term = await one_or_404(db, scope.scoped_terms(actor).where(Term.id == term_id), "term")

    periods = {
        period.id: period
        for period in await all_of(
            db,
            scope.scoped_assessment_periods(actor).where(AssessmentPeriod.term_id == term.id),
        )
    }
    if not periods:
        return pupil, []

    rows = await rows_of(
        db,
        select(ResultEntry, Subject.name)
        .join(ClassSubject, ClassSubject.id == ResultEntry.class_subject_id)
        .join(Subject, Subject.id == ClassSubject.subject_id)
        .where(
            ResultEntry.id.in_(
                scope.scoped_result_entries(actor).with_only_columns(ResultEntry.id)
            ),
            ResultEntry.pupil_id == pupil_id,
            ResultEntry.assessment_period_id.in_(periods),
        )
        .order_by(Subject.display_order, Subject.name),
    )

    return pupil, [
        CorrectableRow(
            entry_id=entry.id,
            class_subject_id=entry.class_subject_id,
            subject_name=subject_name,
            half=periods[entry.assessment_period_id].half.value,
            columns=marks.COLUMNS_BY_HALF[periods[entry.assessment_period_id].half],
            scores={
                column: getattr(entry, column) for column in (*marks.ALL_COLUMNS, "ca_test_total")
            },
            period_average=entry.period_average,
            grade_letter=entry.grade_letter,
            is_snapshot=entry.grade_letter is not None,
        )
        for entry, subject_name in rows
    ]
