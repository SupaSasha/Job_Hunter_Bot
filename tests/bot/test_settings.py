from datetime import UTC, datetime, time
from unittest.mock import AsyncMock

import pytest

from src.bot.client import TelegramAPIError, TelegramClient
from src.bot.commands import HELP
from src.bot.settings import ROOT, TIMEZONES, SettingsHandler, format_settings
from src.models.user import UserORM
from src.repositories.users import UserRepository
from src.services.entitlements import EffectiveNotificationSettings
from src.services.notification_settings import (
    NotificationSettingsService,
    NotificationSettingsView,
    PremiumRequired,
    SettingsUnavailable,
)

TRIAL = NotificationSettingsView(
    EffectiveNotificationSettings(
        "America/Montevideo", time(7, 30), 85, 10, True, True
    ),
    "Trial",
    datetime(2026, 10, 5, 15, tzinfo=UTC),
)
FREE = NotificationSettingsView(
    EffectiveNotificationSettings(
        "America/Montevideo", time(10, 15), 65, 10, True, False
    ),
    "Free",
    None,
)


def callback(data):
    return {
        "id": "query-1",
        "data": data,
        "from": {"id": 999, "is_bot": False},
        "message": {"message_id": 42, "chat": {"id": 999, "type": "private"}},
    }


@pytest.fixture
def handler():
    users = AsyncMock(spec=UserRepository)
    users.get_by_telegram_id.return_value = UserORM(
        id=8, telegram_id=999, is_active=True
    )
    service = AsyncMock(spec=NotificationSettingsService)
    service.get.return_value = TRIAL
    return SettingsHandler(
        users, service, AsyncMock(spec=TelegramClient), help_text=HELP
    )


@pytest.mark.parametrize(
    "view", [TRIAL, FREE, NotificationSettingsView(TRIAL.effective, "Premium", None)]
)
async def test_show_effective_settings(handler, view):
    handler.service.get.return_value = view
    await handler.show(8, 999)
    handler.service.get.assert_awaited_once_with(8)
    text = handler.client.send_message.call_args.args[1]
    assert f"Plan:\n{view.plan}" in text
    assert f"{view.effective.digest_time:%H:%M}" in text
    assert f"{view.effective.min_score}%" in text
    assert ("Trial ends:" in text) == (view.plan == "Trial")
    assert ("🔒" in text) == (view.plan == "Free")


@pytest.mark.parametrize(
    "data,text",
    [
        ("settings:timezone", "Choose your timezone."),
        ("settings:time", "Choose your daily digest time."),
        ("settings:score", "Choose your minimum match score."),
        ("settings:back", "⚙️ Settings"),
        ("settings:close", "/help"),
    ],
)
async def test_navigation_edits_and_acknowledges(handler, data, text):
    await handler.handle(callback(data))
    args = handler.client.edit_message_text.call_args.args
    assert args[:2] == (999, 42)
    assert text in args[2]
    handler.client.send_message.assert_not_awaited()
    handler.client.answer_callback_query.assert_awaited_once_with("query-1", None)
    for row in args[3]["inline_keyboard"]:
        for item in row:
            assert len(item["callback_data"].encode()) <= 64


@pytest.mark.parametrize(
    "data,method,value,confirmation",
    [
        (
            "tz:Europe/Madrid",
            "update_timezone",
            "Europe/Madrid",
            "Timezone updated to Europe/Madrid.",
        ),
        ("time:0800", "update_digest_time", time(8), "Digest time updated to 08:00."),
        ("score:80", "update_min_score", 80, "Minimum score updated to 80%."),
    ],
)
async def test_selection_is_scoped_to_sender(
    handler, data, method, value, confirmation
):
    await handler.handle(callback(data))
    handler.users.get_by_telegram_id.assert_awaited_once_with(999)
    getattr(handler.service, method).assert_awaited_once_with(8, value)
    handler.client.answer_callback_query.assert_awaited_once_with(
        "query-1", confirmation
    )
    assert confirmation in handler.client.edit_message_text.call_args.args[2]


