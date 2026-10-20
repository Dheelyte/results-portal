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
