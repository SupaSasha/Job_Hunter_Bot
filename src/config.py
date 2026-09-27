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

    @field_validator("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", mode="before")
    @classmethod
    def empty_telegram_setting(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
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
