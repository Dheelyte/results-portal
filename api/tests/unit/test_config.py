"""Settings parse from the environment, and never surface the password.

CLAUDE.md forbids exposing tokens or password hashes in logs or error messages.
The database password is in the same class: a traceback or a debug log that
renders Settings must not carry it.
"""

import logging

import pytest
from pydantic import SecretStr, ValidationError

from app.config import Settings

DSN = "postgresql+asyncpg://portal:s3cr3t-pw@db.example:5432/portal"


def test_settings_read_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    monkeypatch.setenv("DATABASE_URL", DSN)
    monkeypatch.setenv("JWT_SECRET", "a" * 48)

    settings = Settings(_env_file=None)

    assert settings.app_env == "production"
    assert settings.log_level == "WARNING"
    assert settings.is_production is True
    assert settings.api_v1_prefix == "/api/v1"


def test_app_env_rejects_an_unknown_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "staging")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_is_production_is_false_outside_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")

    assert Settings(_env_file=None).is_production is False


def test_database_url_is_a_secret() -> None:
    settings = Settings(_env_file=None, database_url=SecretStr(DSN))

    assert isinstance(settings.database_url, SecretStr)
    assert settings.dsn == DSN


@pytest.mark.parametrize("render", [repr, str])
def test_password_never_appears_in_a_rendered_settings_object(render) -> None:
    settings = Settings(_env_file=None, database_url=SecretStr(DSN))

    assert "s3cr3t-pw" not in render(settings)
    assert "s3cr3t-pw" not in render(settings.database_url)
    assert "s3cr3t-pw" not in repr(settings.model_dump())


def test_password_never_appears_in_a_log_line(caplog: pytest.LogCaptureFixture) -> None:
    settings = Settings(_env_file=None, database_url=SecretStr(DSN))

    with caplog.at_level(logging.DEBUG):
        logging.getLogger("test").info("settings loaded", extra={"settings": settings})

    assert "s3cr3t-pw" not in caplog.text


# ---------------------------------------------------------------------------
# Auth configuration (§5.1)
# ---------------------------------------------------------------------------


def test_production_refuses_the_development_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """Shipping with the placeholder secret would let anyone mint an admin
    token. Refuse to start rather than run insecurely."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("JWT_SECRET", raising=False)

    with pytest.raises(ValidationError, match="JWT_SECRET"):
        Settings(_env_file=None)


def test_production_accepts_a_real_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("JWT_SECRET", "b" * 48)

    assert Settings(_env_file=None).is_production is True


def test_development_tolerates_the_placeholder_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """Development must start without ceremony."""
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("JWT_SECRET", raising=False)

    assert Settings(_env_file=None).app_env == "development"


def test_the_jwt_secret_is_never_rendered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "s3cr3t-signing-key-" + "x" * 32)

    settings = Settings(_env_file=None)

    assert "s3cr3t-signing-key" not in repr(settings)
    assert "s3cr3t-signing-key" not in str(settings)
    assert "s3cr3t-signing-key" not in repr(settings.model_dump())


def test_secure_cookies_only_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    """Secure cookies need HTTPS, which development does not have."""
    monkeypatch.setenv("APP_ENV", "development")
    assert Settings(_env_file=None).cookie_secure is False

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("JWT_SECRET", "c" * 48)
    assert Settings(_env_file=None).cookie_secure is True


def test_lockout_defaults_match_the_specification(monkeypatch: pytest.MonkeyPatch) -> None:
    """§5.1: lock for 15 minutes after 5 failed attempts."""
    settings = Settings(_env_file=None)

    assert settings.max_failed_attempts == 5
    assert settings.lockout_minutes == 15
    assert settings.access_token_minutes == 30
    assert settings.refresh_token_days == 30


def test_production_refuses_a_short_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """RFC 7518 §3.2: an HMAC-SHA256 key should be at least 32 bytes."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("JWT_SECRET", "too-short")

    with pytest.raises(ValidationError, match="at least 32 bytes"):
        Settings(_env_file=None)


# ---------------------------------------------------------------------------
# The test database (docs/DECISIONS.md D46)
# ---------------------------------------------------------------------------


def test_the_test_database_is_the_application_one_with_a_suffix() -> None:
    """Derived, not configured, so `pytest` is safe with no setup at all."""
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://portal:portal@postgres:5432/portal",
    )

    assert settings.test_dsn == "postgresql+asyncpg://portal:portal@postgres:5432/portal_test"
    assert settings.dsn == "postgresql+asyncpg://portal:portal@postgres:5432/portal"


def test_an_explicit_test_database_url_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_DATABASE_URL", "postgresql+asyncpg://u:p@elsewhere:5432/scratch_test")

    assert Settings(_env_file=None).test_dsn.endswith("/scratch_test")


def test_the_test_dsn_keeps_the_password() -> None:
    """`render_as_string` masks it by default, which would make the URL
    unusable rather than merely ugly."""
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://portal:s3cret@postgres:5432/portal",
    )

    assert "s3cret" in settings.test_dsn


def test_this_suite_is_not_running_against_the_application_database() -> None:
    """The guard in tests/conftest.py, asserted rather than assumed.

    If the redirection there ever breaks, `clean_database` empties the
    school's data instead of the suite's. That happened twice during
    milestone 5, which is why this test exists.
    """
    from app.db import engine

    assert (engine.url.database or "").endswith("_test"), engine.url.database
