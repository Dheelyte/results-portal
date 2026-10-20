"""Authentication endpoints and rules (ARCHITECTURE.md §5.1, §7).

Milestone 2's done-when is "auth tests pass for all four roles", so the role
matrix is asserted explicitly rather than implied by one admin test.
"""

import datetime as dt

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.config import settings
from app.models import AuditAction, AuditLog, RefreshToken, User, UserRole
from app.routers.auth import REFRESH_COOKIE_NAME
from tests.conftest import TEST_PASSWORD

LOGIN = "/api/v1/auth/login"
REFRESH = "/api/v1/auth/refresh"
LOGOUT = "/api/v1/auth/logout"
CHANGE_PASSWORD = "/api/v1/auth/change-password"
ME = "/api/v1/auth/me"


async def refresh_with(client: AsyncClient, token: str):
    """POST /refresh presenting a specific token.

    httpx deprecates per-request cookies, so the client's jar is set instead.
    """
    client.cookies.set(REFRESH_COOKIE_NAME, token)
    return await client.post(REFRESH)


# ---------------------------------------------------------------------------
# All four roles — the milestone's done-when
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role", list(UserRole))
async def test_every_role_can_sign_in(role: UserRole, make_user, login) -> None:
    user = await make_user(role)

    response = await login(user.email)

    assert response.status_code == 200
    body = response.json()
    assert body["user"]["role"] == role.value
    assert body["user"]["id"] == str(user.id)
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == settings.access_token_minutes * 60


@pytest.mark.parametrize("role", list(UserRole))
async def test_every_role_is_refused_a_wrong_password(role: UserRole, make_user, login) -> None:
    user = await make_user(role)

    response = await login(user.email, "not-the-password")

    assert response.status_code == 401


@pytest.mark.parametrize("role", list(UserRole))
async def test_every_role_can_reach_me_with_its_token(
    role: UserRole, make_user, login, client: AsyncClient
) -> None:
    user = await make_user(role)
    token = (await login(user.email)).json()["access_token"]

    response = await client.get(ME, headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["role"] == role.value


@pytest.mark.parametrize("role", list(UserRole))
async def test_every_role_can_rotate_and_sign_out(
    role: UserRole, make_user, login, client: AsyncClient
) -> None:
    user = await make_user(role)
    await login(user.email)

    assert (await client.post(REFRESH)).status_code == 200
    assert (await client.post(LOGOUT)).status_code == 200


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


async def test_a_parent_may_sign_in_with_a_phone_number(make_user, login) -> None:
    """§5.1 and A7: many parents' email addresses are inactive."""
    await make_user(UserRole.PARENT, email=None, phone="+2348012345678")

    response = await login("+2348012345678")

    assert response.status_code == 200
    assert response.json()["user"]["phone"] == "+2348012345678"


async def test_email_matching_ignores_case(make_user, login) -> None:
    """users.email is citext — a parent will not type it the same way twice."""
    await make_user(UserRole.PARENT, email="Ada.Okafor@Example.Test")

    assert (await login("ada.okafor@example.test")).status_code == 200
    assert (await login("ADA.OKAFOR@EXAMPLE.TEST")).status_code == 200


async def test_an_unknown_identifier_and_a_wrong_password_are_indistinguishable(
    make_user, login
) -> None:
    """Otherwise the login form enumerates accounts, and a parent's phone
    number is guessable."""
    user = await make_user(UserRole.PARENT)

    unknown = await login("nobody@nowhere.test")
    wrong = await login(user.email, "not-the-password")

    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()


async def test_a_deactivated_account_cannot_sign_in(make_user, login) -> None:
    user = await make_user(UserRole.TEACHER, is_active=False)

    assert (await login(user.email)).status_code == 401


async def test_the_response_never_carries_the_password_hash(make_user, login) -> None:
    user = await make_user(UserRole.ADMIN)

    body = (await login(user.email)).text

    assert "password_hash" not in body
    assert "$argon2" not in body
    assert TEST_PASSWORD not in body


async def test_the_refresh_token_is_not_in_the_body(make_user, login) -> None:
    """It travels only in an httpOnly cookie; in the body any XSS would have
    a 30-day credential."""
    user = await make_user(UserRole.ADMIN)

    response = await login(user.email)

    assert "refresh_token" not in response.json()
    assert REFRESH_COOKIE_NAME in response.cookies


async def test_the_refresh_cookie_is_httponly_and_scoped(make_user, login) -> None:
    user = await make_user(UserRole.ADMIN)

    response = await login(user.email)
    cookie = response.headers["set-cookie"]

    assert "HttpOnly" in cookie
    assert f"Path={settings.api_v1_prefix}/auth" in cookie
    assert "SameSite=lax" in cookie.lower().replace("samesite=lax", "SameSite=lax")
    # Host-only: no Domain attribute, so sibling subdomains never see it.
    assert "domain=" not in cookie.lower()


async def test_successful_login_stamps_the_time_and_clears_the_counter(
    make_user, login, session
) -> None:
    user = await make_user(UserRole.TEACHER)
    await login(user.email, "wrong")
    await login(user.email)

    refreshed = await session.get(User, user.id)
    await session.refresh(refreshed)

    assert refreshed.failed_attempts == 0
    assert refreshed.last_login_at is not None


# ---------------------------------------------------------------------------
# Lockout (§5.1: 15 minutes after 5 failed attempts)
# ---------------------------------------------------------------------------


async def test_the_account_locks_on_the_fifth_failure(make_user, login, session) -> None:
    user = await make_user(UserRole.TEACHER)

    for attempt in range(settings.max_failed_attempts - 1):
        assert (await login(user.email, "wrong")).status_code == 401, attempt

    # The fifth failure locks it; the response is still 401, not 423, because
    # the password was wrong *and* the lock has just been applied.
    assert (await login(user.email, "wrong")).status_code == 401

    locked = await session.get(User, user.id)
    await session.refresh(locked)
    assert locked.locked_until is not None


async def test_a_locked_account_is_refused_even_with_the_right_password(make_user, login) -> None:
    user = await make_user(UserRole.TEACHER)

    for _ in range(settings.max_failed_attempts):
        await login(user.email, "wrong")

    response = await login(user.email)

    assert response.status_code == 423
    assert "locked" in response.json()["detail"].lower()


async def test_the_lock_lasts_the_configured_time(make_user, login, session) -> None:
    user = await make_user(UserRole.TEACHER)

    for _ in range(settings.max_failed_attempts):
        await login(user.email, "wrong")

    locked = await session.get(User, user.id)
    await session.refresh(locked)
    remaining = locked.locked_until - dt.datetime.now(dt.UTC)

    assert dt.timedelta(minutes=settings.lockout_minutes - 1) < remaining
    assert remaining <= dt.timedelta(minutes=settings.lockout_minutes)


async def test_an_expired_lock_releases_the_account(make_user, login, session) -> None:
    user = await make_user(UserRole.TEACHER)
    for _ in range(settings.max_failed_attempts):
        await login(user.email, "wrong")

    # Wind the clock back rather than wait fifteen minutes.
    locked = await session.get(User, user.id)
    await session.refresh(locked)
    locked.locked_until = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1)
    await session.commit()

    assert (await login(user.email)).status_code == 200


