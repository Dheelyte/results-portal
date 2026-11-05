"""The arithmetic of §5.1's per-IP login limit (services/ratelimit.py).

The window itself is exercised against a real database in
`tests/integration/test_login_rate_limit.py`. What is unit-tested here is the
part that is pure and easy to get subtly wrong: when a window counts as
exceeded, and what `Retry-After` should say.
"""

import datetime as dt

from app.services.ratelimit import TooManyAttempts, Window

WINDOW = dt.timedelta(minutes=15)
NOW = dt.datetime(2026, 11, 5, 12, 0, tzinfo=dt.UTC)


def window(attempts: int, *, oldest_at: dt.datetime | None = None, limit: int = 20) -> Window:
    return Window(attempts=attempts, limit=limit, oldest_at=oldest_at, window=WINDOW)


def test_below_the_limit_is_not_exceeded() -> None:
    assert not window(19).exceeded


def test_the_limit_itself_is_exceeded() -> None:
    """Twenty attempts means twenty, so the twenty-first is refused.

    `>=`, not `>`: the count is taken *after* this attempt was recorded on
    the previous request, so reaching the limit means the allowance is spent.
    """
    assert window(20).exceeded
    assert window(21).exceeded


def test_retry_after_is_when_the_oldest_attempt_leaves_the_window() -> None:
    # The oldest attempt was 14 minutes ago, so a slot frees up in one.
    oldest = NOW - dt.timedelta(minutes=14)

    assert window(20, oldest_at=oldest).retry_after(now=NOW) == 61


def test_retry_after_is_never_zero() -> None:
    """A `Retry-After: 0` invites the retry it is meant to delay."""
    oldest = NOW - WINDOW  # already leaving, to the second

    assert window(20, oldest_at=oldest).retry_after(now=NOW) == 1


def test_retry_after_is_never_longer_than_the_window() -> None:
    """A clock skew or a future row must not promise a half-hour wait."""
    oldest = NOW + dt.timedelta(minutes=30)

    assert window(20, oldest_at=oldest).retry_after(now=NOW) == int(WINDOW.total_seconds())


def test_retry_after_without_an_oldest_attempt_is_the_whole_window() -> None:
    assert window(20).retry_after(now=NOW) == int(WINDOW.total_seconds())


def test_the_exception_carries_the_delay_and_names_no_identifier() -> None:
    exc = TooManyAttempts(61)

    assert exc.retry_after == 61
    message = str(exc).lower()
    # §5.1's 401 is careful not to be an enumeration oracle; the 429 must not
    # undo that by mentioning the account it was aimed at.
    assert "connection" in message
    for leak in ("account", "user", "email", "phone", "password", "exist"):
        assert leak not in message
