"""Row visibility (ARCHITECTURE.md §5.2).

> "A subject teacher hitting another class's results must get a 404, and the
> filtering must happen where the data is fetched."

These are the assertions that stop a leak. A capability check that says "no"
is a 403; a scope that returns no row is a 404, and §5.2 wants the second for
tenant data because the first confirms the row exists.
"""

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.authz import policy, scope
from app.models import PublicationState, School, User, UserRole


async def ids_from(session: AsyncSession, statement) -> set:
    rows = (await session.execute(statement)).scalars().all()
    return {row.id for row in rows}


# ---------------------------------------------------------------------------
# Classes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role_attribute", ["admin", "head"])
async def test_admin_and_head_see_every_class(
    session: AsyncSession, world, role_attribute: str
) -> None:
    user = getattr(world, role_attribute)

    assert await ids_from(session, scope.scoped_classes(user)) == {
        world.class_4a.id,
        world.class_5b.id,
    }


async def test_a_teacher_sees_the_union_of_both_routes(session: AsyncSession, world) -> None:
    """teacher_a is class teacher of 4A and French teacher in 5B."""
    assert await ids_from(session, scope.scoped_classes(world.teacher_a)) == {
        world.class_4a.id,
        world.class_5b.id,
    }


async def test_a_teacher_sees_only_their_own_class(session: AsyncSession, world) -> None:
    assert await ids_from(session, scope.scoped_classes(world.teacher_b)) == {world.class_5b.id}


async def test_a_specialist_sees_the_classes_they_teach(session: AsyncSession, world) -> None:
    """The specialist is class teacher of neither but teaches Computer in
    both."""
    assert await ids_from(session, scope.scoped_classes(world.specialist)) == {
        world.class_4a.id,
        world.class_5b.id,
    }


async def test_a_parent_sees_their_children_s_classes(session: AsyncSession, world) -> None:
    assert await ids_from(session, scope.scoped_classes(world.parent)) == {
        world.class_4a.id,
        world.class_5b.id,
    }


async def test_a_parent_with_no_children_sees_nothing(session: AsyncSession, world) -> None:
    assert await ids_from(session, scope.scoped_classes(world.other_parent)) == set()


# ---------------------------------------------------------------------------
# Class-subjects
# ---------------------------------------------------------------------------


async def test_a_teacher_sees_only_what_they_teach(session: AsyncSession, world) -> None:
    """Being class teacher of 4A does not reveal another teacher's scores for
    4A Computer."""
    assert await ids_from(session, scope.scoped_class_subjects(world.teacher_a)) == {
        world.maths_4a.id,
        world.french_4a.id,
        world.french_5b.id,
    }


async def test_a_specialist_sees_only_their_subject(session: AsyncSession, world) -> None:
    assert await ids_from(session, scope.scoped_class_subjects(world.specialist)) == {
        world.computer_4a.id,
        world.computer_5b.id,
    }


async def test_a_parent_sees_no_class_subject(session: AsyncSession, world) -> None:
    assert await ids_from(session, scope.scoped_class_subjects(world.parent)) == set()


async def test_the_admin_sees_every_class_subject(session: AsyncSession, world) -> None:
    """Visibility is not capability: the admin sees all six in order to assign
    teachers, and may not enter a score against any of them."""
    visible = await ids_from(session, scope.scoped_class_subjects(world.admin))

    assert len(visible) == 6
    for class_subject_id in visible:
        assert not await policy.can_enter_scores(session, world.admin, class_subject_id)


# ---------------------------------------------------------------------------
# Pupils — the filter that matters most
# ---------------------------------------------------------------------------


async def test_a_parent_sees_only_their_own_children(session: AsyncSession, world) -> None:
    assert await ids_from(session, scope.scoped_pupils(world.parent)) == {
        world.pupils["ada"].id,
        world.pupils["chidi"].id,
    }


async def test_a_parent_never_sees_another_family_s_child(session: AsyncSession, world) -> None:
    visible = await ids_from(session, scope.scoped_pupils(world.parent))

    assert world.pupils["emeka"].id not in visible
    assert await ids_from(session, scope.scoped_pupils(world.other_parent)) == set()


async def test_a_teacher_sees_the_pupils_of_every_class_they_touch(
    session: AsyncSession, world
) -> None:
    assert await ids_from(session, scope.scoped_pupils(world.teacher_a)) == {
        world.pupils["ada"].id,
        world.pupils["emeka"].id,
        world.pupils["chidi"].id,
    }


async def test_a_teacher_never_sees_a_class_they_do_not_touch(session: AsyncSession, world) -> None:
    visible = await ids_from(session, scope.scoped_pupils(world.teacher_b))

    assert visible == {world.pupils["chidi"].id}
    assert world.pupils["ada"].id not in visible


async def test_can_view_pupil_agrees_with_the_scope(session: AsyncSession, world) -> None:
    assert await policy.can_view_pupil(session, world.parent, world.pupils["ada"].id)
    assert not await policy.can_view_pupil(session, world.parent, world.pupils["emeka"].id)
    assert not await policy.can_view_pupil(session, world.teacher_b, world.pupils["ada"].id)


