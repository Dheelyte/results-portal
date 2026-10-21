"""The scoped half of the §5.2 matrix.

"May a teacher enter scores" is a role question, asserted exhaustively in
tests/unit/test_authz_matrix.py. "May *this* teacher enter scores for *that*
class-subject" needs real rows, and is asserted here.

The distinction between class teacher and subject teacher lives in
`class_teachers` and `teaching_assignments`, not in `users.role` — both are
UserRole.TEACHER. That is why these cannot be pure.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import policy

# ---------------------------------------------------------------------------
# Enter scores — "own class-subjects", for both teacher columns
# ---------------------------------------------------------------------------


async def test_a_teacher_may_enter_scores_for_their_own_class_subject(
    session: AsyncSession, world
) -> None:
    assert await policy.can_enter_scores(session, world.teacher_a, world.maths_4a.id)


async def test_a_teacher_may_not_enter_scores_for_another_teachers_subject(
    session: AsyncSession, world
) -> None:
    """Being class teacher of 4A does not grant 4A Computer — the matrix says
    "own class-subjects", not "own class"."""
    assert not await policy.can_enter_scores(session, world.teacher_a, world.computer_4a.id)


async def test_a_teacher_may_not_enter_scores_for_another_class(
    session: AsyncSession, world
) -> None:
    assert not await policy.can_enter_scores(session, world.teacher_b, world.maths_4a.id)


async def test_the_union_case_from_the_specification(session: AsyncSession, world) -> None:
    """§5.2 by name: class teacher of 4A and French teacher in 5B gets both,
    and nothing wider."""
    assert await policy.can_enter_scores(session, world.teacher_a, world.french_5b.id)
    assert await policy.can_enter_scores(session, world.teacher_a, world.maths_4a.id)
    # Not 5B Mathematics, which belongs to teacher_b.
    assert not await policy.can_enter_scores(session, world.teacher_a, world.maths_5b.id)


@pytest.mark.parametrize("role_attribute", ["admin", "head", "parent"])
async def test_non_teachers_never_enter_scores(
    session: AsyncSession, world, role_attribute: str
) -> None:
    user = getattr(world, role_attribute)

    for class_subject in (world.maths_4a, world.french_5b, world.computer_4a):
        assert not await policy.can_enter_scores(session, user, class_subject.id)


# ---------------------------------------------------------------------------
# Narrative — the B1 split (D15)
# ---------------------------------------------------------------------------


async def test_the_class_teacher_writes_an_unassigned_section(session: AsyncSession, world) -> None:
    """Absence of an assignment means the class teacher writes it — which
    covers B-J and every curriculum area not handed to a specialist."""
    assert await policy.can_write_narrative(
        session, world.teacher_a, world.class_4a.id, world.work_habits.id
    )


async def test_the_specialist_writes_their_assigned_section(session: AsyncSession, world) -> None:
    assert await policy.can_write_narrative(
        session, world.specialist, world.class_4a.id, world.computer_skills.id
    )


async def test_the_class_teacher_loses_an_assigned_section(session: AsyncSession, world) -> None:
    """The point of the split: once Computer Skills is assigned, the class
    teacher no longer writes it."""
    assert not await policy.can_write_narrative(
        session, world.teacher_a, world.class_4a.id, world.computer_skills.id
    )


async def test_the_specialist_does_not_get_the_rest_of_the_narrative(
    session: AsyncSession, world
) -> None:
    """One assignment grants one section, not the class."""
    assert not await policy.can_write_narrative(
        session, world.specialist, world.class_4a.id, world.work_habits.id
    )


async def test_an_assignment_is_per_class(session: AsyncSession, world) -> None:
    """The specialist holds Computer Skills for 4A only. For 5B the section
    is unassigned, so 5B's class teacher writes it."""
    assert not await policy.can_write_narrative(
        session, world.specialist, world.class_5b.id, world.computer_skills.id
    )
    assert await policy.can_write_narrative(
        session, world.teacher_b, world.class_5b.id, world.computer_skills.id
    )


async def test_a_teacher_writes_nothing_for_a_class_they_do_not_teach(
    session: AsyncSession, world
) -> None:
    assert not await policy.can_write_narrative(
        session, world.teacher_b, world.class_4a.id, world.work_habits.id
    )


@pytest.mark.parametrize("role_attribute", ["admin", "head", "parent"])
async def test_non_teachers_never_write_narrative(
    session: AsyncSession, world, role_attribute: str
) -> None:
    user = getattr(world, role_attribute)

    assert not await policy.can_write_narrative(
        session, user, world.class_4a.id, world.work_habits.id
    )


# ---------------------------------------------------------------------------
# Attendance, growth and submission — class teacher only
# ---------------------------------------------------------------------------


async def test_the_class_teacher_records_attendance(session: AsyncSession, world) -> None:
    assert await policy.can_record_attendance_and_growth(
        session, world.teacher_a, world.class_4a.id
    )


async def test_a_subject_teacher_does_not_record_attendance(session: AsyncSession, world) -> None:
    """teacher_a teaches French in 5B but is not its class teacher."""
    assert not await policy.can_record_attendance_and_growth(
        session, world.teacher_a, world.class_5b.id
    )


async def test_only_the_class_teacher_submits_the_class(session: AsyncSession, world) -> None:
    assert await policy.can_submit_class(session, world.teacher_a, world.class_4a.id)
    assert not await policy.can_submit_class(session, world.teacher_a, world.class_5b.id)
    assert not await policy.can_submit_class(session, world.specialist, world.class_4a.id)


@pytest.mark.parametrize("role_attribute", ["admin", "head", "parent"])
async def test_non_teachers_never_submit_a_class(
    session: AsyncSession, world, role_attribute: str
) -> None:
    user = getattr(world, role_attribute)

    assert not await policy.can_submit_class(session, user, world.class_4a.id)
    assert not await policy.can_record_attendance_and_growth(session, user, world.class_4a.id)
