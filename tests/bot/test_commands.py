import logging
from datetime import UTC, date, datetime, time, timedelta
from unittest.mock import AsyncMock

import pytest

from src.bot.client import TelegramAPIError, TelegramClient
from src.bot.commands import HELP, WELCOME, CommandHandler, parse_command
from src.bot.dispatch import CommandDispatcher
from src.bot.filters import FiltersHandler
from src.bot.settings import SettingsHandler
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
    queries.collector_states.return_value = [
        CollectorStateORM(
            source="remoteok",
            last_success_at=datetime(2026, 9, 28, 6, 12, tzinfo=UTC),
            next_run_at=datetime(2026, 9, 28, 13, 47, tzinfo=UTC),
            last_status="success",
        )
    ]
    queries.job_count.return_value = 428
    queries.last_digest.return_value = None
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
        filters_handler=AsyncMock(spec=FiltersHandler),
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
    for command in (
        "start",
        "help",
        "status",
        "saved",
        "filters",
        "settings",
        "collect",
        "digest",
    ):
        assert f"/{command} - " in reply(handler)


async def test_status_uses_real_values_and_local_timezone(handler):
    handler.queries.last_digest.return_value = DigestRunORM(
        local_date=date(2026, 9, 28), status="sent"
    )
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
    handler.queries.collector_states.return_value = []
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
async def test_filters_available_regardless_of_entitlements(
    handler, status, end, premium
):
    handler.queries.subscription.return_value = UserSubscriptionORM(
        status=status, trial_ends_at=end, subscription_ends_at=end
    )
    await handler.handle(message("/filters"))
    handler.filters_handler.show.assert_awaited_once_with(7, 123)
    handler.queries.preferences.assert_not_awaited()
    handler.queries.subscription.assert_not_awaited()


async def test_filters_do_not_require_notification_preferences(handler):
    handler.queries.preferences.return_value = None
    await handler.handle(message("/filters"))
    handler.filters_handler.show.assert_awaited_once_with(7, 123)
    handler.queries.preferences.assert_not_awaited()


async def test_cancel_delegates_to_filter_handler(handler):
    await handler.handle(message("/cancel"))
    handler.filters_handler.cancel.assert_awaited_once_with(123)


