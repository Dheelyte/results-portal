"""The audit log must not become a place secrets are kept.

CLAUDE.md forbids scores, comments, tokens and password hashes in logs.
`audit_log.before` / `after` are as much a log as stdout is, and
services/audit.py is the one writer, so the guard belongs there.
"""

import pytest

from app.services.audit import REDACTED, scrub


def test_none_stays_none() -> None:
    assert scrub(None) is None


def test_ordinary_fields_are_untouched() -> None:
    payload = {"role": "teacher", "full_name": "A Person", "is_active": True}

    assert scrub(payload) == payload


@pytest.mark.parametrize(
    "key",
    ["password", "password_hash", "new_password", "token", "refresh_token", "jwt_secret"],
)
def test_forbidden_keys_are_redacted(key: str) -> None:
    scrubbed = scrub({key: "the-actual-secret", "role": "admin"})

    assert scrubbed[key] == REDACTED
    assert scrubbed["role"] == "admin"


def test_redaction_is_case_insensitive() -> None:
    assert scrub({"Password": "s3cret"})["Password"] == REDACTED
    assert scrub({"TOKEN": "abc"})["TOKEN"] == REDACTED


def test_the_key_is_kept_so_the_shape_of_the_change_stays_legible() -> None:
    """That a password changed is the audit-worthy fact; the value never is."""
    assert "password_hash" in scrub({"password_hash": "$argon2id$..."})


def test_nested_dictionaries_are_scrubbed() -> None:
    scrubbed = scrub({"user": {"email": "a@b.test", "password": "s3cret"}})

    assert scrubbed["user"]["password"] == REDACTED
    assert scrubbed["user"]["email"] == "a@b.test"


def test_dictionaries_inside_lists_are_scrubbed() -> None:
    scrubbed = scrub({"sessions": [{"token": "abc"}, {"token": "def"}]})

    assert [s["token"] for s in scrubbed["sessions"]] == [REDACTED, REDACTED]


def test_a_real_argon2_hash_does_not_survive() -> None:
    from app.auth.password import hash_password

    digest = hash_password("correct-horse-battery")

    assert digest not in str(scrub({"password_hash": digest}))
