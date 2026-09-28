import logging
from datetime import UTC, date, datetime, time, timedelta
from unittest.mock import AsyncMock

import pytest

from src.bot.client import TelegramAPIError, TelegramClient
from src.bot.commands import HELP, WELCOME, CommandHandler, parse_command
from src.bot.dispatch import CommandDispatcher
from src.models.job import JobORM
from src.models.scheduling import (
    CollectorStateORM,
    DigestRunORM,
    UserNotificationSettingsORM,
    UserSubscriptionORM,
)
from src.models.user import UserORM
from src.repositories.bot_queries import BotQueryRepository
from src.repositories.feedback import FeedbackRepository
from src.repositories.users import UserRepository
from src.services.entitlements import EntitlementService

NOW = datetime(2026, 9, 28, 15, tzinfo=UTC)


def message(text, sender_id=123, chat_id=None, chat_type="private"):
    return {
        "text": text,
        "from": {"id": sender_id, "is_bot": False},
        "chat": {"id": sender_id if chat_id is None else chat_id, "type": chat_type},
    }


@pytest.fixture
def handler():
    users = AsyncMock(spec=UserRepository)
    users.get_by_telegram_id.return_value = UserORM(
        id=7, telegram_id=123, is_active=True
    )
    queries = AsyncMock(spec=BotQueryRepository)
    queries.preferences.return_value = UserNotificationSettingsORM(
        user_id=7,
        timezone="America/Montevideo",
        digest_time=time(11, 30),
        min_score=42,
        max_jobs_per_digest=10,
        digest_enabled=True,
    )
    queries.subscription.return_value = None
    queries.collector_state.return_value = CollectorStateORM(
        source="remoteok",
        last_success_at=datetime(2026, 9, 28, 6, 12, tzinfo=UTC),
        next_run_at=datetime(2026, 9, 28, 13, 47, tzinfo=UTC),
        last_status="success",
    )
    queries.job_count.return_value = 428
    queries.last_digest.return_value = DigestRunORM(
        local_date=date(2026, 9, 28), status="sent"
    )
    feedback = AsyncMock(spec=FeedbackRepository)
    feedback.get_saved_jobs_for_user.return_value = []
    return CommandHandler(
        users,
        queries,
        feedback,
        AsyncMock(spec=TelegramClient),
        AsyncMock(spec=CommandDispatcher),
        EntitlementService(),
        owner_telegram_id=123,
        bot_username="ExampleBot",
        clock=lambda: NOW,
    )


def reply(handler):
    return handler.client.send_message.call_args.args[1]


@pytest.mark.parametrize("command,text", [("/start", WELCOME), ("/help", HELP)])
async def test_public_commands(handler, command, text):
    handler.users.get_by_telegram_id.return_value = None
    await handler.handle(message(command, sender_id=999))
    handler.client.send_message.assert_awaited_once_with(999, text)
    handler.users.get_by_telegram_id.assert_not_awaited()
    handler.users.add.assert_not_awaited()


async def test_help_lists_all_commands(handler):
    await handler.handle(message("/help"))
    for command in ("start", "help", "status", "saved", "filters", "collect", "digest"):
        assert f"/{command} - " in reply(handler)


async def test_status_uses_real_values_and_local_timezone(handler):
    await handler.handle(message("/status"))
    text = reply(handler)
    for value in (
        "Bot status: running",
        "Last success: 2026-09-28 03:12",
        "Next run: 2026-09-28 10:47",
        "Last status: success",
        "Jobs in database: 428",
        "Time: 09:00",
        "Timezone: America/Montevideo",
        "Last digest: Today (sent)",
    ):
        assert value in text
    handler.queries.last_digest.assert_awaited_once_with(7)


async def test_status_missing_state_uses_explicit_unknowns(handler):
    handler.queries.collector_state.return_value = None
    handler.queries.preferences.return_value = None
    handler.queries.last_digest.return_value = None
    handler.queries.job_count.return_value = 0
    await handler.handle(message("/status"))
    for value in (
        "Last success: Never",
        "Next run: Not scheduled",
        "Last status: Unknown",
        "Jobs in database: 0",
        "Time: Unknown",
        "Timezone: Unknown",
        "Last digest: Never",
    ):
        assert value in reply(handler)


async def test_status_empty_digest_not_reported_as_sent(handler):
    handler.queries.last_digest.return_value = DigestRunORM(
        local_date=date(2026, 9, 27), status="empty"
    )
    await handler.handle(message("/status"))
    assert "Last digest: 2026-09-27 (empty)" in reply(handler)


async def test_saved_shows_jobs_without_descriptions(handler):
    handler.feedback.get_saved_jobs_for_user.return_value = [
        JobORM(
            title="Python Backend Developer",
            company="Acme",
            url="https://example.com/1",
            description="Private long description",
        ),
        JobORM(title="Backend Engineer", company=None, url="https://example.com/2"),
    ]
    await handler.handle(message("/saved"))
    handler.feedback.get_saved_jobs_for_user.assert_awaited_once_with(7, limit=10)
    assert "1. Python Backend Developer\nAcme\nhttps://example.com/1" in reply(handler)
    assert "2. Backend Engineer\nCompany not specified" in reply(handler)
    assert "description" not in reply(handler)


async def test_saved_empty(handler):
    await handler.handle(message("/saved"))
    assert reply(handler) == "You don't have any saved jobs yet."


