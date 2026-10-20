"""Seed data (ARCHITECTURE.md §10, docs/DECISIONS.md D30).

Two things are proven here: that the reference data matches the printed card,
and that seeding is idempotent — it must never re-assert a value the school
has since edited (§2.3).
"""

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AssessmentPeriod,
    Class,
    ClassSubject,
    GradeBand,
    GradingScale,
    GuardianPupil,
    NarrativeSection,
    Pupil,
    School,
    Subject,
    TeachingAssignment,
    Term,
    User,
    UserRole,
)
from app.seed.demo import seed_demo
from app.seed.reference import (
    BEHAVIOURAL_SECTIONS,
    CURRICULUM_AREA,
    CURRICULUM_AREAS,
    ENGLISH_CHILDREN,
    STANDALONE_SUBJECTS,
    seed_reference,
)

# ---------------------------------------------------------------------------
# Reference data matches the card
# ---------------------------------------------------------------------------


async def test_the_subject_tree_matches_the_card(session: AsyncSession, school: School) -> None:
    await seed_reference(session, school.id)

    subjects = (
        (
            await session.execute(
                select(Subject)
                .where(Subject.school_id == school.id)
                .order_by(Subject.display_order)
            )
        )
        .scalars()
        .all()
    )

    # English plus its five children plus thirteen standalone subjects.
    assert len(subjects) == 1 + len(ENGLISH_CHILDREN) + len(STANDALONE_SUBJECTS) == 19

    english = subjects[0]
    assert english.name == "English"
    assert english.is_group is True
    assert english.parent_subject_id is None

    children = [s for s in subjects if s.parent_subject_id == english.id]
    assert [c.name for c in children] == list(ENGLISH_CHILDREN)
    assert all(c.is_group is False for c in children)


async def test_eighteen_subjects_are_scored(session: AsyncSession, school: School) -> None:
    """The group heading prints but holds no scores (R7)."""
    await seed_reference(session, school.id)

    scored = await session.scalar(
        select(func.count())
        .select_from(Subject)
        .where(Subject.school_id == school.id, Subject.is_group.is_(False))
    )

    assert scored == 18


async def test_the_grading_scale_is_the_card_s_seven_bands(
    session: AsyncSession, school: School
) -> None:
    """A2: seeded because it is what is printed, even though it contradicts
    the six-band scale approved in September (N1, still open)."""
    await seed_reference(session, school.id)

    scale = await session.scalar(select(GradingScale).where(GradingScale.school_id == school.id))
    bands = (
        (
            await session.execute(
                select(GradeBand)
                .where(GradeBand.scale_id == scale.id)
                .order_by(GradeBand.sort_order)
            )
        )
        .scalars()
        .all()
    )

    assert scale.is_active is True
    assert len(bands) == 7
    assert [b.letter for b in bands] == ["A+", "A", "B+", "B", "C", "D", "E"]
    assert bands[0].min_score == Decimal("90.00")
    assert bands[0].max_score == Decimal("100.00")
    assert bands[-1].min_score == Decimal("0.00")
    assert bands[-1].max_score == Decimal("39.00")


async def test_the_bands_cover_zero_to_a_hundred_without_gaps(
    session: AsyncSession, school: School
) -> None:
    """A gap would leave a score with no grade; an overlap would make the
    grade depend on evaluation order."""
    await seed_reference(session, school.id)

    scale = await session.scalar(select(GradingScale))
    bands = (
        (
            await session.execute(
                select(GradeBand)
                .where(GradeBand.scale_id == scale.id)
                .order_by(GradeBand.min_score)
            )
        )
        .scalars()
        .all()
    )

    assert bands[0].min_score == Decimal("0.00")
    assert bands[-1].max_score == Decimal("100.00")
    for lower, upper in zip(bands, bands[1:], strict=False):
        assert upper.min_score == lower.max_score + 1


async def test_there_are_sixteen_narrative_sections(session: AsyncSession, school: School) -> None:
    """Seven curriculum areas plus B-J. Not seventeen — see DECISIONS D27."""
    await seed_reference(session, school.id)

    sections = (
        (
            await session.execute(
                select(NarrativeSection)
                .where(NarrativeSection.school_id == school.id)
                .order_by(NarrativeSection.display_order)
            )
        )
        .scalars()
        .all()
    )

    assert len(sections) == 16
    assert len(CURRICULUM_AREAS) == 7
    assert len(BEHAVIOURAL_SECTIONS) == 9

    grouped = [s for s in sections if s.group_label == CURRICULUM_AREA]
    assert len(grouped) == 7
    assert [s.code for s in sections[7:]] == ["B", "C", "D", "E", "F", "G", "H", "I", "J"]


async def test_the_curriculum_areas_are_not_the_scored_subjects(
    session: AsyncSession, school: School
) -> None:
    """§1.4 says so explicitly, and D15's design depends on it: "Art & Music"
    has no scored counterpart at all."""
    await seed_reference(session, school.id)

    scored = {
        s.name
        for s in (
            await session.execute(select(Subject).where(Subject.is_group.is_(False)))
        ).scalars()
    }
    areas = {label for _, label in CURRICULUM_AREAS}

    assert "Art & Music" in areas
    assert "Art & Music" not in scored
    assert areas != scored


# ---------------------------------------------------------------------------
# Idempotency (D30)
# ---------------------------------------------------------------------------


async def test_seeding_twice_creates_nothing_the_second_time(
    session: AsyncSession, school: School
) -> None:
    first = await seed_reference(session, school.id)
    second = await seed_reference(session, school.id)

    assert sum(first.values()) > 0
    assert second == {"subjects": 0, "grading_scale": 0, "narrative_sections": 0}


