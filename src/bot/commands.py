import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from src.bot.client import TelegramAPIError, TelegramClient
from src.bot.dispatch import CommandDispatcher
from src.bot.formatter import _truncate
from src.bot.settings import SettingsHandler
from src.bot.statistics import format_statistics
from src.repositories.bot_queries import BotQueryRepository
from src.repositories.feedback import FeedbackRepository
from src.repositories.users import UserRepository
from src.services.collector_policy import COLLECTOR_POLICIES, source_display_name
from src.services.default_filters import default_user_filters
from src.services.entitlements import EffectiveNotificationSettings, EntitlementService
from src.services.statistics import StatisticsService

logger = logging.getLogger(__name__)

WELCOME = (
    "Job Hunter Bot\n\n"
    "I search for remote jobs, filter them based on your preferences, calculate "
    "a match score, and send the best matches in a daily digest.\n\n"
    "Use /help to see available commands."
)
HELP = (
    "/start - About the bot\n"
    "/help - Show available commands\n"
    "/status - Show bot and collector status\n"
    "/saved - Show saved jobs\n"
    "/filters - Show current filters\n"
    "/settings - Notification settings"
)
ADMIN_HELP = (
    "\n\nAdmin commands:\n"
    "/collect - Run all job collectors now\n"
    "/digest - Send today's digest now\n"
    "/stats [24h|7d|30d] - Pipeline statistics"
)
UNAVAILABLE = "This command is not available."
UNKNOWN = "Unknown command. Use /help to see available commands."
COMMANDS = {
    "start",
    "help",
    "status",
    "saved",
    "filters",
    "settings",
    "collect",
    "digest",
    "stats",
}


def parse_command(text: object, bot_username: str) -> str | None:
    if not isinstance(text, str) or not text.startswith("/"):
        return None
    token = text.split(maxsplit=1)[0]
    name, separator, target = token[1:].partition("@")
    if separator and target.lower() != bot_username.lower():
        return None
    if not re.fullmatch(r"[A-Za-z0-9_]{1,32}", name):
        return ""
    return name.lower()


def format_filters(effective: EffectiveNotificationSettings) -> str:
    filters = default_user_filters(effective.timezone)
    labels = {
        "python": "Python",
        "fastapi": "FastAPI",
        "postgresql": "PostgreSQL",
        "redis": "Redis",
        "celery": "Celery",
        "docker": "Docker",
    }
    required = "\n".join(labels.get(t, t) for t in filters.required_technologies)
    preferred = "\n".join(labels.get(t, t) for t in filters.preferred_technologies)

    def yes_no(value: bool) -> str:
        return "Yes" if value else "No"

    return (
        f"Current filters\n\nRequired technologies:\n{required or 'Any'}\n\n"
        f"Preferred:\n{preferred or 'None'}\n\n"
        f"Remote only: {yes_no(filters.remote_only)}\n"
        f"Worldwide: {yes_no(filters.worldwide_allowed)}\n"
        f"LATAM: {yes_no(filters.latam_allowed)}\n"
        f"South America: {yes_no(filters.south_america_allowed)}\n"
        f"Uruguay: {yes_no(filters.uruguay_allowed)}\n\n"
        f"Timezone: {filters.timezone}\n"
        f"Timezone tolerance: ±{filters.timezone_tolerance_hours}h\n\n"
        f"Excluded US-only: {yes_no(filters.exclude_us_only)}\n\n"
        f"Minimum score: {effective.min_score}\n"
        f"Digest time: {effective.digest_time:%H:%M}"
    )


def saved_job_messages(jobs: list) -> list[str]:
    if not jobs:
        return ["You don't have any saved jobs yet."]
    messages = []
    current = "Saved jobs:"
    for index, job in enumerate(jobs[:10], start=1):
        entry = _truncate(
            f"{index}. {_truncate(job.title, 240)}\n"
            f"{_truncate(job.company or 'Company not specified', 160)}\n{job.url}",
            3800,
        )
        combined = f"{current}\n\n{entry}"
        if len(combined.encode("utf-16-le")) // 2 > 4096:
            messages.append(current)
            current = f"Saved jobs (continued):\n\n{entry}"
        else:
            current = combined
    messages.append(current)
    return messages


