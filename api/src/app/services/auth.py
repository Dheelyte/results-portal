"""Authentication rules (ARCHITECTURE.md §5.1).

Every rule in this module, not in a router and not in a component
(CLAUDE.md rule 2). Routers translate the results below into HTTP.
"""

import datetime as dt
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.password import hash_password, needs_rehash, verify_password
from app.auth.tokens import (
    create_access_token,
    generate_refresh_token,
    hash_refresh_token,
    refresh_token_expiry,
)
from app.config import settings
from app.models import AuditAction, RefreshToken, User
from app.services import audit

logger = logging.getLogger(__name__)


class AuthError(Exception):
    """Authentication failed. The message is safe to return to a client."""


class InvalidCredentials(AuthError):
    def __init__(self) -> None:
        # One message for "no such user", "wrong password" and "inactive".
        # Distinguishing them turns the login form into an account-enumeration
        # oracle, which matters here: a parent's phone number is guessable.
        super().__init__("Incorrect username or password.")


class AccountLocked(AuthError):
    def __init__(self, until: dt.datetime) -> None:
        self.until = until
        super().__init__(
            "This account is temporarily locked after too many failed attempts. "
            "Please try again later or contact the school."
        )


class PasswordChangeRequired(AuthError):
    def __init__(self) -> None:
        super().__init__("You must change your password before continuing.")


@dataclass(frozen=True)
class IssuedTokens:
    """What a successful login or refresh produces."""

    access_token: str
    refresh_token: str
    refresh_expires_at: dt.datetime
    user: User


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


async def _find_user_by_identifier(session: AsyncSession, identifier: str) -> User | None:
    """Look a user up by email or phone.

    §5.1 and A7: parents log in with either, against the same password, because
    many parents' email addresses are inactive. `users.email` is citext, so the
    email comparison is already case-insensitive.
    """
    candidate = identifier.strip()
    if not candidate:
        return None

    result = await session.execute(
        select(User).where(or_(User.email == candidate, User.phone == candidate))
    )
    return result.scalars().first()


async def _issue_tokens(
    session: AsyncSession,
    user: User,
    *,
    family_id: uuid.UUID | None = None,
    now: dt.datetime | None = None,
) -> IssuedTokens:
    """Mint an access/refresh pair and persist the refresh token's hash."""
    moment = now or _now()

    refresh_token = generate_refresh_token()
    expires_at = refresh_token_expiry(moment)

    row = RefreshToken(
        school_id=user.school_id,
        user_id=user.id,
        token_hash=hash_refresh_token(refresh_token),
        family_id=family_id or uuid.uuid4(),
        expires_at=expires_at,
    )
    session.add(row)
    await session.flush()

    access_token = create_access_token(
        user_id=user.id,
        school_id=user.school_id,
        role=user.role.value,
        must_change_password=user.must_change_password,
        now=moment,
    )

    return IssuedTokens(
        access_token=access_token,
        refresh_token=refresh_token,
        refresh_expires_at=expires_at,
        user=user,
    )