async def test_seeding_again_does_not_undo_an_edit(session: AsyncSession, school: School) -> None:
    """The point of D30. Re-asserting a seeded value on the next deploy would
    quietly discard the school's own configuration."""
    await seed_reference(session, school.id)

    subject = await session.scalar(select(Subject).where(Subject.name == "Yoruba"))
    subject.name = "Yoruba Language"
    subject.display_order = 99
    subject.is_specialist = True

    band = await session.scalar(select(GradeBand).where(GradeBand.letter == "A+"))
    band.min_score = Decimal("85.00")

    section = await session.scalar(select(NarrativeSection).where(NarrativeSection.code == "J"))
    section.is_active = False
    await session.commit()

    await seed_reference(session, school.id)

    await session.refresh(subject)
    await session.refresh(band)
    await session.refresh(section)

    assert subject.name == "Yoruba Language"
    assert subject.display_order == 99
    assert subject.is_specialist is True
    assert band.min_score == Decimal("85.00")
    assert section.is_active is False


async def test_a_deleted_subject_is_restored_but_nothing_else_changes(
    session: AsyncSession, school: School
) -> None:
    """Absent means create. That is the one case where seeding acts."""
    await seed_reference(session, school.id)

    french = await session.scalar(select(Subject).where(Subject.name == "French"))
    await session.delete(french)
    await session.commit()

    counts = await seed_reference(session, school.id)

    assert counts["subjects"] == 1
    assert await session.scalar(select(Subject).where(Subject.name == "French")) is not None


# ---------------------------------------------------------------------------
# Demo data (§10)
# ---------------------------------------------------------------------------


async def test_demo_data_matches_the_specified_fixture(session: AsyncSession) -> None:
    await seed_demo(session)

    assert await session.scalar(select(func.count()).select_from(Pupil)) == 20
    assert await session.scalar(select(func.count()).select_from(Class)) == 2
    assert await session.scalar(select(func.count()).select_from(Term)) == 3
    # Two assessment sheets per term — the structural key of the system.
    assert await session.scalar(select(func.count()).select_from(AssessmentPeriod)) == 6

    by_role = dict(
        (await session.execute(select(User.role, func.count()).group_by(User.role))).all()
    )
    assert by_role[UserRole.ADMIN] == 1
    assert by_role[UserRole.HEAD_TEACHER] == 1
    assert by_role[UserRole.TEACHER] == 3
    assert by_role[UserRole.PARENT] == 8


async def test_one_parent_has_two_children_in_different_classes(
    session: AsyncSession,
) -> None:
    """§10 names this fixture because it catches most multi-child bugs."""
    await seed_demo(session)

    rows = (
        await session.execute(
            select(GuardianPupil.guardian_user_id, func.count())
            .group_by(GuardianPupil.guardian_user_id)
            .having(func.count() > 1)
        )
    ).all()

    assert len(rows) == 1
    guardian_id = rows[0][0]

    # The classes must actually differ: a parent with two children in the
    # same class exercises none of the multi-class paths.
    from app.models import Enrollment

    distinct_classes = (
        await session.execute(
            select(func.count(func.distinct(Enrollment.class_id)))
            .select_from(GuardianPupil)
            .join(Enrollment, Enrollment.pupil_id == GuardianPupil.pupil_id)
            .where(GuardianPupil.guardian_user_id == guardian_id)
        )
    ).scalar_one()

    assert distinct_classes == 2


async def test_one_pupil_joined_in_second_term(session: AsyncSession) -> None:
    """§10's other named fixture: R5 must average over the terms a pupil was
    present for, not over three."""
    from app.models import Enrollment

    await seed_demo(session)

    first_term = await session.scalar(select(Term).where(Term.number == "first"))
    late = (
        (
            await session.execute(
                select(Enrollment).where(Enrollment.joined_on > first_term.starts_on)
            )
        )
        .scalars()
        .all()
    )

    assert len(late) == 1


async def test_no_group_subject_is_ever_offered_as_a_class_subject(
    session: AsyncSession,
) -> None:
    """R7: a group heading prints on the card but holds no scores."""
    await seed_demo(session)

    groups_offered = await session.scalar(
        select(func.count())
        .select_from(ClassSubject)
        .join(Subject, Subject.id == ClassSubject.subject_id)
        .where(Subject.is_group.is_(True))
    )

    assert groups_offered == 0


async def test_every_class_subject_has_a_teacher(session: AsyncSession) -> None:
    await seed_demo(session)

    class_subjects = await session.scalar(select(func.count()).select_from(ClassSubject))
    assignments = await session.scalar(select(func.count()).select_from(TeachingAssignment))

    assert class_subjects == assignments == 36  # 18 scored subjects x 2 classes


async def test_a_specialist_teaches_across_both_classes(session: AsyncSession) -> None:
    """The §5.2 union case: a teacher who is class teacher of one class and
    subject teacher in another gets both scopes and nothing wider."""
    await seed_demo(session)

    specialist_classes = await session.scalar(
        select(func.count(func.distinct(ClassSubject.class_id)))
        .select_from(TeachingAssignment)
        .join(ClassSubject, ClassSubject.id == TeachingAssignment.class_subject_id)
        .join(Subject, Subject.id == ClassSubject.subject_id)
        .where(Subject.is_specialist.is_(True))
    )

    assert specialist_classes == 2


async def test_demo_refuses_to_run_over_existing_pupils(session: AsyncSession) -> None:
    """It is development data; pointing it at a real database would be a
    disaster that no error message could undo."""
    import pytest

    await seed_demo(session)

    with pytest.raises(RuntimeError, match="already holds pupils"):
        await seed_demo(session)
