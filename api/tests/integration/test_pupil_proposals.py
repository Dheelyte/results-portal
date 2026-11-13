"""A class teacher adds a pupil; an admin approves (docs/DECISIONS.md D125)."""

from httpx import AsyncClient

API = "/api/v1"
NEW = {"first_name": "Chidi", "last_name": "Nwosu", "sex": "M"}


async def propose(client, headers, class_id, body=NEW):
    return await client.post(f"{API}/classes/{class_id}/pupils", headers=headers, json=body)


async def test_the_class_teacher_adds_a_pupil_who_waits(
    client: AsyncClient, world, headers_for
) -> None:
    teacher = await headers_for(world.teacher_a)  # class teacher of 4A

    response = await propose(client, teacher, world.class_4a.id)

    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["pending_approval"], body["is_active"]) == (True, False)
    waiting = (
        await client.get(f"{API}/classes/{world.class_4a.id}/pupils/proposed", headers=teacher)
    ).json()
    assert [row["id"] for row in waiting] == [body["id"]]


async def test_a_waiting_pupil_is_on_no_list(client: AsyncClient, world, headers_for) -> None:
    teacher = await headers_for(world.teacher_a)
    pupil = (await propose(client, teacher, world.class_4a.id)).json()
    admin = await headers_for(world.admin)

    roll = (
        await client.get(
            f"{API}/pupils", headers=admin, params={"class_id": str(world.class_4a.id)}
        )
    ).json()
    attendance = (
        await client.get(
            f"{API}/classes/{world.class_4a.id}/attendance",
            headers=teacher,
            params={"term_id": str(world.term.id)},
        )
    ).json()
    waiting = (await client.get(f"{API}/pupils", headers=admin, params={"pending": True})).json()

    assert pupil["id"] not in {row["id"] for row in roll["items"]}
    assert pupil["id"] not in {row["pupil_id"] for row in attendance["rows"]}
    assert [row["id"] for row in waiting["items"]] == [pupil["id"]]


async def test_only_that_class_teacher_can_add(client: AsyncClient, world, headers_for) -> None:
    other_class_teacher = await headers_for(world.teacher_b)
    subject_teacher = await headers_for(world.specialist)

    assert (await propose(client, other_class_teacher, world.class_4a.id)).status_code == 404
    assert (await propose(client, subject_teacher, world.class_4a.id)).status_code == 404


async def test_an_admin_approves_and_the_pupil_joins_the_class(
    client: AsyncClient, world, headers_for
) -> None:
    pupil = (await propose(client, await headers_for(world.teacher_a), world.class_4a.id)).json()
    admin = await headers_for(world.admin)

    approved = await client.post(f"{API}/pupils/{pupil['id']}/approve", headers=admin)
    again = await client.post(f"{API}/pupils/{pupil['id']}/approve", headers=admin)
    roll = (
        await client.get(
            f"{API}/pupils", headers=admin, params={"class_id": str(world.class_4a.id)}
        )
    ).json()

    assert approved.status_code == 200, approved.text
    assert (approved.json()["pending_approval"], approved.json()["is_active"]) == (False, True)
    assert again.status_code == 409
    assert pupil["id"] in {row["id"] for row in roll["items"]}


async def test_an_admin_rejects_by_deleting(client: AsyncClient, world, headers_for) -> None:
    pupil = (await propose(client, await headers_for(world.teacher_a), world.class_4a.id)).json()

    response = await client.delete(
        f"{API}/pupils/{pupil['id']}", headers=await headers_for(world.admin)
    )

    assert response.status_code == 204


async def test_no_parent_is_linked_to_a_waiting_pupil(
    client: AsyncClient, world, headers_for
) -> None:
    pupil = (await propose(client, await headers_for(world.teacher_a), world.class_4a.id)).json()

    response = await client.post(
        f"{API}/guardians/{world.parent.id}/children",
        headers=await headers_for(world.admin),
        json={"children": [{"pupil_id": pupil["id"]}]},
    )

    assert response.status_code == 422
    assert "must be approved" in response.json()["detail"]
