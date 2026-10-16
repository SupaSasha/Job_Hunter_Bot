import re
from datetime import time
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    MODE: Literal["LOCAL", "DEV", "TEST", "PROD"] = "LOCAL"

    DB_HOST: str
    DB_PORT: int = 5432
    DB_USER: str
    DB_PASS: str
    DB_NAME: str

    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = Field(default=6379, ge=1, le=65535)
    REDIS_DB: int = Field(default=0, ge=0)
    SCHEDULER_TIMEZONE: str = "America/Montevideo"
    DIGEST_JOB_MAX_AGE_DAYS: int = Field(default=7, ge=1)
    DIGEST_CANDIDATE_LIMIT: int = Field(default=1000, ge=1)
    DIGEST_PENDING_TIMEOUT_MINUTES: int = Field(default=30, ge=11)
    HIMALAYAS_MAX_PAGES: int = Field(default=3, ge=1, le=5)
    HIMALAYAS_API_KEY: str | None = Field(default=None, repr=False)
    JOBICY_MAX_PAGES: int = Field(default=2, ge=1, le=5)
    THE_MUSE_MAX_PAGES: int = Field(default=3, ge=1, le=5)
    THE_MUSE_API_KEY: str | None = Field(default=None, repr=False)
    JOOBLE_API_KEY: str | None = Field(default=None, repr=False)
    JOOBLE_API_DOMAIN: str | None = None
    JOOBLE_SEARCH_LOCATION: str | None = None
    JOOBLE_MAX_PAGES_PER_QUERY: int = Field(default=1, ge=1, le=3)
    JOOBLE_MAX_JOBS_PER_RUN: int = Field(default=40, ge=1, le=200)
    TRIAL_DAYS: int = Field(default=7, ge=1)
    FREE_DIGEST_TIME: time = time(9)
    FREE_MIN_SCORE: int = Field(default=70, ge=0, le=100)
    FREE_MAX_JOBS_PER_DIGEST: int = Field(default=10, ge=0)

    @field_validator("SCHEDULER_TIMEZONE")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Use an IANA timezone") from exc
        return value

    @field_validator("FREE_DIGEST_TIME")
    @classmethod
    def local_digest_time(cls, value: time) -> time:
        if value.tzinfo is not None:
            raise ValueError("Digest time must be a local wall clock time")
        return value

    @property
    def REDIS_URL(self) -> str:
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    TELEGRAM_BOT_TOKEN: str | None = Field(default=None, repr=False)
    TELEGRAM_CHAT_ID: int | None = None
    MIN_NOTIFICATION_SCORE: int = Field(default=70, ge=0, le=100)
    MAX_NOTIFICATIONS_PER_RUN: int = Field(default=5, ge=0)

    @field_validator(
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "HIMALAYAS_API_KEY",
        "THE_MUSE_API_KEY",
        "JOOBLE_API_KEY",
        "JOOBLE_API_DOMAIN",
        "JOOBLE_SEARCH_LOCATION",
        mode="before",
    )
    @classmethod
    def empty_telegram_setting(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("JOOBLE_API_DOMAIN")
    @classmethod
    def valid_jooble_domain(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.lower()
        if not re.fullmatch(r"(?:[a-z]{2}\.)?jooble\.org", value):
            raise ValueError(
                "Use the Jooble domain where the key was issued, without a URL path"
            )
        return value

    @property
    def database_url(self) -> URL:
        return URL.create(
            "postgresql+asyncpg",
            username=self.DB_USER,
            password=self.DB_PASS,
            host=self.DB_HOST,
            port=self.DB_PORT,
            database=self.DB_NAME,
        )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
