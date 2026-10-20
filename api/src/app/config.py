"""Application configuration, read entirely from the environment.

Every key is listed in the repository's `.env.example` (ARCHITECTURE.md §11).
No default here may carry a real secret.
"""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Refused outright in production.  Present only so development and the test
# suite start without ceremony.
INSECURE_JWT_SECRET = "dev-only-not-a-secret-change-me-before-production"

# RFC 7518 §3.2: an HMAC-SHA256 key should be at least as long as the hash it
# produces.  A shorter one weakens the signature, and PyJWT warns about it.
MIN_JWT_SECRET_BYTES = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["development", "production", "test"] = "development"
    log_level: str = "INFO"

    # Held as a SecretStr so the password never reaches a log line, a traceback
    # or a repr.  Call .get_secret_value() only where the DSN is actually used.
    database_url: SecretStr = SecretStr("postgresql+asyncpg://portal:portal@postgres:5432/portal")

    api_v1_prefix: str = "/api/v1"

    # --- Origins (docs/DECISIONS.md, D13) ---------------------------------
    # The single origin allowed to call this API from a browser.  Never "*":
    # the refresh cookie travels with credentials, and the two are
    # incompatible by specification.
    public_web_origin: str = "http://localhost:8080"

    # --- Auth (§5.1) -------------------------------------------------------
    jwt_secret: SecretStr = SecretStr(INSECURE_JWT_SECRET)
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 30
    refresh_token_days: int = 30

    # §5.1: lock for 15 minutes after 5 failed attempts.
    max_failed_attempts: int = 5
    lockout_minutes: int = 15

    @model_validator(mode="after")
    def _demand_a_real_jwt_secret_in_production(self) -> "Settings":
        if not self.is_production:
            return self

        secret = self.jwt_secret.get_secret_value()
        advice = "Generate one with: python -c 'import secrets; print(secrets.token_urlsafe(64))'"

        if secret == INSECURE_JWT_SECRET:
            raise ValueError(
                f"JWT_SECRET must be set to a real value when APP_ENV=production. {advice}"
            )
        if len(secret.encode()) < MIN_JWT_SECRET_BYTES:
            raise ValueError(
                f"JWT_SECRET must be at least {MIN_JWT_SECRET_BYTES} bytes "
                f"when APP_ENV=production. {advice}"
            )
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def dsn(self) -> str:
        """The database URL as a plain string, for the engine and Alembic."""
        return self.database_url.get_secret_value()

    @property
    def cookie_secure(self) -> bool:
        """Secure cookies need HTTPS, which development does not have."""
        return self.is_production


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