async def test_timezone_for_free_user(handler):
    handler.service.get.return_value = FREE
    await handler.handle(callback("tz:UTC"))
    handler.service.update_timezone.assert_awaited_once_with(8, "UTC")


@pytest.mark.parametrize("kind,current", [("time", "10:15"), ("score", "65%")])
async def test_free_menus_show_configured_defaults(handler, kind, current):
    handler.service.get.return_value = FREE
    await handler.handle(callback(f"settings:{kind}"))
    args = handler.client.edit_message_text.call_args.args
    assert "available during the trial or with Premium" in args[2]
    assert current in args[2]
    assert len(args[3]["inline_keyboard"]) == 1
    handler.service.update_digest_time.assert_not_awaited()
    handler.service.update_min_score.assert_not_awaited()


@pytest.mark.parametrize(
    "data,method",
    [
        ("time:0800", "update_digest_time"),
        ("score:80", "update_min_score"),
    ],
)
async def test_stale_premium_button_becomes_locked(handler, data, method):
    handler.service.get.side_effect = [TRIAL, FREE]
    getattr(handler.service, method).side_effect = PremiumRequired
    await handler.handle(callback(data))
    assert (
        "available during the trial"
        in handler.client.edit_message_text.call_args.args[2]
    )
    handler.client.answer_callback_query.assert_awaited_once()


@pytest.mark.parametrize(
    "data",
    [
        "settings:foobar",
        "tz:Invalid",
        "time:0730",
        "time:2500",
        "score:101",
        "score:81",
        "score:080",
        None,
    ],
)
async def test_invalid_callback_acknowledged_without_changes(handler, data):
    await handler.handle(callback(data))
    handler.client.answer_callback_query.assert_awaited_once()
    handler.client.edit_message_text.assert_not_awaited()
    handler.service.update_timezone.assert_not_awaited()
    handler.service.update_digest_time.assert_not_awaited()
    handler.service.update_min_score.assert_not_awaited()


@pytest.mark.parametrize(
    "change",
    ["group", "mismatch", "bot", "missing", "inactive", "bad_id", "no_message"],
)
async def test_unauthorized_callbacks_do_not_read_settings(handler, change):
    payload = callback("settings:back")
    if change == "group":
        payload["message"]["chat"]["type"] = "group"
    elif change == "mismatch":
        payload["message"]["chat"]["id"] = 123
    elif change == "bot":
        payload["from"]["is_bot"] = True
    elif change == "missing":
        handler.users.get_by_telegram_id.return_value = None
    elif change == "inactive":
        handler.users.get_by_telegram_id.return_value.is_active = False
    elif change == "bad_id":
        payload["from"]["id"] = True
    else:
        payload.pop("message")
    await handler.handle(payload)
    handler.service.get.assert_not_awaited()
    handler.client.edit_message_text.assert_not_awaited()
    handler.client.answer_callback_query.assert_awaited_once()


async def test_edit_failure_still_acknowledged_without_replay(handler):
    handler.client.edit_message_text.side_effect = TelegramAPIError("timeout")
    await handler.handle(callback("score:80"))
    handler.service.update_min_score.assert_awaited_once()
    handler.client.answer_callback_query.assert_awaited_once()


async def test_acknowledgment_failure_is_handled(handler):
    handler.client.answer_callback_query.side_effect = TelegramAPIError("timeout")
    await handler.handle(callback("settings:back"))
    handler.client.edit_message_text.assert_awaited_once()


def test_timezone_options_and_root_callback_lengths():
    from zoneinfo import ZoneInfo

    assert {
        "Europe/Berlin",
        "Asia/Tokyo",
        "Africa/Johannesburg",
        "Australia/Sydney",
    } <= set(TIMEZONES)
    for zone in TIMEZONES:
        assert ZoneInfo(zone).key == zone
        assert len(f"tz:{zone}".encode()) <= 64
    for row in ROOT["inline_keyboard"]:
        assert len(row[0]["callback_data"].encode()) <= 64
    assert "2026-10-05" in format_settings(TRIAL)