async def test_saved_long_unicode_is_split_and_capped_at_ten(handler):
    handler.feedback.get_saved_jobs_for_user.return_value = [
        JobORM(
            title="🐍" * 300,
            company="Example",
            url=f"https://example.com/{i}/" + "a" * 900,
        )
        for i in range(12)
    ]
    await handler.handle(message("/saved"))
    texts = [call.args[1] for call in handler.client.send_message.call_args_list]
    assert len(texts) > 1
    assert all(len(t.encode("utf-16-le")) // 2 <= 4096 for t in texts)
    assert "10. " in "\n".join(texts)
    assert "11. " not in "\n".join(texts)


@pytest.mark.parametrize(
    "status,end,premium",
    [
        ("trial", NOW + timedelta(days=1), True),
        ("trial", NOW, False),
        ("active", None, True),
        ("active", NOW, False),
    ],
)
async def test_filters_use_effective_entitlements(handler, status, end, premium):
    handler.queries.subscription.return_value = UserSubscriptionORM(
        status=status, trial_ends_at=end, subscription_ends_at=end
    )
    await handler.handle(message("/filters"))
    text = reply(handler)
    assert f"Minimum score: {42 if premium else 70}" in text
    assert f"Digest time: {'11:30' if premium else '09:00'}" in text
    for value in (
        "Python",
        "FastAPI",
        "PostgreSQL",
        "Redis",
        "Celery",
        "Docker",
        "Remote only: Yes",
        "Timezone tolerance: ±2h",
        "Excluded US-only: Yes",
    ):
        assert value in text
    assert "trial_ends_at" not in text and "user_id" not in text


async def test_missing_preferences_are_not_invented(handler):
    handler.queries.preferences.return_value = None
    await handler.handle(message("/filters"))
    assert reply(handler) == "Notification settings are not available yet."


@pytest.mark.parametrize(
    "command,expected",
    [
        ("collect", "Collection started."),
        ("digest", "Digest started."),
    ],
)
async def test_owner_dispatches_without_waiting_for_worker(handler, command, expected):
    await handler.handle(message(f"/{command}"))
    if command == "collect":
        handler.dispatcher.collect.assert_awaited_once_with()
        handler.dispatcher.digest.assert_not_awaited()
    else:
        handler.dispatcher.digest.assert_awaited_once_with(7)
        handler.dispatcher.collect.assert_not_awaited()
    assert reply(handler) == expected


@pytest.mark.parametrize("command", ["collect", "digest"])
@pytest.mark.parametrize("owner", [123, None])
async def test_non_owner_cannot_dispatch(handler, command, owner):
    handler.owner_telegram_id = owner
    await handler.handle(message(f"/{command}", sender_id=999))
    assert reply(handler) == "This command is not available."
    handler.dispatcher.collect.assert_not_awaited()
    handler.dispatcher.digest.assert_not_awaited()
    handler.users.get_by_telegram_id.assert_not_awaited()


@pytest.mark.parametrize("command", ["status", "saved", "filters", "collect", "digest"])
@pytest.mark.parametrize("missing", [True, False])
async def test_unknown_or_inactive_user_cannot_access_data(handler, command, missing):
    handler.users.get_by_telegram_id.return_value = (
        None if missing else UserORM(id=7, telegram_id=123, is_active=False)
    )
    await handler.handle(message(f"/{command}"))
    assert reply(handler) == "This command is not available."
    handler.queries.job_count.assert_not_awaited()
    handler.feedback.get_saved_jobs_for_user.assert_not_awaited()
    handler.dispatcher.collect.assert_not_awaited()
    handler.dispatcher.digest.assert_not_awaited()


@pytest.mark.parametrize("command", ["collect", "digest", "status", "saved", "filters"])
async def test_group_or_mismatched_chat_cannot_leak_owner_data(handler, command):
    await handler.handle(message(f"/{command}", chat_id=-42, chat_type="group"))
    assert reply(handler) == "This command is not available."
    handler.users.get_by_telegram_id.assert_not_awaited()
    handler.dispatcher.collect.assert_not_awaited()
    handler.dispatcher.digest.assert_not_awaited()


@pytest.mark.parametrize("command", ["collect", "digest"])
async def test_dispatch_failure_has_safe_reply_and_log(handler, command, caplog):
    getattr(handler.dispatcher, command).side_effect = RuntimeError("secret-token")
    with caplog.at_level(logging.INFO):
        await handler.handle(message(f"/{command} secret-argument"))
    expected = "collection" if command == "collect" else "digest"
    assert reply(handler) == f"Failed to start {expected}."
    assert "secret-token" not in caplog.text
    assert "secret-argument" not in caplog.text
    assert "Failed to dispatch" in caplog.text


async def test_unknown_command_hint_does_not_log_raw_text(handler, caplog):
    with caplog.at_level(logging.INFO):
        await handler.handle(message("/secret_token credentials"))
    assert reply(handler) == "Unknown command. Use /help to see available commands."
    assert "Unknown command" in caplog.text
    assert "secret_token" not in caplog.text and "credentials" not in caplog.text


async def test_reply_failure_does_not_replay_admin_side_effect(handler):
    handler.client.send_message.side_effect = TelegramAPIError("timeout")
    await handler.handle(message("/collect"))
    handler.dispatcher.collect.assert_awaited_once()


@pytest.mark.parametrize(
    "text,expected",
    [
        ("/start", "start"),
        ("/help@ExampleBot", "help"),
        ("/HELP@examplebot argument", "help"),
        ("/help@OtherBot", None),
        ("hello", None),
        (None, None),
        ("/", ""),
        ("/foo", "foo"),
        ("/help@ExampleBot@OtherBot", None),
    ],
)
def test_command_parsing(text, expected):
    assert parse_command(text, "ExampleBot") == expected


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"text": "/start"},
        message("/start", sender_id=True),
        message("/start", sender_id=0),
        message("/start", sender_id=2**63),
        message("plain text"),
        message("/help@OtherBot"),
    ],
)
async def test_invalid_or_unaddressed_message_is_ignored(handler, payload):
    await handler.handle(payload)
    handler.client.send_message.assert_not_awaited()
