"""Pupils, accounts and the guardian link over HTTP (§4.1, §5.1, §7).

Two things here matter more than the rest. A temporary password is shown once
and never stored readably, logged or audited. And `guardian_pupils` is the
record §5.2's most important filter rests on — a parent sees exactly the
pupils named there.
"""

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditAction, AuditLog, RefreshToken, UserRole
from tests.conftest import TEST_PASSWORD
from tests.integration.test_admin_academic import make_session
from tests.integration.test_admin_structure import a_class

PUPILS = "/api/v1/pupils"
USERS = "/api/v1/users"


async def a_pupil(client: AsyncClient, headers, **payload) -> dict:
    body = {
        "admission_number": "SSHMS/2026/001",
        "first_name": "Ada",
        "last_name": "Okafor",
    } | payload
    response = await client.post(PUPILS, headers=headers, json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def an_account(client: AsyncClient, headers, **payload) -> dict:
    body = {"role": "teacher", "full_name": "A Teacher", "email": "teacher@sshms.test"} | payload
    response = await client.post(USERS, headers=headers, json=body)
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Pupils
# ---------------------------------------------------------------------------


async def test_an_admin_adds_a_pupil(client: AsyncClient, admin_headers) -> None:
    body = await a_pupil(client, admin_headers)

    assert body["admission_number"] == "SSHMS/2026/001"
    assert body["is_active"] is True


async def test_a_pupil_can_be_enrolled_on_creation(client: AsyncClient, admin_headers) -> None:
    academic = await make_session(client, admin_headers)
    klass = await a_class(client, admin_headers)

    await a_pupil(client, admin_headers, class_id=klass["id"])

    listed = (
        await client.get(PUPILS, headers=admin_headers, params={"class_id": klass["id"]})
    ).json()

    assert listed["total"] == 1
    assert academic["is_current"] is True


async def test_a_duplicate_admission_number_is_refused_without_naming_the_child(
    client: AsyncClient, admin_headers
) -> None:
    """CLAUDE.md keeps a pupil's identity out of an error message, so the
    message must not confirm which child already holds the number."""
    await a_pupil(client, admin_headers)

    response = await client.post(
        PUPILS,
        headers=admin_headers,
        json={
            "admission_number": "SSHMS/2026/001",
            "first_name": "Different",
            "last_name": "Child",
        },
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail == "A pupil with that admission number already exists."
    assert "Ada" not in detail
    assert "SSHMS" not in detail


async def test_sex_must_be_m_or_f(client: AsyncClient, admin_headers) -> None:
    """As the card records it."""
    response = await client.post(
        PUPILS,
        headers=admin_headers,
        json={
            "admission_number": "SSHMS/2026/002",
            "first_name": "Ada",
            "last_name": "Okafor",
            "sex": "X",
        },
    )

    assert response.status_code == 422


async def test_pupils_can_be_searched_by_name_or_number(client: AsyncClient, admin_headers) -> None:
    await a_pupil(client, admin_headers, admission_number="A/1", first_name="Ada")
    await a_pupil(client, admin_headers, admission_number="B/2", first_name="Chidi")

    by_name = (await client.get(PUPILS, headers=admin_headers, params={"search": "chid"})).json()
    by_number = (await client.get(PUPILS, headers=admin_headers, params={"search": "A/1"})).json()

    assert [item["first_name"] for item in by_name["items"]] == ["Chidi"]
    assert [item["first_name"] for item in by_number["items"]] == ["Ada"]


async def test_the_roll_is_paged(client: AsyncClient, admin_headers) -> None:
    """Roughly five hundred pupils; nothing returns the whole roll at once."""
    for index in range(5):
        await a_pupil(
            client,
            admin_headers,
            admission_number=f"SSHMS/2026/{index:03d}",
            first_name=f"Child{index}",
        )

    page = (
        await client.get(PUPILS, headers=admin_headers, params={"limit": 2, "offset": 2})
    ).json()

    assert page["total"] == 5
    assert len(page["items"]) == 2
    assert page["offset"] == 2


async def test_a_pupil_can_be_moved_to_another_class(client: AsyncClient, admin_headers) -> None:
    """Pupils change class mid-year, and a roll typed in before the classes
    were settled needs placing afterwards."""
    await make_session(client, admin_headers)
    first = await a_class(client, admin_headers, name="Primary 4", level_order=4)
    second = await a_class(client, admin_headers, name="Primary 5", level_order=5)
    pupil = await a_pupil(client, admin_headers, class_id=first["id"])

    response = await client.put(
        f"{PUPILS}/{pupil['id']}/enrollment",
        headers=admin_headers,
        json={"class_id": second["id"]},
    )

    assert response.status_code == 200, response.text
    assert response.json()["class_id"] == second["id"]

    in_first = (
        await client.get(PUPILS, headers=admin_headers, params={"class_id": first["id"]})
    ).json()
    assert in_first["total"] == 0


async def test_a_house_from_another_school_is_a_404(
    client: AsyncClient, admin_headers, session: AsyncSession
) -> None:
    from app.models import House, School

    other = School(name="Another School", short_name="AS")
    session.add(other)
    await session.flush()
    house = House(school_id=other.id, name="Blue")
    session.add(house)
    await session.commit()

    response = await client.post(
        PUPILS,
        headers=admin_headers,
        json={
            "admission_number": "SSHMS/2026/003",
            "first_name": "Ada",
            "last_name": "Okafor",
            "house_id": str(house.id),
        },
    )

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------


async def test_creating_an_account_returns_a_temporary_password(
    client: AsyncClient, admin_headers
) -> None:
    body = await an_account(client, admin_headers)

    assert body["temporary_password"]
    assert body["user"]["must_change_password"] is True
    assert "password_hash" not in body["user"]


async def test_the_temporary_password_actually_works(
    client: AsyncClient, admin_headers, login
) -> None:
    """And the holder is then stopped at the change-password gate (§5.1)."""
    created = await an_account(client, admin_headers)

    response = await login("teacher@sshms.test", created["temporary_password"])
    assert response.status_code == 200
    token = response.json()["access_token"]

    blocked = await client.get("/api/v1/sessions", headers={"Authorization": f"Bearer {token}"})
    assert blocked.status_code == 409


async def test_an_account_needs_an_email_or_a_phone(client: AsyncClient, admin_headers) -> None:
    """A7: many parents' email addresses are inactive, so either will do —
    but an account with neither cannot be told how to sign in."""
    response = await client.post(
        USERS, headers=admin_headers, json={"role": "parent", "full_name": "A Parent"}
    )

    assert response.status_code == 422
    assert "email address or a phone number" in response.json()["detail"]


async def test_a_blank_identifier_is_not_an_identifier(client: AsyncClient, admin_headers) -> None:
    """An empty string satisfies the database CHECK while being unusable."""
    response = await client.post(
        USERS,
        headers=admin_headers,
        json={"role": "parent", "full_name": "A Parent", "email": "   ", "phone": ""},
    )

    assert response.status_code == 422


async def test_a_parent_can_be_created_with_only_a_phone(
    client: AsyncClient, admin_headers, login
) -> None:
    created = await an_account(
        client,
        admin_headers,
        role="parent",
        full_name="A Parent",
        email=None,
        phone="08030000001",
    )

    response = await login("08030000001", created["temporary_password"])

    assert response.status_code == 200


async def test_a_duplicate_email_is_a_conflict(client: AsyncClient, admin_headers) -> None:
    await an_account(client, admin_headers)

    response = await client.post(
        USERS,
        headers=admin_headers,
        json={"role": "teacher", "full_name": "Someone Else", "email": "teacher@sshms.test"},
    )

    assert response.status_code == 409


async def test_a_reset_issues_a_new_password_and_kills_live_sessions(
    client: AsyncClient, admin_headers, make_user, headers_for, session: AsyncSession
) -> None:
    """What an admin does when a password has been passed around. Leaving the
    existing sessions alive would defeat it."""
    teacher = await make_user(UserRole.TEACHER)
    await headers_for(teacher)

    live = await session.scalar(
        select(func.count(RefreshToken.id)).where(
            RefreshToken.user_id == teacher.id, RefreshToken.revoked_at.is_(None)
        )
    )
    assert live == 1

    response = await client.post(f"{USERS}/{teacher.id}/reset-password", headers=admin_headers)

    assert response.status_code == 200
    assert response.json()["temporary_password"]
    assert response.json()["user"]["must_change_password"] is True

    remaining = await session.scalar(
        select(func.count(RefreshToken.id)).where(
            RefreshToken.user_id == teacher.id, RefreshToken.revoked_at.is_(None)
        )
    )
    assert remaining == 0


async def test_a_reset_clears_a_lockout(
    client: AsyncClient, admin_headers, make_user, login, session: AsyncSession
) -> None:
    """An account locked by failed attempts is exactly the account whose owner
    rings the school."""
    from app.config import settings

    teacher = await make_user(UserRole.TEACHER)
    for _ in range(settings.max_failed_attempts):
        await login(teacher.email, "wrong-password-entirely")
    assert (await login(teacher.email)).status_code == 423

    reset = (
        await client.post(f"{USERS}/{teacher.id}/reset-password", headers=admin_headers)
    ).json()

    assert (await login(teacher.email, reset["temporary_password"])).status_code == 200


async def test_a_temporary_password_never_reaches_the_audit_log(
    client: AsyncClient, admin_headers, session: AsyncSession
) -> None:
    created = await an_account(client, admin_headers)

    rows = (
        (
            await session.execute(
                select(AuditLog).where(
                    AuditLog.action.in_([AuditAction.USER_CREATED, AuditAction.PASSWORD_RESET])
                )
            )
        )
        .scalars()
        .all()
    )

    assert rows
    for row in rows:
        serialised = f"{row.before} {row.after}"
        assert created["temporary_password"] not in serialised
        assert "password_hash" not in serialised


async def test_account_creation_and_resets_are_audited(
    client: AsyncClient, admin_headers, make_user, session: AsyncSession
) -> None:
    """§4.9 requires a row for both."""
    await an_account(client, admin_headers)
    teacher = await make_user(UserRole.TEACHER)
    await client.post(f"{USERS}/{teacher.id}/reset-password", headers=admin_headers)

    created = await session.scalar(
        select(func.count(AuditLog.id)).where(AuditLog.action == AuditAction.USER_CREATED)
    )
    reset = await session.scalar(
        select(func.count(AuditLog.id)).where(AuditLog.action == AuditAction.PASSWORD_RESET)
    )

    assert created == 1
    assert reset == 1


# ---------------------------------------------------------------------------
# The guardian link
# ---------------------------------------------------------------------------


async def test_attaching_children_to_a_parent(client: AsyncClient, admin_headers) -> None:
    parent = await an_account(
        client, admin_headers, role="parent", full_name="A Parent", email="parent@sshms.test"
    )
    first = await a_pupil(client, admin_headers, admission_number="A/1", first_name="Ada")
    second = await a_pupil(client, admin_headers, admission_number="B/2", first_name="Chidi")

    response = await client.post(
        f"/api/v1/guardians/{parent['user']['id']}/children",
        headers=admin_headers,
        json={
            "children": [
                {"pupil_id": first["id"], "relationship": "Mother", "is_primary": True},
                {"pupil_id": second["id"]},
            ]
        },
    )

    assert response.status_code == 200, response.text
    assert {item["id"] for item in response.json()} == {first["id"], second["id"]}


async def test_attaching_is_additive(client: AsyncClient, admin_headers) -> None:
    """Adding a second child later must not detach the first."""
    parent = await an_account(
        client, admin_headers, role="parent", full_name="A Parent", email="parent@sshms.test"
    )
    first = await a_pupil(client, admin_headers, admission_number="A/1", first_name="Ada")
    second = await a_pupil(client, admin_headers, admission_number="B/2", first_name="Chidi")
    url = f"/api/v1/guardians/{parent['user']['id']}/children"

    await client.post(url, headers=admin_headers, json={"children": [{"pupil_id": first["id"]}]})
    response = await client.post(
        url, headers=admin_headers, json={"children": [{"pupil_id": second["id"]}]}
    )

    assert len(response.json()) == 2


async def test_children_cannot_be_attached_to_a_teacher(client: AsyncClient, admin_headers) -> None:
    teacher = await an_account(client, admin_headers)
    pupil = await a_pupil(client, admin_headers)

    response = await client.post(
        f"/api/v1/guardians/{teacher['user']['id']}/children",
        headers=admin_headers,
        json={"children": [{"pupil_id": pupil["id"]}]},
    )

    assert response.status_code == 422
    assert "not a parent account" in response.json()["detail"]


async def test_the_guardian_link_is_audited_without_naming_the_children(
    client: AsyncClient, admin_headers, session: AsyncSession
) -> None:
    parent = await an_account(
        client, admin_headers, role="parent", full_name="A Parent", email="parent@sshms.test"
    )
    pupil = await a_pupil(client, admin_headers, first_name="Ada", last_name="Okafor")

    await client.post(
        f"/api/v1/guardians/{parent['user']['id']}/children",
        headers=admin_headers,
        json={"children": [{"pupil_id": pupil["id"]}]},
    )

    row = (
        await session.execute(
            select(AuditLog).where(AuditLog.action == AuditAction.GUARDIAN_CHILDREN_SET)
        )
    ).scalar_one()

    assert pupil["id"] in row.after["pupil_ids"]
    assert "Ada" not in f"{row.after}"
    assert "Okafor" not in f"{row.after}"


async def test_an_unknown_pupil_is_refused_vaguely(client: AsyncClient, admin_headers) -> None:
    """Confirming which id is unknown would let ids be probed for existence."""
    import uuid

    parent = await an_account(
        client, admin_headers, role="parent", full_name="A Parent", email="parent@sshms.test"
    )

    response = await client.post(
        f"/api/v1/guardians/{parent['user']['id']}/children",
        headers=admin_headers,
        json={"children": [{"pupil_id": str(uuid.uuid4())}]},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "One or more of those pupils does not exist."


async def test_an_admin_sees_a_parents_children(client: AsyncClient, admin_headers) -> None:
    parent = await an_account(
        client, admin_headers, role="parent", full_name="A Parent", email="parent@sshms.test"
    )
    pupil = await a_pupil(client, admin_headers)
    url = f"/api/v1/guardians/{parent['user']['id']}/children"
    await client.post(url, headers=admin_headers, json={"children": [{"pupil_id": pupil["id"]}]})

    response = await client.get(url, headers=admin_headers)

    assert [item["id"] for item in response.json()] == [pupil["id"]]


async def test_the_password_the_test_suite_uses_still_works(
    client: AsyncClient, make_user, login
) -> None:
    """A canary: if the shared fixture password stops working, half the
    failures above would be misleading."""
    user = await make_user(UserRole.ADMIN)

    assert (await login(user.email, TEST_PASSWORD)).status_code == 200
