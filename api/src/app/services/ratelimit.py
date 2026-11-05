"""Per-IP rate limiting for login (ARCHITECTURE.md §5.1, docs/DECISIONS.md D96).

§5.1 asks for two defences on login: "lock for 15 minutes after 5 failed
attempts; **rate-limit login by IP too**". Milestone 2 built the first. This
is the second, and the two guard different things:

- The **lockout** protects one account from being guessed at. It counts
  failures against a user row.
- This protects the **system** from one address working through a list. No
  single account need ever reach five failures, and a login with an unknown
  identifier does not even write an audit row — there is no `school_id` to
  attach it to — so the lockout and the audit log are both blind to it.

A table rather than a counter in memory, because production runs two uvicorn
workers (`api/Dockerfile`): an in-process window would give an attacker twice
the allowance and forget everything on each deploy. One small insert per
login attempt, at a school of ~450 accounts, is not a cost worth optimising.

The limit is on **attempts, not failures**. A successful login consumes
allowance too, which is deliberate: the thing being limited is volume from
one address, and an attacker holding one valid account should not be able to
hide behind it.
"""

import dataclasses
import datetime as dt
import logging

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import LoginAttempt

logger = logging.getLogger(__name__)


class TooManyAttempts(Exception):
    """The address has used its allowance for this window.

    Carries `retry_after` so the router can set the header RFC 9110 §10.2.3
    requires of a 429, and the message says nothing about whether any
    identifier exists.
    """

    def __init__(self, retry_after: int) -> None:
        self.retry_after = retry_after
        super().__init__(
            "Too many sign-in attempts from this connection. Please wait a few "
            "minutes and try again."
        )


@dataclasses.dataclass(frozen=True, slots=True)
class Window:
    """What the limiter knows about one address right now."""

    attempts: int
    limit: int
    oldest_at: dt.datetime | None
    window: dt.timedelta

    @property
    def exceeded(self) -> bool:
        return self.attempts >= self.limit

    def retry_after(self, *, now: dt.datetime) -> int:
        """Seconds until the oldest attempt leaves the window.

        At least one second, because a `Retry-After: 0` invites an immediate
        retry, and at most the window itself.
        """
        if self.oldest_at is None:
            return int(self.window.total_seconds())
        remaining = (self.oldest_at + self.window) - now
        return max(1, min(int(self.window.total_seconds()), int(remaining.total_seconds()) + 1))


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


async def check(db: AsyncSession, ip_address: str | None) -> Window | None:
    """How much of its allowance this address has used.

    Returns None when there is no address to attribute the attempt to — a
    request arriving without one is not thereby exempt from anything else,
    but it cannot be counted either, and refusing every such request would
    break a deployment whose proxy does not forward the header.
    """
    if not ip_address:
        return None

    settings = get_settings()
    window = dt.timedelta(minutes=settings.login_ip_window_minutes)
    since = _now() - window

    row = (
        await db.execute(
            select(func.count(LoginAttempt.id), func.min(LoginAttempt.attempted_at)).where(
                LoginAttempt.ip_address == ip_address,
                LoginAttempt.attempted_at >= since,
            )
        )
    ).one()

    return Window(
        attempts=row[0] or 0,
        limit=settings.login_ip_max_attempts,
        oldest_at=row[1],
        window=window,
    )


async def enforce(db: AsyncSession, ip_address: str | None) -> None:
    """Raise TooManyAttempts if this address has used its allowance.

    Called **before** the password is checked, so a refused request does no
    Argon2id work. That is half the point: Argon2 is deliberately expensive,
    and an unthrottled login endpoint is a CPU amplifier pointed at the one
    host this runs on.
    """
    state = await check(db, ip_address)
    if state is None or not state.exceeded:
        return

    retry_after = state.retry_after(now=_now())
    # No address in the log line: it is the one identifying thing here, and
    # the count is what an operator needs.
    logger.warning(
        "login rate limit reached",
        extra={"attempts": state.attempts, "limit": state.limit, "retry_after": retry_after},
    )
    raise TooManyAttempts(retry_after)


async def record(db: AsyncSession, ip_address: str | None) -> None:
    """Count one attempt from this address, and prune what has aged out.

    Pruning here rather than on a schedule: this table is written only by
    this function, so the cheapest place to keep it small is the moment it
    grows. The prune covers twice the window, so a row is kept a little past
    the point it stops counting — long enough to be legible if anyone looks.

    The caller commits. `record` is called on the failure paths too, where the
    surrounding transaction is already being committed for the audit row.
    """
    if not ip_address:
        return

    settings = get_settings()
    db.add(LoginAttempt(ip_address=ip_address))
    await db.execute(
        delete(LoginAttempt).where(
            LoginAttempt.attempted_at
            < _now() - 2 * dt.timedelta(minutes=settings.login_ip_window_minutes)
        )
    )