class CommandHandler:
    def __init__(
        self,
        users: UserRepository,
        queries: BotQueryRepository,
        feedback: FeedbackRepository,
        client: TelegramClient,
        dispatcher: CommandDispatcher,
        entitlements: EntitlementService,
        *,
        owner_telegram_id: int | None,
        bot_username: str,
        settings_handler: SettingsHandler | None = None,
        statistics: StatisticsService | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self.statistics = statistics
        self.settings_handler = settings_handler
        self.users = users
        self.queries = queries
        self.feedback = feedback
        self.client = client
        self.dispatcher = dispatcher
        self.entitlements = entitlements
        self.owner_telegram_id = owner_telegram_id
        self.bot_username = bot_username
        self.clock = clock

    async def _reply(self, chat_id: int, text: str) -> None:
        try:
            await self.client.send_message(chat_id, text)
        except TelegramAPIError:
            # Do not replay an already dispatched admin task after a reply timeout.
            logger.warning("Command reply failed")

    async def _effective(self, user_id: int) -> EffectiveNotificationSettings | None:
        preferences = await self.queries.preferences(user_id)
        if preferences is None:
            return None
        subscription = await self.queries.subscription(user_id)
        return self.entitlements.effective(preferences, subscription, self.clock())

    async def _status(self, user_id: int) -> str:
        effective = await self._effective(user_id)
        zone = ZoneInfo(effective.timezone if effective else "UTC")
        states = {
            state.source: state for state in await self.queries.collector_states()
        }
        count = await self.queries.job_count()
        run = await self.queries.last_digest(user_id)

        def timestamp(value, fallback):
            return (
                value.astimezone(zone).strftime("%Y-%m-%d %H:%M") if value else fallback
            )

        collector_sections = []
        for source in dict.fromkeys([*COLLECTOR_POLICIES, *states]):
            collector = states.get(source)
            name = source_display_name(source)
            last_success = timestamp(
                collector.last_success_at if collector else None, "Never"
            )
            next_run = timestamp(
                collector.next_run_at if collector else None, "Not scheduled"
            )
            status = (collector.last_status if collector else None) or "Unknown"
            collector_sections.append(
                f"{name}\nLast success: {last_success}\nNext run: {next_run}\n"
                f"Last status: {status}"
            )
        collector_text = "\n\n".join(collector_sections)
        last_digest = "Never"
        if run is not None:
            day = (
                "Today"
                if run.local_date == self.clock().astimezone(zone).date()
                else str(run.local_date)
            )
            last_digest = f"{day} ({run.status})"
        digest_time = (
            effective.digest_time.strftime("%H:%M") if effective else "Unknown"
        )
        enabled = (
            ("Yes" if effective.digest_enabled else "No") if effective else "Unknown"
        )
        return (
            f"Bot status: running\n\n{collector_text}\n\n"
            f"Jobs in database: {count}\n\nDaily digest:\n"
            f"Time: {digest_time}\n"
            f"Timezone: {effective.timezone if effective else 'Unknown'}\n"
            f"Last digest: {last_digest}\nEnabled: {enabled}\n\n"
            f"Times shown in {zone.key}."
        )

    async def handle(self, message: dict) -> None:
        if not isinstance(message, dict):
            return
        command = parse_command(message.get("text"), self.bot_username)
        if command is None:
            return
        sender, chat = message.get("from"), message.get("chat")
        if not isinstance(sender, dict) or not isinstance(chat, dict):
            return
        sender_id, chat_id = sender.get("id"), chat.get("id")
        if (
            type(sender_id) is not int
            or not 0 < sender_id <= 2**63 - 1
            or type(chat_id) is not int
            or not -(2**63) < chat_id < 2**63
            or sender.get("is_bot") is True
        ):
            return
        # Never log raw message text, arguments, or unknown command names.
        logger.info(
            "Command received: %s", command if command in COMMANDS else "unknown"
        )
        if chat.get("type") != "private" or chat_id != sender_id:
            await self._reply(chat_id, UNAVAILABLE)
            return
        if command in {"start", "help"}:
            help_text = HELP + (
                ADMIN_HELP if sender_id == self.owner_telegram_id else ""
            )
            await self._reply(chat_id, WELCOME if command == "start" else help_text)
            return
        if command not in COMMANDS:
            logger.info("Unknown command")
            await self._reply(chat_id, UNKNOWN)
            return
        admin = command in {"collect", "digest", "stats"}
        if admin and (
            self.owner_telegram_id is None or sender_id != self.owner_telegram_id
        ):
            logger.warning("Unauthorized admin command")
            await self._reply(chat_id, UNAVAILABLE)
            return
        user = await self.users.get_by_telegram_id(sender_id)
        if user is None or not user.is_active:
            if admin:
                logger.warning("Unauthorized admin command")
            await self._reply(chat_id, UNAVAILABLE)
            return
        if command == "stats":
            await self._stats(chat_id, message["text"])
        elif admin:
            await self._admin(command, user.id, chat_id)
        elif command == "settings":
            if self.settings_handler is not None:
                await self.settings_handler.show(user.id, chat_id)
            else:
                await self._reply(
                    chat_id, "Notification settings are not available yet."
                )
        elif command == "status":
            await self._reply(chat_id, await self._status(user.id))
        elif command == "saved":
            jobs = await self.feedback.get_saved_jobs_for_user(user.id, limit=10)
            for text in saved_job_messages(jobs):
                await self._reply(chat_id, text)
        elif command == "filters":
            effective = await self._effective(user.id)
            await self._reply(
                chat_id,
                (
                    format_filters(effective)
                    if effective
                    else "Notification settings are not available yet."
                ),
            )

    async def _stats(self, chat_id: int, text: str) -> None:
        arguments = text.split()[1:]
        if len(arguments) > 1 or (
            arguments and arguments[0] not in {"24h", "7d", "30d"}
        ):
            await self._reply(chat_id, "Usage: /stats [24h|7d|30d]")
            return
        if self.statistics is None:
            await self._reply(chat_id, "Statistics are unavailable.")
            return
        try:
            stats = await self.statistics.get_stats(arguments[0] if arguments else "7d")
        except Exception as exc:
            logger.error("Statistics failed: %s", type(exc).__name__)
            await self._reply(chat_id, "Statistics are temporarily unavailable.")
            return
        for message in format_statistics(stats):
            await self._reply(chat_id, message)

    async def _admin(self, command: str, user_id: int, chat_id: int) -> None:
        if command == "digest":
            from src.config import settings

            effective = await self._effective(user_id)
            run = await self.queries.last_digest(user_id)
            now = self.clock()
            local_date = now.astimezone(
                ZoneInfo(effective.timezone if effective else "UTC")
            ).date()
            if (
                run is not None
                and run.local_date == local_date
                and run.status != "abandoned"
            ):
                stale = (
                    run.status == "pending"
                    and run.started_at is not None
                    and run.started_at
                    < now - timedelta(minutes=settings.DIGEST_PENDING_TIMEOUT_MINUTES)
                )
                if not stale:
                    response = {
                        "sent": "Digest already sent today.",
                        "pending": "Digest is already in progress.",
                    }.get(run.status, "Digest already attempted today.")
                    await self._reply(chat_id, response)
                    return
        action = "collection" if command == "collect" else "digest"
        logger.info("Admin %s requested", action)
        try:
            if command == "collect":
                await self.dispatcher.collect()
            else:
                await self.dispatcher.digest(user_id)
        except Exception as exc:
            logger.error("Failed to dispatch %s (%s)", action, type(exc).__name__)
            await self._reply(chat_id, f"Failed to start {action}.")
            return
        await self._reply(
            chat_id,
            ("Collection started." if command == "collect" else "Digest queued."),
        )
