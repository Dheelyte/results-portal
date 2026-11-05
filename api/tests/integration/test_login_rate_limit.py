"""§5.1's per-IP login limit, against a real database.

"Lock for 15 minutes after 5 failed attempts; **rate-limit login by IP
too**." Milestone 2 built the lockout. This is the other half, and the tests
below are mostly about the attack the lockout *cannot* see: one address
working through a list of identifiers, where no single account ever reaches
five failures.
"""

import datetime as dt

import pytest
from sqlalchemy import func, select

from app.config import settings
from app.models import LoginAttempt, User

LOGIN = "/api/v1/auth/login"


async def attempts_recorded(session) -> int:
    return await session.scalar(select(func.count(LoginAttempt.id)))


async def spend_the_allowance(login, make_user) -> None:
    """Use up the address's allowance without locking any one account.

    One failure each against a fresh identifier, so `failed_attempts` never
    reaches §5.1's five anywhere. Without this the two defences overlap and a
    429 test could pass because of a 423 it never saw.
    """
    for _ in range(settings.login_ip_max_attempts):
        user = await make_user()
        assert (await login(user.email, "wrong-password")).status_code == 401


# ---------------------------------------------------------------------------
# The limit holds
# ---------------------------------------------------------------------------


async def test_the_allowance_is_spent_and_then_refused(login, make_user) -> None:
    user = await make_user()

    for attempt in range(settings.login_ip_max_attempts):
        response = await login(user.email, "wrong-password")
        assert response.status_code in (401, 423), f"attempt {attempt + 1}"

    refused = await login(user.email, "wrong-password")

    assert refused.status_code == 429


async def test_the_refusal_carries_retry_after(login, make_user) -> None:
    """RFC 9110 §10.2.3: a 429 should say when to come back."""
    user = await make_user()
    for _ in range(settings.login_ip_max_attempts):
        await login(user.email, "wrong-password")

    refused = await login(user.email, "wrong-password")

    assert refused.status_code == 429
    delay = int(refused.headers["retry-after"])
    assert 0 < delay <= settings.login_ip_window_minutes * 60


async def test_a_correct_password_is_refused_once_the_address_is_over(login, make_user) -> None:
    """The limit is on the address, not the identity.

    This is the property that makes it worth having: an attacker who finally
    guesses right still gets nothing. It is also the cost — a parent behind a
    hotspot someone else exhausted waits with them.

    The allowance is spent against *other* identifiers, so the account being
    signed into is not itself locked: what refuses this login must be the
    address limit and nothing else.
    """
    innocent = await make_user()
    await spend_the_allowance(login, make_user)

    assert (await login(innocent.email)).status_code == 429


async def test_the_sprayer_is_caught_though_no_account_is_locked(login, make_user, session) -> None:
    """The attack the §5.1 lockout is blind to.

    Twenty-one identifiers, one failure each. No account reaches five
    failures, so nothing locks; and an *unknown* identifier writes no audit
    row at all, because there is no `school_id` to attach it to. The limit is
    the only thing that sees this.
    """
    users = [await make_user() for _ in range(settings.login_ip_max_attempts)]

    for user in users:
        assert (await login(user.email, "wrong-password")).status_code == 401

    refused = await login("someone-else@sshms.test", "wrong-password")
    assert refused.status_code == 429

    # Nothing locked, which is the point.
    locked = await session.scalars(select(User).where(User.locked_until.is_not(None)))
    assert list(locked) == []


async def test_an_unknown_identifier_still_spends_an_attempt(login, session) -> None:
    """Otherwise the cheapest attack would be the one that costs nothing.

    The unknown-identifier path writes no audit row and returns early, so the
    attempt is recorded and committed before the user is looked up at all.
    """
    for _ in range(settings.login_ip_max_attempts):
        assert (await login("nobody@sshms.test", "x")).status_code == 401

    assert (await login("nobody@sshms.test", "x")).status_code == 429
    assert await attempts_recorded(session) == settings.login_ip_max_attempts


# ---------------------------------------------------------------------------
# The window moves
# ---------------------------------------------------------------------------


async def test_an_attempt_outside_the_window_does_not_count(login, make_user, session) -> None:
    innocent = await make_user()
    await spend_the_allowance(login, make_user)
    assert (await login(innocent.email)).status_code == 429

    # Age every recorded attempt past the window, which is what the clock
    # would do given a quarter of an hour.
    stale = dt.datetime.now(dt.UTC) - dt.timedelta(
        minutes=settings.login_ip_window_minutes, seconds=30
    )
    for attempt in await session.scalars(select(LoginAttempt)):
        attempt.attempted_at = stale
    await session.commit()

    assert (await login(innocent.email)).status_code == 200


async def test_rows_past_twice_the_window_are_pruned(login, make_user, session) -> None:
    """The table is kept small where it grows, not on a schedule."""
    user = await make_user()
    await login(user.email, "wrong")

    ancient = dt.datetime.now(dt.UTC) - dt.timedelta(
        minutes=settings.login_ip_window_minutes * 2, seconds=30
    )
    for attempt in await session.scalars(select(LoginAttempt)):
        attempt.attempted_at = ancient
    await session.commit()

    await login(user.email, "wrong")

    # The ancient row is gone; only the attempt just made remains.
    assert await attempts_recorded(session) == 1


# ---------------------------------------------------------------------------
# What it must not do
# ---------------------------------------------------------------------------


async def test_the_refusal_names_no_account(login, make_user) -> None:
    user = await make_user(email="known@sshms.test")
    for _ in range(settings.login_ip_max_attempts):
        await login(user.email, "wrong-password")

    detail = (await login(user.email, "wrong-password")).json()["detail"].lower()

    assert "known@sshms.test" not in detail
    for leak in ("account", "password", "exist"):
        assert leak not in detail


async def test_no_identifier_is_ever_recorded(login, make_user, session) -> None:
    """The table holds an address and a moment. §5.1: the identifier may be a
    parent's phone number, and this is a log."""
    user = await make_user(phone="08030000111")
    await login(user.phone, "wrong-password")

    columns = {column.name for column in LoginAttempt.__table__.columns}

    assert columns == {"id", "ip_address", "attempted_at"}
    assert await attempts_recorded(session) == 1


@pytest.mark.parametrize("endpoint", ["/api/v1/auth/refresh", "/api/v1/auth/logout"])
async def test_only_login_is_limited(endpoint, client, login, make_user) -> None:
    """§5.1 limits login. Refresh and logout present a token they already
    hold, so limiting them would log a legitimate parent out mid-session."""
    user = await make_user()
    assert (await login(user.email)).status_code == 200

    for _ in range(settings.login_ip_max_attempts + 2):
        response = await client.post(endpoint)
        assert response.status_code != 429
