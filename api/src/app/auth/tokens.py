"""Access and refresh tokens (ARCHITECTURE.md §5.1).

Two different things, deliberately:

- The **access token** is a JWT, 30 minutes, held in memory by the client. It
  is self-describing, so a request can be authorised without a database read.
- The **refresh token** is an opaque random string, 30 days, in an httpOnly
  cookie. It carries no claims and means nothing without the row it hashes to,
  which is what makes revocation immediate — a JWT cannot be withdrawn before
  it expires, and a 30-day un-revokable credential is not acceptable.

Pure functions; the rules that use them live in services/auth.py.
"""

import datetime as dt
import hashlib
import secrets
import uuid
from dataclasses import dataclass

import jwt

from app.config import settings

# Opaque, so length is the only thing protecting it. 32 bytes is 256 bits.
_REFRESH_TOKEN_BYTES = 32


class TokenError(Exception):
    """An access token was absent, malformed, expired or not ours."""


@dataclass(frozen=True)
class AccessTokenClaims:
    """What a verified access token asserts."""

    user_id: uuid.UUID
    school_id: uuid.UUID
    role: str
    must_change_password: bool
    expires_at: dt.datetime


def create_access_token(
    *,
    user_id: uuid.UUID,
    school_id: uuid.UUID,
    role: str,
    must_change_password: bool,
    now: dt.datetime | None = None,
) -> str:
    """Mint a signed access token.

    `must_change_password` rides in the token so the gate can be enforced
    without a database read on every request.
    """
    issued_at = now or dt.datetime.now(dt.UTC)
    expires_at = issued_at + dt.timedelta(minutes=settings.access_token_minutes)

    payload = {
        "sub": str(user_id),
        "sid": str(school_id),
        "role": role,
        "mcp": must_change_password,
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
        "typ": "access",
    }
    return jwt.encode(payload, settings.jwt_secret.get_secret_value(), settings.jwt_algorithm)


def decode_access_token(token: str) -> AccessTokenClaims:
    """Verify a token and return its claims, or raise TokenError.

    Every failure mode collapses to one exception type with one message. A
    caller must not be able to tell "expired" from "bad signature" from
    "refresh token presented as an access token".
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise TokenError("invalid or expired access token") from exc

    if payload.get("typ") != "access":
        raise TokenError("invalid or expired access token")

    try:
        return AccessTokenClaims(
            user_id=uuid.UUID(payload["sub"]),
            school_id=uuid.UUID(payload["sid"]),
            role=payload["role"],
            must_change_password=bool(payload.get("mcp", False)),
            expires_at=dt.datetime.fromtimestamp(payload["exp"], tz=dt.UTC),
        )
    except (KeyError, ValueError) as exc:
        raise TokenError("invalid or expired access token") from exc


def generate_refresh_token() -> str:
    """A fresh opaque refresh token. Returned to the caller exactly once."""
    return secrets.token_urlsafe(_REFRESH_TOKEN_BYTES)


def hash_refresh_token(token: str) -> str:
    """The stored form of a refresh token.

    Plain SHA-256, not Argon2: the token is 256 bits of system-generated
    randomness, so there is no low-entropy guess space for a slow hash to
    defend. A slow hash here would only tax every refresh. Passwords are the
    opposite case, which is why they use Argon2id.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def refresh_token_expiry(now: dt.datetime | None = None) -> dt.datetime:
    issued_at = now or dt.datetime.now(dt.UTC)
    return issued_at + dt.timedelta(days=settings.refresh_token_days)