async def test_missing_settings_with_reply_failure_does_not_escape(handler):
    handler.service.get.side_effect = SettingsUnavailable
    handler.client.send_message.side_effect = TelegramAPIError("timeout")
    await handler.show(8, 999)
    handler.client.send_message.assert_awaited_once_with(
        999, "Notification settings are not available yet."
    )


@pytest.mark.parametrize(
    "data,expected",
    [
        (
            "settings:time",
            [
                "time:0700",
                "time:0800",
                "time:0900",
                "time:1000",
                "time:1200",
                "time:1800",
                "time:2000",
            ],
        ),
        ("settings:score", [f"score:{s}" for s in (50, 60, 70, 75, 80, 85, 90)]),
        (
            "settings:timezone",
            [*[f"tz:{zone}" for zone in TIMEZONES], "settings:custom_timezone"],
        ),
    ],
)
async def test_menus_contain_only_supported_presets(handler, data, expected):
    await handler.handle(callback(data))
    rows = handler.client.edit_message_text.call_args.args[3]["inline_keyboard"]
    assert [item["callback_data"] for row in rows for item in row] == [
        *expected,
        "settings:back",
    ]
    if data in ("settings:time", "settings:score"):
        assert [len(row) for row in rows] == [2, 2, 2, 1, 1]


@pytest.mark.parametrize(
    "zone",
    [
        "America/Montevideo",
        "Europe/Berlin",
        "Asia/Tokyo",
        "Africa/Johannesburg",
        "Australia/Sydney",
        "America/Mexico_City",
    ],
)
async def test_custom_timezone_input_routed_and_cleared_after_commit(
    handler, fake_redis, zone
):
    from src.bot.pending_input import PendingInputStore
    from src.bot.updates import route_update

    handler.pending = PendingInputStore(fake_redis)
    await handler.handle(callback("settings:custom_timezone"))
    state = await handler.pending.get(999)
    assert state.action == "settings:timezone"
    payload = {
        "text": zone,
        "from": {"id": 999},
        "chat": {"id": 999, "type": "private"},
    }
    filters = AsyncMock()
    await route_update(
        {"message": payload},
        commands=AsyncMock(),
        callbacks=AsyncMock(),
        settings=handler,
        filters=filters,
    )
    handler.service.update_timezone.assert_awaited_once_with(8, zone)
    filters.handle_input.assert_not_awaited()
    assert await handler.pending.get(999) is None


async def test_invalid_custom_timezone_retry_navigation_and_filter_input_isolation(
    handler, fake_redis
):
    from src.bot.pending_input import PendingInput, PendingInputStore
    from src.i18n import LocalizedValidationError

    handler.pending = PendingInputStore(fake_redis)
    await handler.handle(callback("settings:custom_timezone"))
    handler.service.update_timezone.side_effect = LocalizedValidationError(
        "error.timezone"
    )
    payload = {
        "text": "Invalid/Zone",
        "from": {"id": 999},
        "chat": {"id": 999, "type": "private"},
    }
    assert await handler.handle_input(payload)
    assert await handler.pending.get(999) is not None
    await handler.handle(callback("settings:back"))
    assert await handler.pending.get(999) is None
    await handler.pending.set(999, PendingInput("filters:keywords", 42))
    assert await handler.handle_input(payload) is False


async def test_unauthorized_custom_timezone_input_does_not_write(handler, fake_redis):
    from src.bot.pending_input import PendingInput, PendingInputStore

    handler.pending = PendingInputStore(fake_redis)
    await handler.pending.set(999, PendingInput("settings:timezone", 42))
    for payload in [
        {
            "text": "Asia/Tokyo",
            "from": {"id": 999},
            "chat": {"id": 999, "type": "group"},
        },
        {
            "text": "Asia/Tokyo",
            "from": {"id": 999},
            "chat": {"id": 123, "type": "private"},
        },
    ]:
        assert await handler.handle_input(payload) is False
    handler.service.update_timezone.assert_not_awaited()
