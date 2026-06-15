"""Settings — env-driven, lru-cached."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_ENV: str = "dev"

    # Database
    DATABASE_URL: str = "postgresql+psycopg://app:app@localhost:5432/app"
    TEST_DATABASE_URL: str = "postgresql+psycopg://app:app@localhost:5432/app_test"

    # OpenAI
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"

    # Upload safety caps
    MAX_UPLOAD_BYTES: int = 5_242_880  # 5 MB
    MAX_UPLOAD_ROWS: int = 10_000


@lru_cache
def get_settings() -> Settings:
    return Settings()
