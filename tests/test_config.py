import pytest
from pydantic import ValidationError


@pytest.fixture
def settings_class(monkeypatch):
    for name, value in {
        "DB_HOST": "localhost",
        "DB_USER": "test",
        "DB_PASS": "test",
        "DB_NAME": "test",
    }.items():
        monkeypatch.setenv(name, value)
    for name in (
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "MIN_NOTIFICATION_SCORE",
        "MAX_NOTIFICATIONS_PER_RUN",
    ):
        monkeypatch.delenv(name, raising=False)
    from src.config import Settings

    return Settings


def test_empty_example_credentials_are_optional(settings_class) -> None:
    settings = settings_class(_env_file=".env.example")
    assert settings.TELEGRAM_BOT_TOKEN is None
    assert settings.TELEGRAM_CHAT_ID is None
    assert settings.MIN_NOTIFICATION_SCORE == 70
    assert settings.MAX_NOTIFICATIONS_PER_RUN == 5
    assert settings.HIMALAYAS_API_KEY is None
    assert settings.HIMALAYAS_MAX_PAGES == 3


def test_token_is_not_in_repr_and_big_chat_id_is_supported(settings_class) -> None:
    settings = settings_class(
        _env_file=None,
        TELEGRAM_BOT_TOKEN="  secret-token  ",
        HIMALAYAS_API_KEY="private-api-key",
        TELEGRAM_CHAT_ID="1234567890123",
    )
    assert settings.TELEGRAM_BOT_TOKEN == "secret-token"
    assert "secret-token" not in repr(settings)
    assert "private-api-key" not in repr(settings)
    assert settings.TELEGRAM_CHAT_ID == 1234567890123


@pytest.mark.parametrize(
    "overrides",
    [
        {"MIN_NOTIFICATION_SCORE": -1},
        {"MIN_NOTIFICATION_SCORE": 101},
        {"MAX_NOTIFICATIONS_PER_RUN": -1},
    ],
)
def test_invalid_score_or_limit(settings_class, overrides) -> None:
    with pytest.raises(ValidationError):
        settings_class(_env_file=None, **overrides)


@pytest.mark.parametrize(
    "overrides",
    [
        {"REDIS_PORT": 0},
        {"REDIS_DB": -1},
        {"TRIAL_DAYS": 0},
        {"FREE_MIN_SCORE": 101},
        {"FREE_MAX_JOBS_PER_DIGEST": -1},
        {"SCHEDULER_TIMEZONE": "GMT-3"},
        {"FREE_DIGEST_TIME": "09:00+03:00"},
    ],
)
def test_invalid_scheduler_settings(settings_class, overrides):
    with pytest.raises(ValidationError):
        settings_class(_env_file=None, **overrides)


def test_scheduler_settings_defaults_and_redis_url(settings_class):
    from datetime import time

    config = settings_class(_env_file=None)
    assert config.REDIS_URL == "redis://localhost:6379/0"
    assert config.FREE_DIGEST_TIME == time(9)
    assert config.SCHEDULER_TIMEZONE == "America/Montevideo"
    assert config.TRIAL_DAYS == 7
