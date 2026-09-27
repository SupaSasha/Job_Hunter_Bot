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


def test_token_is_not_in_repr_and_big_chat_id_is_supported(settings_class) -> None:
    settings = settings_class(
        _env_file=None,
        TELEGRAM_BOT_TOKEN="  secret-token  ",
        TELEGRAM_CHAT_ID="1234567890123",
    )
    assert settings.TELEGRAM_BOT_TOKEN == "secret-token"
    assert "secret-token" not in repr(settings)
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
