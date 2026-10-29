"""Nobody but the head teacher reviews a class (§5.2).

§5.2's review rows read **✅ all** in the head teacher's column and a dash in
every other — including the admin's. That is the one most likely to surprise:
the admin sets the school up and publishes the results, but approving them is
the head teacher's judgement, and §1.6 keeps approve and publish as two steps
held by two people.

The admin's route to a changed grade is `PATCH /entries/{id}` after
publication (R13), audited and with a reason — not approval.
"""

import pytest
from httpx import AsyncClient

from app.models import UserRole
from tests.integration.routes import ANY_ID, call, ids_for

# §7's review block, as built in milestone 9.
REVIEW_ENDPOINTS: list[tuple[str, str, dict | None]] = [
    ("GET", f"/review/queue?term_id={ANY_ID}", None),
    ("GET", f"/classes/{ANY_ID}/review?term_id={ANY_ID}", None),
    (
        "PUT",
        f"/classes/{ANY_ID}/remarks?term_id={ANY_ID}",
        {"rows": [{"pupil_id": ANY_ID, "head_teacher_remark": "A good term."}]},
    ),
    ("POST", f"/classes/{ANY_ID}/approve?term_id={ANY_ID}", None),
    ("POST", f"/classes/{ANY_ID}/return?term_id={ANY_ID}", {"note": "Please check 4A maths."}),
]

# Every column of §5.2's review rows that holds a dash.
ROLES_WITHOUT_REVIEW = [UserRole.ADMIN, UserRole.TEACHER, UserRole.PARENT]


@pytest.mark.parametrize("case", REVIEW_ENDPOINTS, ids=ids_for)
@pytest.mark.parametrize("role", ROLES_WITHOUT_REVIEW, ids=lambda role: role.value)
async def test_only_the_head_teacher_reviews(
    client: AsyncClient, make_user, headers_for, case, role: UserRole
) -> None:
    user = await make_user(role)
    headers = await headers_for(user)

    response = await call(client, case, headers)

    assert response.status_code == 403, f"{case[0]} {case[1]} as {role.value}"
    assert response.json()["detail"] == "Your role does not permit this action."


@pytest.mark.parametrize("case", REVIEW_ENDPOINTS, ids=ids_for)
async def test_the_review_surface_requires_authentication(client: AsyncClient, case) -> None:
    response = await call(client, case, None)

    assert response.status_code == 401


@pytest.mark.parametrize("case", REVIEW_ENDPOINTS, ids=ids_for)
async def test_a_head_teacher_owing_a_password_change_is_stopped_first(
    client: AsyncClient, make_user, login, case
) -> None:
    head = await make_user(UserRole.HEAD_TEACHER, must_change_password=True)
    token = (await login(head.email)).json()["access_token"]

    response = await call(client, case, {"Authorization": f"Bearer {token}"})

    assert response.status_code == 409
    assert "change your password" in response.json()["detail"]


async def test_a_head_teacher_sees_no_other_schools_classes(
    client: AsyncClient, session, headers_for, world, password_hash
) -> None:
    """§2.2: "✅ all" means every class in **their** school."""
    from app.models import School, User

    other_school = School(name="Another School", short_name="AS")
    session.add(other_school)
    await session.flush()
    intruder = User(
        school_id=other_school.id,
        role=UserRole.HEAD_TEACHER,
        full_name="Elsewhere",
        email="head@other.test",
        password_hash=password_hash,
        must_change_password=False,
    )
    session.add(intruder)
    await session.commit()

    headers = await headers_for(intruder)

    response = await client.get(
        f"/api/v1/classes/{world.class_4a.id}/review",
        params={"term_id": str(world.term.id)},
        headers=headers,
    )

    assert response.status_code == 404


async def test_the_head_teacher_sees_every_class_in_their_own_school(
    client: AsyncClient, headers_for, world
) -> None:
    """Both classes, neither of which they teach. That is what "all" means."""
    headers = await headers_for(world.head)

    for class_id in (world.class_4a.id, world.class_5b.id):
        response = await client.get(
            f"/api/v1/classes/{class_id}/review",
            params={"term_id": str(world.term.id)},
            headers=headers,
        )
        assert response.status_code == 200, response.text
