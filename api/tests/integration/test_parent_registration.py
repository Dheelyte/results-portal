"""Parents sign themselves up; an admin approves (docs/DECISIONS.md D126)."""

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, UserRole

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
USERS = "/api/v1/users"
PASSWORD = "a long enough password"


async def sign_up(client: AsyncClient, **body):
    payload = {"full_name": "Ngozi Okafor", "phone": "08031234567", "password": PASSWORD}
    return await client.post(REGISTER, json=payload | body)


async def pending(client: AsyncClient, admin_headers) -> list[dict]:
    return (await client.get(USERS, headers=admin_headers, params={"pending": True})).json()


async def test_a_sign_up_waits_and_cannot_sign_in(
    client: AsyncClient, admin_headers, session: AsyncSession
) -> None:
    response = await sign_up(client)

    assert response.status_code == 202, response.text
    account = await session.scalar(select(User).where(User.phone == "08031234567"))
    assert (account.role, account.is_active, account.pending_approval) == (
        UserRole.PARENT,
        False,
        True,
    )
    right = await client.post(LOGIN, json={"identifier": "08031234567", "password": PASSWORD})
    wrong = await client.post(LOGIN, json={"identifier": "08031234567", "password": "nope"})
    assert right.status_code == 403
    assert "waiting for the school to approve" in right.json()["detail"]
    assert wrong.status_code == 401


async def test_a_taken_number_gets_the_same_answer_and_no_account(
    client: AsyncClient, admin_headers, make_user, session: AsyncSession
) -> None:
    """No enumeration: the form must not say which numbers are parents'."""
    existing = await make_user(UserRole.PARENT)
    before = await session.scalar(select(func.count()).select_from(User))

    fresh = await sign_up(client, phone="08099999999")
    clash = await sign_up(client, phone=None, email=existing.email)

    assert clash.status_code == fresh.status_code == 202
    assert clash.json() == fresh.json()
    assert await session.scalar(select(func.count()).select_from(User)) == before + 1


async def test_a_sign_up_needs_a_way_to_sign_in_and_a_real_password(
    client: AsyncClient,
) -> None:
    no_identifier = await sign_up(client, phone=None)
    short = await sign_up(client, password="short")

    assert no_identifier.status_code == 422
    assert short.status_code == 422


async def test_an_admin_approves_and_the_parent_signs_in(
    client: AsyncClient, admin_headers
) -> None:
    await sign_up(client)
    [account] = await pending(client, admin_headers)

    approved = await client.post(f"{USERS}/{account['id']}/approve", headers=admin_headers)
    login = await client.post(LOGIN, json={"identifier": "08031234567", "password": PASSWORD})

    assert approved.status_code == 200, approved.text
    assert approved.json()["pending_approval"] is False
    assert login.status_code == 200
    assert await pending(client, admin_headers) == []


async def test_rejecting_an_untouched_sign_up_deletes_it(
    client: AsyncClient, admin_headers, session: AsyncSession
) -> None:
    await sign_up(client)
    [account] = await pending(client, admin_headers)

    response = await client.post(f"{USERS}/{account['id']}/reject", headers=admin_headers)

    assert response.status_code == 200
    assert "removed" in response.json()["detail"]
    assert await session.scalar(select(User).where(User.phone == "08031234567")) is None


async def test_rejecting_after_a_failed_sign_in_keeps_it_deactivated(
    client: AsyncClient, admin_headers, session: AsyncSession
) -> None:
    await sign_up(client)
    await client.post(LOGIN, json={"identifier": "08031234567", "password": "wrong one"})
    [account] = await pending(client, admin_headers)

    response = await client.post(f"{USERS}/{account['id']}/reject", headers=admin_headers)

    assert response.status_code == 200
    assert "kept" in response.json()["detail"]
    session.expire_all()
    kept = await session.scalar(select(User).where(User.phone == "08031234567"))
    assert (kept.is_active, kept.pending_approval) == (False, False)


async def test_children_wait_for_approval_too(
    client: AsyncClient, admin_headers, session: AsyncSession
) -> None:
    await sign_up(client)
    [account] = await pending(client, admin_headers)

    response = await client.post(
        f"/api/v1/guardians/{account['id']}/children",
        headers=admin_headers,
        json={"children": [{"pupil_id": "00000000-0000-0000-0000-000000000000"}]},
    )

    assert response.status_code == 422