# ---------------------------------------------------------------------------
# Term reports — R12
# ---------------------------------------------------------------------------


async def test_a_parent_sees_no_unpublished_report(session: AsyncSession, world) -> None:
    """R12. The reports exist in draft; the parent must not see them, and
    must not be told they exist."""
    assert await ids_from(session, scope.scoped_term_reports(world.parent)) == set()


async def test_a_parent_sees_a_published_report(session: AsyncSession, world) -> None:
    world.reports["ada"].state = PublicationState.PUBLISHED
    await session.commit()

    assert await ids_from(session, scope.scoped_term_reports(world.parent)) == {
        world.reports["ada"].id
    }


async def test_a_withheld_report_is_invisible_not_forbidden(session: AsyncSession, world) -> None:
    """A 403 would confirm the report exists. R12 wants the school-contact
    message instead, which means the row simply is not in scope."""
    world.reports["ada"].state = PublicationState.WITHHELD
    await session.commit()

    assert await ids_from(session, scope.scoped_term_reports(world.parent)) == set()
    assert not await policy.can_acknowledge_report(session, world.parent, world.reports["ada"].id)


async def test_publishing_another_family_s_report_changes_nothing(
    session: AsyncSession, world
) -> None:
    world.reports["emeka"].state = PublicationState.PUBLISHED
    await session.commit()

    assert await ids_from(session, scope.scoped_term_reports(world.parent)) == set()


async def test_a_parent_may_acknowledge_only_a_published_report_of_their_own(
    session: AsyncSession, world
) -> None:
    world.reports["ada"].state = PublicationState.PUBLISHED
    world.reports["emeka"].state = PublicationState.PUBLISHED
    await session.commit()

    assert await policy.can_acknowledge_report(session, world.parent, world.reports["ada"].id)
    assert not await policy.can_acknowledge_report(session, world.parent, world.reports["emeka"].id)


async def test_staff_do_not_acknowledge_reports(session: AsyncSession, world) -> None:
    """§5.2: staff cannot read parent endpoints."""
    world.reports["ada"].state = PublicationState.PUBLISHED
    await session.commit()

    for user in (world.admin, world.head, world.teacher_a):
        assert not await policy.can_acknowledge_report(session, user, world.reports["ada"].id)


async def test_a_teacher_sees_reports_for_their_classes_in_any_state(
    session: AsyncSession, world
) -> None:
    """Staff need draft reports; the publication filter is a parent rule."""
    visible = await ids_from(session, scope.scoped_term_reports(world.teacher_b))

    assert visible == {world.reports["chidi"].id}


# ---------------------------------------------------------------------------
# Tenancy — the school_id filter on every scope
# ---------------------------------------------------------------------------


@pytest.fixture
async def other_school(session: AsyncSession, password_hash: str):
    """A second school. The column exists from the first migration precisely
    so this can never be an accident (§2.2)."""
    from types import SimpleNamespace

    from app.models import Class, Pupil

    record = School(name="Another School", short_name="OTHER")
    session.add(record)
    await session.flush()

    intruder = User(
        school_id=record.id,
        role=UserRole.ADMIN,
        full_name="Other Admin",
        email="admin@other.test",
        password_hash=password_hash,
        must_change_password=False,
    )
    klass = Class(school_id=record.id, name="Primary 4", level_order=4)
    pupil = Pupil(
        school_id=record.id,
        admission_number="OTHER/001",
        first_name="Someone",
        last_name="Else",
    )
    session.add_all([intruder, klass, pupil])
    await session.commit()

    return SimpleNamespace(school=record, admin=intruder, klass=klass, pupil=pupil)


async def test_another_school_s_admin_sees_nothing_of_ours(
    session: AsyncSession, world, other_school
) -> None:
    """A school-wide role is school-wide in *its own* school."""
    assert await ids_from(session, scope.scoped_classes(other_school.admin)) == {
        other_school.klass.id
    }
    assert await ids_from(session, scope.scoped_pupils(other_school.admin)) == {
        other_school.pupil.id
    }


async def test_our_admin_sees_nothing_of_theirs(session: AsyncSession, world, other_school) -> None:
    visible_classes = await ids_from(session, scope.scoped_classes(world.admin))
    visible_pupils = await ids_from(session, scope.scoped_pupils(world.admin))

    assert other_school.klass.id not in visible_classes
    assert other_school.pupil.id not in visible_pupils


async def test_every_scope_filters_by_school(session: AsyncSession, world, other_school) -> None:
    """Belt and braces: whatever the role, no scope may cross the tenant
    boundary."""
    from app.models import Class, Pupil

    total_classes = await session.scalar(select(func.count()).select_from(Class))
    assert total_classes == 3  # two of ours, one of theirs

    for user in (world.admin, world.head, world.teacher_a, world.specialist, world.parent):
        for statement in (
            scope.scoped_classes(user),
            scope.scoped_pupils(user),
            scope.scoped_class_subjects(user),
            scope.scoped_term_reports(user),
        ):
            rows = (await session.execute(statement)).scalars().all()
            assert all(row.school_id == world.school.id for row in rows)

    assert await session.scalar(select(func.count()).select_from(Pupil)) == 4
