"""Head teachers and admins who teach (docs/DECISIONS.md D123).

Either can be made a class teacher or a subject teacher. The role grant is
scoped, so it lets them act only where an assignment names them. And nobody
approves or returns a class they teach in: the head teacher hands that class
to an admin.
"""

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ClassTermState, ClassTermStatus

API = "/api/v1"


async def assign_subject(client, admin, class_subject_id, teacher_id) -> None:
    response = await client.put(
        f"{API}/class-subjects/{class_subject_id}/teacher",
        headers=admin,
        json={"teacher_user_id": str(teacher_id)},
    )
    assert response.status_code == 200, response.text


async def assign_class(client, admin, class_id, teacher_id) -> None:
    response = await client.put(
        f"{API}/classes/{class_id}/class-teacher",
        headers=admin,
        json={"teacher_user_id": str(teacher_id)},
    )
    assert response.status_code == 200, response.text


async def test_a_head_teacher_or_admin_can_be_assigned(
    client: AsyncClient, world, headers_for
) -> None:
    admin = await headers_for(world.admin)

    await assign_subject(client, admin, world.maths_4a.id, world.head.id)
    await assign_subject(client, admin, world.french_4a.id, world.admin.id)
    await assign_class(client, admin, world.class_5b.id, world.head.id)


async def test_my_work_is_only_what_is_assigned(client: AsyncClient, world, headers_for) -> None:
    """A school-wide scope must not turn "my work" into every class."""
    admin = await headers_for(world.admin)
    await assign_subject(client, admin, world.maths_4a.id, world.head.id)
    head = await headers_for(world.head)

    body = (await client.get(f"{API}/my/assignments", headers=head)).json()

    assert [row["class_subject_id"] for row in body["assignments"]] == [str(world.maths_4a.id)]
    assert body["class_teacher_of"] == []


async def test_an_unassigned_head_teacher_cannot_enter_scores(
    client: AsyncClient, world, headers_for
) -> None:
    head = await headers_for(world.head)
    pupil = next(iter(world.pupils.values()))
    period = str(uuid.uuid4())  # refused on the class-subject before the period matters

    response = await client.put(
        f"{API}/class-subjects/{world.maths_4a.id}/entries",
        headers=head,
        json={
            "assessment_period_id": period,
            "rows": [{"pupil_id": str(pupil.id), "ca_test_1": "5"}],
        },
    )

    assert response.status_code in (403, 404), response.text


async def test_a_head_teacher_cannot_decide_on_a_class_they_teach_in(
    client: AsyncClient, world, headers_for
) -> None:
    admin = await headers_for(world.admin)
    await assign_subject(client, admin, world.maths_4a.id, world.head.id)
    head = await headers_for(world.head)
    params = {"term_id": str(world.term.id)}

    review = await client.get(
        f"{API}/classes/{world.class_4a.id}/review", headers=head, params=params
    )
    approve = await client.post(
        f"{API}/classes/{world.class_4a.id}/approve", headers=head, params=params
    )
    other = await client.get(
        f"{API}/classes/{world.class_5b.id}/review", headers=head, params=params
    )

    assert "An admin decides on it instead" in review.json()["decision_blocked"]
    assert approve.status_code == 409
    assert "You teach in this class" in approve.json()["detail"]
    assert other.json()["decision_blocked"] is None


async def test_an_admin_decides_only_on_a_class_the_head_teacher_teaches_in(
    client: AsyncClient, world, headers_for
) -> None:
    admin = await headers_for(world.admin)
    await assign_class(client, admin, world.class_4a.id, world.head.id)
    params = {"term_id": str(world.term.id)}

    handed_over = await client.get(
        f"{API}/classes/{world.class_4a.id}/review", headers=admin, params=params
    )
    not_theirs = await client.post(
        f"{API}/classes/{world.class_5b.id}/approve", headers=admin, params=params
    )

    assert handed_over.json()["decision_blocked"] is None
    assert not_theirs.status_code == 409
    assert "The head teacher reviews this class" in not_theirs.json()["detail"]


async def test_the_admins_queue_holds_only_the_handed_over_class(
    client: AsyncClient, world, headers_for, session: AsyncSession
) -> None:
    for klass in (world.class_4a, world.class_5b):
        session.add(
            ClassTermStatus(
                school_id=world.school.id,
                class_id=klass.id,
                term_id=world.term.id,
                state=ClassTermState.SUBMITTED,
            )
        )
    await session.commit()
    admin = await headers_for(world.admin)
    await assign_class(client, admin, world.class_4a.id, world.head.id)
    params = {"term_id": str(world.term.id)}

    admins = (await client.get(f"{API}/review/queue", headers=admin, params=params)).json()
    heads = (
        await client.get(
            f"{API}/review/queue", headers=await headers_for(world.head), params=params
        )
    ).json()

    assert [row["class_id"] for row in admins] == [str(world.class_4a.id)]
    blocked = {row["class_id"]: row["decision_blocked"] for row in heads}
    assert blocked[str(world.class_5b.id)] is None
    assert "An admin decides" in blocked[str(world.class_4a.id)]
