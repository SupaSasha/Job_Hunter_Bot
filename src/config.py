from typing import Literal

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
