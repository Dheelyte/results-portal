"""Short-lived signed URLs for a generated card (ARCHITECTURE.md §9, §5.3).

§9:

    Stored at reports/{session}/{term}/{admission_number}-{version}.pdf,
    served only through short-lived signed URLs. A guessable public URL would
    let anyone enumerate the school's results.

So the link a parent follows carries its own authority and its own expiry,
and nothing else will open it. The token is an HMAC over the object key and
the expiry, signed with the application's JWT secret:

    {key}.{expires_at}.{signature}

Three properties, each one a test:

- **A guessed key is refused.** Without a signature made with the secret
  there is no way to construct a token, so enumeration gets a 403 rather than
  a file.
- **An expired token is refused**, even though the signature is still good.
  §7 puts the TTL at five minutes: long enough to click a link, short enough
  that a URL copied into a WhatsApp group stops working before it spreads.
- **A tampered token is refused.** The signature covers the key *and* the
  expiry, so neither can be edited without invalidating the other.

`compare_digest` throughout: a signature check that returns early on the
first wrong byte is a timing oracle, and this one is reachable by anyone.
"""

import base64
import hashlib
import hmac
import logging
import time

from app.config import settings

logger = logging.getLogger(__name__)

# §7: "302 → signed URL, 5 min TTL".
DEFAULT_TTL_SECONDS = 300

SEPARATOR = "."


class InvalidLink(Exception):
    """The token does not open anything. Deliberately one error for every
    reason — expired, tampered, forged — because telling them apart tells an
    attacker which half to work on."""


def _encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _signature(key: str, expires_at: int) -> str:
    message = f"{key}{SEPARATOR}{expires_at}".encode()
    digest = hmac.new(
        settings.jwt_secret.get_secret_value().encode(), message, hashlib.sha256
    ).digest()
    return _encode(digest)


def sign(key: str, *, ttl_seconds: int = DEFAULT_TTL_SECONDS, now: int | None = None) -> str:
    """A token that opens exactly this object, for exactly this long."""
    expires_at = int(now if now is not None else time.time()) + ttl_seconds
    return SEPARATOR.join([_encode(key.encode()), str(expires_at), _signature(key, expires_at)])


def verify(token: str, *, now: int | None = None) -> str:
    """The object key this token opens, or `InvalidLink`.

    Never returns a reason. A caller that distinguished "expired" from
    "forged" would be telling whoever is trying which of the two to fix.
    """
    try:
        encoded_key, raw_expiry, signature = token.split(SEPARATOR)
        key = _decode(encoded_key).decode()
        expires_at = int(raw_expiry)
    except (ValueError, UnicodeDecodeError, base64.binascii.Error) as error:
        raise InvalidLink("malformed") from error

    if not hmac.compare_digest(signature, _signature(key, expires_at)):
        raise InvalidLink("bad signature")

    if (now if now is not None else int(time.time())) >= expires_at:
        raise InvalidLink("expired")

    return key
