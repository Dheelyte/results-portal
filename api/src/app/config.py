"""Application configuration, read entirely from the environment.

Every key is listed in the repository's `.env.example` (ARCHITECTURE.md §11).
No default here may carry a real secret.
"""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def dsn(self) -> str:
        """The database URL as a plain string, for the engine and Alembic."""
        return self.database_url.get_secret_value()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
