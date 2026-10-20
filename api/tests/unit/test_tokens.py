"""Access and refresh tokens (ARCHITECTURE.md §5.1)."""

import datetime as dt
import uuid

import jwt
import pytest

from app.auth.tokens import (
    TokenError,
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_refresh_token,
    refresh_token_expiry,
)
from app.config import settings

USER_ID = uuid.uuid4()
SCHOOL_ID = uuid.uuid4()


def make_token(**overrides) -> str:
    kwargs = {
        "user_id": USER_ID,
        "school_id": SCHOOL_ID,
        "role": "teacher",
        "must_change_password": False,
    }
    kwargs.update(overrides)
    return create_access_token(**kwargs)


def test_round_trip_preserves_the_claims() -> None:
    claims = decode_access_token(make_token(role="head_teacher", must_change_password=True))

    assert claims.user_id == USER_ID
    assert claims.school_id == SCHOOL_ID
    assert claims.role == "head_teacher"
    assert claims.must_change_password is True


def test_the_token_expires_after_the_configured_lifetime() -> None:
    claims = decode_access_token(make_token())
    lifetime = claims.expires_at - dt.datetime.now(dt.UTC)

    assert lifetime <= dt.timedelta(minutes=settings.access_token_minutes)
    assert lifetime > dt.timedelta(minutes=settings.access_token_minutes - 1)


def test_an_expired_token_is_refused() -> None:
    long_ago = dt.datetime.now(dt.UTC) - dt.timedelta(days=1)

    with pytest.raises(TokenError):
        decode_access_token(make_token(now=long_ago))


def test_a_token_signed_with_another_key_is_refused() -> None:
    forged = jwt.encode(
        {
            "sub": str(USER_ID),
            "sid": str(SCHOOL_ID),
            "role": "admin",
            "typ": "access",
            "iat": int(dt.datetime.now(dt.UTC).timestamp()),
            "exp": int((dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)).timestamp()),
        },
        # 32+ bytes, so the forgery is refused for its signature rather
        # than dismissed for a short key.
        "a-different-secret-" + "x" * 32,
        algorithm="HS256",
    )

    with pytest.raises(TokenError):
        decode_access_token(forged)


def test_the_none_algorithm_is_refused() -> None:
    """The classic JWT forgery: an unsigned token claiming alg=none."""
    unsigned = jwt.encode({"sub": str(USER_ID), "role": "admin"}, key="", algorithm="none")

    with pytest.raises(TokenError):
        decode_access_token(unsigned)


def test_a_token_of_the_wrong_type_is_refused() -> None:
    """Guards against a future token kind being replayed as an access token."""
    other = jwt.encode(
        {
            "sub": str(USER_ID),
            "sid": str(SCHOOL_ID),
            "role": "admin",
            "typ": "password_reset",
            "iat": int(dt.datetime.now(dt.UTC).timestamp()),
            "exp": int((dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)).timestamp()),
        },
        settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )

    with pytest.raises(TokenError):
        decode_access_token(other)


@pytest.mark.parametrize("rubbish", ["", "not.a.token", "a.b.c", "Bearer xyz"])
def test_rubbish_is_refused(rubbish: str) -> None:
    with pytest.raises(TokenError):
        decode_access_token(rubbish)


def test_every_failure_gives_the_same_message() -> None:
    """A caller must not learn *why* a token failed."""
    messages = set()
    for bad in ["", "a.b.c", make_token(now=dt.datetime.now(dt.UTC) - dt.timedelta(days=1))]:
        try:
            decode_access_token(bad)
        except TokenError as exc:
            messages.add(str(exc))

    assert len(messages) == 1


def test_refresh_tokens_are_long_and_unique() -> None:
    tokens = {generate_refresh_token() for _ in range(1000)}

    assert len(tokens) == 1000
    # 32 bytes base64url-encoded.
    assert all(len(t) >= 43 for t in tokens)


def test_the_refresh_hash_is_deterministic_and_hides_the_token() -> None:
    token = generate_refresh_token()
    digest = hash_refresh_token(token)

    assert digest == hash_refresh_token(token)
    assert token not in digest
    assert len(digest) == 64  # sha256 hex


def test_distinct_refresh_tokens_hash_differently() -> None:
    assert hash_refresh_token(generate_refresh_token()) != hash_refresh_token(
        generate_refresh_token()
    )


def test_refresh_expiry_matches_the_configured_lifetime() -> None:
    now = dt.datetime.now(dt.UTC)

    assert refresh_token_expiry(now) == now + dt.timedelta(days=settings.refresh_token_days)