async def test_the_counter_resets_with_the_lock(make_user, login, session) -> None:
    """After a lock expires the user gets a fresh allowance, rather than being
    re-locked by a single further mistake."""
    user = await make_user(UserRole.TEACHER)
    for _ in range(settings.max_failed_attempts):
        await login(user.email, "wrong")

    locked = await session.get(User, user.id)
    await session.refresh(locked)

    assert locked.failed_attempts == 0


# ---------------------------------------------------------------------------
# Refresh rotation and reuse detection
# ---------------------------------------------------------------------------


async def test_refresh_issues_a_new_token_pair(make_user, login, client: AsyncClient) -> None:
    user = await make_user(UserRole.TEACHER)
    first = (await login(user.email)).json()["access_token"]
    first_cookie = client.cookies[REFRESH_COOKIE_NAME]

    response = await client.post(REFRESH)

    assert response.status_code == 200
    assert client.cookies[REFRESH_COOKIE_NAME] != first_cookie
    assert response.json()["user"]["id"] == str(user.id)
    assert isinstance(first, str)


async def test_a_rotated_token_cannot_be_used_again(make_user, login, client: AsyncClient) -> None:
    user = await make_user(UserRole.TEACHER)
    await login(user.email)
    stale = client.cookies[REFRESH_COOKIE_NAME]

    await client.post(REFRESH)

    replayed = await refresh_with(client, stale)
    assert replayed.status_code == 401


async def test_reuse_revokes_the_whole_family(make_user, login, client: AsyncClient) -> None:
    """A replayed token means the chain has leaked. Revoking only that token
    would leave the attacker's successor working."""
    user = await make_user(UserRole.TEACHER)
    await login(user.email)
    stale = client.cookies[REFRESH_COOKIE_NAME]

    await client.post(REFRESH)
    current = client.cookies[REFRESH_COOKIE_NAME]

    await refresh_with(client, stale)

    # The legitimate successor is dead too. That is the intended outcome: the
    # user signs in again and the stolen token is worthless.
    assert (await refresh_with(client, current)).status_code == 401