@pytest.mark.parametrize(
    "command,expected",
    [
        ("collect", "Collection started."),
        (
            "digest",
            "Digest queued.",
        ),
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


@pytest.mark.parametrize("command", ["collect", "digest", "stats"])
@pytest.mark.parametrize("owner", [123, None])
async def test_non_owner_cannot_dispatch(handler, command, owner):
    handler.owner_telegram_id = owner
    await handler.handle(message(f"/{command}", sender_id=999))
    assert reply(handler) == "This command is not available."
    handler.dispatcher.collect.assert_not_awaited()
    handler.dispatcher.digest.assert_not_awaited()
    handler.users.get_by_telegram_id.assert_not_awaited()


@pytest.mark.parametrize(
    "command", ["status", "saved", "filters", "settings", "collect", "digest", "stats"]
)
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


@pytest.mark.parametrize(
    "command", ["collect", "digest", "stats", "status", "saved", "filters", "settings"]
)
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


async def test_settings_available_to_registered_non_owner(handler):
    handler.settings_handler = AsyncMock(spec=SettingsHandler)
    await handler.handle(message("/settings", sender_id=999))
    handler.settings_handler.show.assert_awaited_once_with(7, 999)


async def test_public_help_hides_admin_commands(handler):
    await handler.handle(message("/help", sender_id=999))
    assert "/settings - " in reply(handler)
    assert "/collect" not in reply(handler)
    assert "/digest" not in reply(handler)


async def test_status_lists_each_persisted_source_and_missing_registered_state(handler):
    handler.queries.collector_states.return_value.append(
        CollectorStateORM(
            source="weworkremotely",
            last_success_at=NOW,
            next_run_at=NOW + timedelta(hours=4),
            last_status="success",
        )
    )
    await handler.handle(message("/status"))
    text = reply(handler)
    assert "Remote OK" in text
    assert (
        "We Work Remotely\nLast success: 2026-09-28 12:00\nNext run: 2026-09-28 16:00"
        in text
    )
    handler.queries.collector_states.return_value = []
    await handler.handle(message("/status"))
    assert "We Work Remotely\nLast success: Never" in reply(handler)


async def test_getonboard_status_and_never_run_placeholder(handler):
    await handler.handle(message("/status"))
    assert "Get on Board\nLast success: Never" in reply(handler)
    handler.queries.collector_states.return_value.append(
        CollectorStateORM(
            source="getonboard",
            last_success_at=NOW,
            next_run_at=NOW + timedelta(hours=8),
            last_status="success",
        )
    )
    await handler.handle(message("/status"))
    assert "Get on Board\nLast success: 2026-09-28 12:00" in reply(handler)
    assert "Remote OK" in reply(handler) and "We Work Remotely" in reply(handler)


async def test_owner_collect_dispatches_all_three_real_registered_tasks(handler):
    from contextlib import ExitStack
    from unittest.mock import Mock, patch

    from src.bot.dispatch import CeleryCommandDispatcher
    from src.tasks.jobs import COLLECTOR_TASKS

    assert set(COLLECTOR_TASKS) == {"remoteok", "weworkremotely", "getonboard"}
    with ExitStack() as stack:
        publishers = [
            stack.enter_context(patch.object(task, "delay"))
            for task in COLLECTOR_TASKS.values()
        ]
        handler.dispatcher = CeleryCommandDispatcher(COLLECTOR_TASKS.values(), Mock())
        await handler.handle(message("/collect"))
        for publisher in publishers:
            publisher.assert_called_once_with()
    assert reply(handler) == "Collection started."


@pytest.mark.parametrize(
    "text,period",
    [
        ("/stats", "7d"),
        ("/stats 24h", "24h"),
        ("/stats@ExampleBot 7d", "7d"),
        ("/stats 30d", "30d"),
    ],
)
async def test_owner_stats_empty_database_sections(handler, text, period):
    from src.schemas.statistics import BotStats, CollectorStats
    from src.services.statistics import StatisticsService

    handler.statistics = AsyncMock(spec=StatisticsService)
    handler.statistics.get_stats.return_value = BotStats(
        period=period,
        since=NOW - timedelta(days=7),
        until=NOW,
        collectors=[CollectorStats(source="remoteok")],
    )
    await handler.handle(message(text))
    handler.statistics.get_stats.assert_awaited_once_with(period)
    for section in [
        "Collectors",
        "Remote OK",
        "Pipeline",
        "90–100",
        "0–49",
        "Delivery",
        "Feedback",
        "Users",
        "Data quality",
        "N/A",
    ]:
        assert section in reply(handler)
    handler.dispatcher.collect.assert_not_awaited()
    handler.dispatcher.digest.assert_not_awaited()


@pytest.mark.parametrize("text", ["/stats 1d", "/stats 7d extra"])
async def test_invalid_stats_period_does_not_query(handler, text):
    handler.statistics = AsyncMock()
    await handler.handle(message(text))
    assert reply(handler) == "Usage: /stats [24h|7d|30d]"
    handler.statistics.get_stats.assert_not_awaited()


async def test_stats_only_in_owner_help(handler):
    await handler.handle(message("/help"))
    assert "/stats" in reply(handler)
    await handler.handle(message("/help", sender_id=999))
    assert "/stats" not in reply(handler)


async def test_stats_error_does_not_expose_database_details(handler, caplog):
    handler.statistics = AsyncMock()
    handler.statistics.get_stats.side_effect = RuntimeError("private credentials")
    with caplog.at_level(logging.ERROR):
        await handler.handle(message("/stats"))
    assert reply(handler) == "Statistics are temporarily unavailable."
    assert "private credentials" not in caplog.text


def test_stats_long_output_split_at_telegram_limit():
    from src.bot.statistics import format_statistics
    from src.schemas.statistics import BotStats, CollectorStats

    stats = BotStats(
        period="7d",
        since=NOW,
        until=NOW,
        collectors=[CollectorStats(source=f"source_{n}") for n in range(30)],
    )
    messages = format_statistics(stats)
    assert len(messages) > 1
    assert all(len(text.encode("utf-16-le")) // 2 <= 4096 for text in messages)
    assert "Users" in "\n".join(messages)


def test_historical_digests_do_not_appear_as_measured_zeroes():
    from src.bot.statistics import format_statistics
    from src.schemas.statistics import BotStats, DigestStats

    stats = BotStats(
        period="7d",
        since=NOW,
        until=NOW,
        digest=DigestStats(runs=3, unmeasured_runs=3, selected_count=2, sent_count=2),
    )
    text = "\n".join(format_statistics(stats))
    assert "Candidates: N/A" in text
    assert "90–100: N/A" in text
    assert "Selected: 2 | Sent: 2" in text


@pytest.mark.parametrize(
    "status,response",
    [
        ("sent", "Digest already sent today."),
        ("pending", "Digest is already in progress."),
        ("empty", "Digest already attempted today."),
    ],
)
async def test_manual_digest_reports_existing_attempt(handler, status, response):
    handler.queries.last_digest.return_value = DigestRunORM(
        local_date=NOW.date(), status=status, started_at=NOW
    )
    await handler.handle(message("/digest"))
    assert reply(handler) == response
    handler.dispatcher.digest.assert_not_awaited()


async def test_manual_digest_can_recover_stale_attempt(handler):
    handler.queries.last_digest.return_value = DigestRunORM(
        local_date=NOW.date(), status="pending", started_at=NOW - timedelta(hours=1)
    )
    await handler.handle(message("/digest"))
    handler.dispatcher.digest.assert_awaited_once_with(7)
    assert "queued" in reply(handler)