async def authenticate(
    session: AsyncSession,
    *,
    identifier: str,
    password: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> IssuedTokens:
    """Log a user in by email or phone.

    Raises InvalidCredentials or AccountLocked. A user with
    `must_change_password` set is still issued tokens — the gate is enforced on
    other endpoints, because changing the password requires being logged in.
    """
    now = _now()
    user = await _find_user_by_identifier(session, identifier)

    if user is None:
        # No audit row: there is no school_id to attach it to, and audit_log
        # requires one. The structured log carries it instead, without the
        # identifier, which would be a parent's phone number.
        logger.warning("login failed: unknown identifier", extra={"outcome": "unknown_user"})
        raise InvalidCredentials

    if user.locked_until is not None and user.locked_until > now:
        await audit.record(
            session,
            school_id=user.school_id,
            actor_id=user.id,
            action=AuditAction.LOGIN_FAILED,
            entity_type="user",
            entity_id=user.id,
            after={"outcome": "locked"},
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await session.commit()
        raise AccountLocked(user.locked_until)

    if not user.is_active or not verify_password(user.password_hash, password):
        await _register_failed_attempt(
            session, user, now=now, ip_address=ip_address, user_agent=user_agent
        )
        raise InvalidCredentials

    # Success: clear the counter, release any expired lock, stamp the login.
    user.failed_attempts = 0
    user.locked_until = None
    user.last_login_at = now

    # Cost parameters may have been raised since this hash was made; migrate
    # it now, while the plaintext is in hand.
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)

    tokens = await _issue_tokens(session, user, now=now)

    await audit.record(
        session,
        school_id=user.school_id,
        actor_id=user.id,
        action=AuditAction.LOGIN_SUCCEEDED,
        entity_type="user",
        entity_id=user.id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await session.commit()
    return tokens


async def _register_failed_attempt(
    session: AsyncSession,
    user: User,
    *,
    now: dt.datetime,
    ip_address: str | None,
    user_agent: str | None,
) -> None:
    """Count a failure and lock the account at the threshold (§5.1)."""
    user.failed_attempts += 1
    locked = user.failed_attempts >= settings.max_failed_attempts

    if locked:
        user.locked_until = now + dt.timedelta(minutes=settings.lockout_minutes)
        # Reset the counter with the lock, so that after it expires the user
        # gets a fresh allowance rather than being re-locked by one mistake.
        user.failed_attempts = 0

    await audit.record(
        session,
        school_id=user.school_id,
        actor_id=user.id,
        action=AuditAction.LOGIN_LOCKED if locked else AuditAction.LOGIN_FAILED,
        entity_type="user",
        entity_id=user.id,
        after={"outcome": "locked" if locked else "bad_password"},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await session.commit()


async def refresh(
    session: AsyncSession,
    *,
    refresh_token: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> IssuedTokens:
    """Exchange a refresh token for a new pair, rotating it (§5.1).

    Reuse of an already-consumed token means the chain has leaked. The whole
    family is revoked, which logs out every session descended from that login
    — including the attacker's and the legitimate user's. That is the intended
    outcome: the user re-authenticates, and the stolen token is worthless.
    """
    now = _now()
    token_hash = hash_refresh_token(refresh_token)

    result = await session.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    row = result.scalars().first()

    if row is None:
        logger.warning("refresh failed: unknown token", extra={"outcome": "unknown_token"})
        raise InvalidCredentials

    if row.revoked_at is not None:
        await _revoke_family(session, row, now=now)
        await audit.record(
            session,
            school_id=row.school_id,
            actor_id=row.user_id,
            action=AuditAction.TOKEN_REUSE_DETECTED,
            entity_type="refresh_token",
            entity_id=row.id,
            after={"family_id": str(row.family_id), "outcome": "family_revoked"},
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await session.commit()
        raise InvalidCredentials

    if row.expires_at <= now:
        raise InvalidCredentials

    user = await session.get(User, row.user_id)
    if user is None or not user.is_active:
        raise InvalidCredentials

    # Rotate: the presented token is consumed and a successor issued in the
    # same family.
    tokens = await _issue_tokens(session, user, family_id=row.family_id, now=now)

    successor = await session.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == hash_refresh_token(tokens.refresh_token)
        )
    )
    row.revoked_at = now
    row.replaced_by = successor.scalars().one().id

    await audit.record(
        session,
        school_id=user.school_id,
        actor_id=user.id,
        action=AuditAction.TOKEN_REFRESHED,
        entity_type="refresh_token",
        entity_id=row.id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await session.commit()
    return tokens


async def _revoke_family(session: AsyncSession, row: RefreshToken, *, now: dt.datetime) -> None:
    """Revoke every unrevoked token descended from the same login."""
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == row.family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )


async def logout(
    session: AsyncSession,
    *,
    refresh_token: str | None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    """Revoke the presented token's whole family.

    The family, not just the one token: logging out should end the session, and
    a session is the chain of rotations descended from one login.

    Never raises. A logout that fails because the token was already gone has
    achieved what the caller wanted.
    """
    if not refresh_token:
        return

    now = _now()
    result = await session.execute(
        select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(refresh_token))
    )
    row = result.scalars().first()
    if row is None:
        return

    await _revoke_family(session, row, now=now)
    await audit.record(
        session,
        school_id=row.school_id,
        actor_id=row.user_id,
        action=AuditAction.LOGOUT,
        entity_type="refresh_token",
        entity_id=row.id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await session.commit()


async def change_password(
    session: AsyncSession,
    *,
    user: User,
    current_password: str,
    new_password: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    """Change a user's own password (§7 /auth/change-password).

    Revokes every refresh token the user holds. A password change is how
    someone responds to a suspected compromise, so leaving existing sessions
    alive would defeat the point.
    """
    if not verify_password(user.password_hash, current_password):
        raise InvalidCredentials

    validate_password_strength(new_password)

    now = _now()
    user.password_hash = hash_password(new_password)
    user.must_change_password = False

    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )

    await audit.record(
        session,
        school_id=user.school_id,
        actor_id=user.id,
        action=AuditAction.PASSWORD_CHANGED,
        entity_type="user",
        entity_id=user.id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await session.commit()


# §5.1 sets no password policy. A length floor is the one rule with real
# evidence behind it; composition rules mostly produce "Password1!".
MIN_PASSWORD_LENGTH = 10


def validate_password_strength(password: str) -> None:
    """Reject a password that is too short. Raises AuthError."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AuthError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