async def test_rotation_keeps_the_family_and_links_the_chain(
    make_user, login, client: AsyncClient, session
) -> None:
    user = await make_user(UserRole.TEACHER)
    await login(user.email)
    await client.post(REFRESH)

    rows = (
        (await session.execute(select(RefreshToken).order_by(RefreshToken.issued_at)))
        .scalars()
        .all()
    )

    assert len(rows) == 2
    assert rows[0].family_id == rows[1].family_id
    assert rows[0].replaced_by == rows[1].id
    assert rows[0].revoked_at is not None
    assert rows[1].revoked_at is None


async def test_an_unknown_refresh_token_is_refused(client: AsyncClient) -> None:
    response = await refresh_with(client, "not-a-real-token")

    assert response.status_code == 401


async def test_refresh_without_a_cookie_is_refused(client: AsyncClient) -> None:
    assert (await client.post(REFRESH)).status_code == 401


async def test_an_expired_refresh_token_is_refused(
    make_user, login, client: AsyncClient, session
) -> None:
    user = await make_user(UserRole.TEACHER)
    await login(user.email)

    row = (await session.execute(select(RefreshToken))).scalars().one()
    row.expires_at = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1)
    await session.commit()

    assert (await client.post(REFRESH)).status_code == 401


async def test_a_deactivated_user_cannot_refresh(
    make_user, login, client: AsyncClient, session
) -> None:
    user = await make_user(UserRole.TEACHER)
    await login(user.email)

    record = await session.get(User, user.id)
    record.is_active = False
    await session.commit()

    assert (await client.post(REFRESH)).status_code == 401


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------


async def test_logout_revokes_the_session(make_user, login, client: AsyncClient) -> None:
    user = await make_user(UserRole.TEACHER)
    await login(user.email)
    cookie = client.cookies[REFRESH_COOKIE_NAME]

    assert (await client.post(LOGOUT)).status_code == 200
    assert (await refresh_with(client, cookie)).status_code == 401


async def test_logout_without_a_session_still_succeeds(client: AsyncClient) -> None:
    """A logout that finds nothing to revoke has achieved what was asked."""
    assert (await client.post(LOGOUT)).status_code == 200


async def test_logout_revokes_the_whole_chain(make_user, login, client: AsyncClient, session):
    user = await make_user(UserRole.TEACHER)
    await login(user.email)
    await client.post(REFRESH)
    await client.post(LOGOUT)

    unrevoked = await session.scalar(
        select(func.count()).select_from(RefreshToken).where(RefreshToken.revoked_at.is_(None))
    )

    assert unrevoked == 0


# ---------------------------------------------------------------------------
# Change password and the must_change_password gate
# ---------------------------------------------------------------------------


async def test_a_user_can_change_their_password(make_user, login, client: AsyncClient) -> None:
    user = await make_user(UserRole.TEACHER)
    token = (await login(user.email)).json()["access_token"]

    response = await client.post(
        CHANGE_PASSWORD,
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": TEST_PASSWORD, "new_password": "a-brand-new-password"},
    )

    assert response.status_code == 200
    assert (await login(user.email, "a-brand-new-password")).status_code == 200
    assert (await login(user.email, TEST_PASSWORD)).status_code == 401


async def test_changing_a_password_revokes_every_session(
    make_user, login, client: AsyncClient, session
) -> None:
    """A password change is how someone responds to a suspected compromise."""
    user = await make_user(UserRole.TEACHER)
    token = (await login(user.email)).json()["access_token"]

    await client.post(
        CHANGE_PASSWORD,
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": TEST_PASSWORD, "new_password": "a-brand-new-password"},
    )

    unrevoked = await session.scalar(
        select(func.count()).select_from(RefreshToken).where(RefreshToken.revoked_at.is_(None))
    )
    assert unrevoked == 0


async def test_the_wrong_current_password_is_refused(make_user, login, client: AsyncClient) -> None:
    user = await make_user(UserRole.TEACHER)
    token = (await login(user.email)).json()["access_token"]

    response = await client.post(
        CHANGE_PASSWORD,
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": "wrong", "new_password": "a-brand-new-password"},
    )

    assert response.status_code == 401


async def test_a_too_short_new_password_is_refused(make_user, login, client: AsyncClient) -> None:
    user = await make_user(UserRole.TEACHER)
    token = (await login(user.email)).json()["access_token"]

    response = await client.post(
        CHANGE_PASSWORD,
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": TEST_PASSWORD, "new_password": "short"},
    )

    assert response.status_code == 422


