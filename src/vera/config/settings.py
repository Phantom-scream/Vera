"""Typed, environment-driven application settings."""

from enum import StrEnum
from functools import lru_cache

from pydantic import Field
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


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide immutable settings instance."""

    return Settings()
