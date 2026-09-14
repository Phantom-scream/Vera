"""Typed, environment-driven application settings."""

from enum import StrEnum
from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    """Supported application environments."""

    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """Vera runtime settings loaded from ``VERA_`` environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="VERA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Vera"
    environment: Environment = Environment.DEVELOPMENT
    log_level: str = "INFO"
    database_url: str = "postgresql+asyncpg://vera:vera@localhost:5432/vera"
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)
    max_report_size_bytes: int = Field(default=10 * 1024 * 1024, ge=1)
    gitlab_token: SecretStr | None = None
    gitlab_api_url: str = "https://gitlab.com/api/v4"
    github_token: SecretStr | None = None
    github_api_url: str = "https://api.github.com"
    ci_provider_override: str | None = None
    provider_api_timeout: float = Field(default=5.0, gt=0, le=60)

    @field_validator("gitlab_api_url", "github_api_url")
    @classmethod
    def require_secure_provider_url(cls, value: str) -> str:
        normalized = value.rstrip("/")
        parsed = urlsplit(normalized)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("provider API URLs must use HTTPS")
        return normalized


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide immutable settings instance."""

    return Settings()