async def test_change_password_requires_authentication(client: AsyncClient) -> None:
    response = await client.post(
        CHANGE_PASSWORD,
        json={"current_password": TEST_PASSWORD, "new_password": "a-brand-new-password"},
    )

    assert response.status_code == 401


async def test_a_new_account_is_flagged_to_change_its_password(make_user, login) -> None:
    user = await make_user(UserRole.PARENT, must_change_password=True)

    body = (await login(user.email)).json()

    # Signing in still works — changing the password requires being signed in.
    assert body["user"]["must_change_password"] is True


async def test_changing_the_password_clears_the_flag(make_user, login, client: AsyncClient) -> None:
    user = await make_user(UserRole.PARENT, must_change_password=True)
    token = (await login(user.email)).json()["access_token"]

    await client.post(
        CHANGE_PASSWORD,
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": TEST_PASSWORD, "new_password": "a-brand-new-password"},
    )

    body = (await login(user.email, "a-brand-new-password")).json()
    assert body["user"]["must_change_password"] is False


# ---------------------------------------------------------------------------
# Bearer token handling
# ---------------------------------------------------------------------------


async def test_me_requires_a_token(client: AsyncClient) -> None:
    response = await client.get(ME)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("header", ["", "Bearer ", "Bearer rubbish", "Basic abc", "rubbish"])
async def test_a_bad_authorization_header_is_refused(header: str, client: AsyncClient) -> None:
    response = await client.get(ME, headers={"Authorization": header})

    assert response.status_code == 401


async def test_a_token_outlives_nothing_once_the_account_is_deactivated(
    make_user, login, client: AsyncClient, session
) -> None:
    """The row is loaded on every request, so a deactivated account stops
    working at once rather than when its access token expires."""
    user = await make_user(UserRole.TEACHER)
    token = (await login(user.email)).json()["access_token"]

    record = await session.get(User, user.id)
    record.is_active = False
    await session.commit()

    assert (await client.get(ME, headers={"Authorization": f"Bearer {token}"})).status_code == 401


# ---------------------------------------------------------------------------
# Audit (§4.9)
# ---------------------------------------------------------------------------


async def test_a_successful_login_is_audited(make_user, login, session) -> None:
    user = await make_user(UserRole.ADMIN)
    await login(user.email)

    entry = await session.scalar(
        select(AuditLog).where(AuditLog.action == AuditAction.LOGIN_SUCCEEDED)
    )

    assert entry is not None
    assert entry.actor_id == user.id
    assert entry.school_id == user.school_id


async def test_a_failed_login_is_audited(make_user, login, session) -> None:
    """§4.9 names failed logins explicitly."""
    user = await make_user(UserRole.TEACHER)
    await login(user.email, "wrong")

    entry = await session.scalar(
        select(AuditLog).where(AuditLog.action == AuditAction.LOGIN_FAILED)
    )

    assert entry is not None
    assert entry.after == {"outcome": "bad_password"}


async def test_a_lockout_is_audited(make_user, login, session) -> None:
    user = await make_user(UserRole.TEACHER)
    for _ in range(settings.max_failed_attempts):
        await login(user.email, "wrong")

    entry = await session.scalar(
        select(AuditLog).where(AuditLog.action == AuditAction.LOGIN_LOCKED)
    )

    assert entry is not None


async def test_token_reuse_is_audited(make_user, login, client: AsyncClient, session) -> None:
    user = await make_user(UserRole.TEACHER)
    await login(user.email)
    stale = client.cookies[REFRESH_COOKIE_NAME]
    await client.post(REFRESH)
    await refresh_with(client, stale)

    entry = await session.scalar(
        select(AuditLog).where(AuditLog.action == AuditAction.TOKEN_REUSE_DETECTED)
    )

    assert entry is not None
    assert entry.after["outcome"] == "family_revoked"


async def test_no_audit_row_ever_carries_a_secret(
    make_user, login, client: AsyncClient, session
) -> None:
    user = await make_user(UserRole.ADMIN)
    token = (await login(user.email)).json()["access_token"]
    await login(user.email, "wrong")
    await client.post(
        CHANGE_PASSWORD,
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": TEST_PASSWORD, "new_password": "a-brand-new-password"},
    )

    rows = (await session.execute(select(AuditLog))).scalars().all()
    blob = " ".join(f"{r.before} {r.after}" for r in rows)

    assert TEST_PASSWORD not in blob
    assert "a-brand-new-password" not in blob
    assert "$argon2" not in blob
    assert token not in blob
