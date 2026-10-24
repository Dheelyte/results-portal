"""Argon2id password hashing (ARCHITECTURE.md §5.1)."""

import pytest

from app.auth.password import (
    generate_temporary_password,
    hash_password,
    hasher_for,
    needs_rehash,
    verify_password,
)

PASSWORD = "correct-horse-battery"


def test_hash_then_verify() -> None:
    assert verify_password(hash_password(PASSWORD), PASSWORD) is True


def test_wrong_password_does_not_verify() -> None:
    assert verify_password(hash_password(PASSWORD), "not-the-password") is False


def test_hash_is_argon2id() -> None:
    assert hash_password(PASSWORD).startswith("$argon2id$")


def test_hash_never_contains_the_password() -> None:
    assert PASSWORD not in hash_password(PASSWORD)


def test_hashes_are_salted_so_two_hashes_differ() -> None:
    """Equal passwords must not produce equal hashes, or the database reveals
    which accounts share one."""
    first, second = hash_password(PASSWORD), hash_password(PASSWORD)

    assert first != second
    assert verify_password(first, PASSWORD)
    assert verify_password(second, PASSWORD)


@pytest.mark.parametrize(
    "bad_hash",
    ["", "not-a-hash", "$argon2id$v=19$m=65536,t=3,p=4$truncated"],
)
def test_a_corrupt_hash_fails_closed(bad_hash: str) -> None:
    """A malformed stored hash must deny access, never raise — otherwise one
    bad row turns a login into a 500 that distinguishes it from a wrong
    password."""
    assert verify_password(bad_hash, PASSWORD) is False
    assert needs_rehash(bad_hash) is False


def test_a_current_hash_does_not_need_rehashing() -> None:
    assert needs_rehash(hash_password(PASSWORD)) is False


def test_temporary_passwords_are_unambiguous() -> None:
    """These get read down a phone line and copied out of WhatsApp."""
    for _ in range(50):
        assert not set(generate_temporary_password()) & set("O0lI1o")


def test_temporary_passwords_are_unique_and_long_enough() -> None:
    generated = {generate_temporary_password() for _ in range(200)}

    assert len(generated) == 200
    assert all(len(p) == 12 for p in generated)


def test_a_dangerously_short_temporary_password_is_refused() -> None:
    with pytest.raises(ValueError):
        generate_temporary_password(length=4)


# ---------------------------------------------------------------------------
# The test-only cost profile (docs/DECISIONS.md D61)
# ---------------------------------------------------------------------------


def test_only_the_test_environment_gets_the_cheap_profile() -> None:
    """The guard that keeps the weakening where it belongs.

    The suite runs under `APP_ENV=test` with deliberately feeble Argon2
    parameters, because several hundred logins at the production cost of
    725 ms each is four minutes of hashing and nothing else. If that profile
    ever reached development — let alone production — every stored password
    would be cheap to attack, and nothing else in the system would notice.
    """
    for app_env in ("development", "production", "", "testing", "TEST"):
        hasher = hasher_for(app_env)

        assert hasher.time_cost >= 3, app_env
        # RFC 9106's low-memory profile: 64 MiB, in KiB.
        assert hasher.memory_cost >= 65536, app_env
        assert hasher.parallelism >= 4, app_env


def test_the_test_profile_is_the_one_in_use_here() -> None:
    """Otherwise this file's own speed would be a mystery."""
    hasher = hasher_for("test")

    assert hasher.memory_cost < 65536
    assert hasher.time_cost < 3


def test_a_hash_records_the_parameters_it_was_made_with() -> None:
    """Which is why the switch is safe to make at all.

    An Argon2 hash embeds its own cost parameters, so a password hashed under
    one profile still verifies under another. `needs_rehash` then migrates it
    on the owner's next login.
    """
    cheap = hasher_for("test")
    strong = hasher_for("production")

    stored = cheap.hash(PASSWORD)

    assert strong.verify(stored, PASSWORD) is True
    assert strong.check_needs_rehash(stored) is True
