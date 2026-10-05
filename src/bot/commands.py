import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from src.bot.client import TelegramAPIError, TelegramClient
from src.bot.dispatch import CommandDispatcher
from src.bot.filters import FiltersHandler
from src.bot.formatter import _truncate
from src.bot.settings import SettingsHandler, build_language_keyboard
from src.bot.statistics import format_statistics
from src.i18n import (
    DEFAULT_LANGUAGE,
    Language,
    initial_language,
    status_label,
    t,
    user_language,
)
from src.repositories.bot_queries import BotQueryRepository
from src.repositories.feedback import FeedbackRepository
from src.repositories.users import UserRepository
from src.services.collector_policy import COLLECTOR_POLICIES, source_display_name
from src.services.entitlements import EffectiveNotificationSettings, EntitlementService
from src.services.statistics import StatisticsService
from src.services.user_language import UserLanguageService

logger = logging.getLogger(__name__)

WELCOME = t("start.welcome")
HELP = t("help.public")
ADMIN_HELP = t("help.admin")
UNAVAILABLE = t("command.unavailable")
UNKNOWN = t("command.unknown")
COMMANDS = {
    "start",
    "help",
    "status",
    "saved",
    "filters",
    "settings",
    "cancel",
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


def saved_job_messages(jobs: list, language: Language = DEFAULT_LANGUAGE) -> list[str]:
    if not jobs:
        return [t("saved.empty", language)]
    messages = []
    current = t("saved.title", language)
    for index, job in enumerate(jobs[:10], start=1):
        entry = _truncate(
            f"{index}. {_truncate(job.title, 240)}\n"
            f"{_truncate(job.company or t('job.company_missing', language), 160)}\n"
            f"{job.url}",
            3800,
        )
        combined = f"{current}\n\n{entry}"
        if len(combined.encode("utf-16-le")) // 2 > 4096:
            messages.append(current)
            current = t("saved.continued", language) + f"\n\n{entry}"
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
        filters_handler: FiltersHandler | None = None,
        statistics: StatisticsService | None = None,
        languages: UserLanguageService | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self.languages = languages
        self.filters_handler = filters_handler
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

    async def _status(self, user_id: int, language: Language = DEFAULT_LANGUAGE) -> str:
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
                collector.last_success_at if collector else None,
                t("status.never", language),
            )
            next_run = timestamp(
                collector.next_run_at if collector else None,
                t("status.not_scheduled", language),
            )
            status = (collector.last_status if collector else None) or t(
                "common.unknown", language
            )
            collector_sections.append(
                t(
                    "status.collector",
                    language,
                    name=name,
                    last_success=last_success,
                    next_run=next_run,
                    status=status_label(status, language),
                )
            )
        collector_text = "\n\n".join(collector_sections)
        last_digest = t("status.never", language)
        if run is not None:
            day = (
                t("status.today", language)
                if run.local_date == self.clock().astimezone(zone).date()
                else str(run.local_date)
            )
            last_digest = f"{day} ({status_label(run.status, language)})"
        digest_time = (
            effective.digest_time.strftime("%H:%M")
            if effective
            else t("common.unknown", language)
        )
        enabled = (
            t("common.yes" if effective.digest_enabled else "common.no", language)
            if effective
            else t("common.unknown", language)
        )
        return t(
            "status.body",
            language,
            collectors=collector_text,
            count=count,
            time=digest_time,
            timezone=effective.timezone if effective else t("common.unknown", language),
            last_digest=last_digest,
            enabled=enabled,
            zone=zone.key,
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
        language = initial_language(sender.get("language_code"))
        if chat.get("type") != "private" or chat_id != sender_id:
            await self._reply(chat_id, t("command.unavailable", language))
            return
        user = await self.users.get_by_telegram_id(sender_id)
        language = user_language(user, sender.get("language_code"))
        if command == "start":
            new_user = user is None
            if self.languages is not None:
                # Also recover missing bootstrap rows after interrupted onboarding.
                user = await self.languages.register(
                    sender_id, sender.get("language_code")
                )
                language = user_language(user, sender.get("language_code"))
            if new_user:
                try:
                    await self.client.send_message(
                        chat_id,
                        t("language.choose", language),
                        build_language_keyboard(language, onboarding=True),
                    )
                except TelegramAPIError:
                    logger.warning("Language picker reply failed")
            else:
                await self._reply(chat_id, t("start.welcome", language))
            return
        if command == "help":
            text = t("help.public", language) + (
                t("help.admin", language) if sender_id == self.owner_telegram_id else ""
            )
            await self._reply(chat_id, text)
            return
        if command not in COMMANDS:
            logger.info("Unknown command")
            await self._reply(chat_id, t("command.unknown", language))
            return
        admin = command in {"collect", "digest", "stats"}
        if admin and (
            self.owner_telegram_id is None or sender_id != self.owner_telegram_id
        ):
            logger.warning("Unauthorized admin command")
            await self._reply(chat_id, t("command.unavailable", language))
            return
        if user is None or not user.is_active:
            if admin:
                logger.warning("Unauthorized admin command")
            await self._reply(chat_id, t("command.unavailable", language))
            return
        if command == "stats":
            await self._stats(chat_id, message["text"], language)
        elif admin:
            await self._admin(command, user.id, chat_id, language)
        elif command == "settings":
            if self.settings_handler is not None:
                await self.settings_handler.show(user.id, chat_id, language)
            else:
                await self._reply(chat_id, t("settings.unavailable", language))
        elif command == "status":
            await self._reply(chat_id, await self._status(user.id, language))
        elif command == "saved":
            jobs = await self.feedback.get_saved_jobs_for_user(user.id, limit=10)
            for text in saved_job_messages(jobs, language):
                await self._reply(chat_id, text)
        elif command == "filters":
            if self.filters_handler is not None:
                await self.filters_handler.show(user.id, chat_id, language)
            else:
                await self._reply(chat_id, t("filters.unavailable", language))
        elif command == "cancel":
            if self.filters_handler is not None:
                await self.filters_handler.cancel(chat_id, language)
            else:
                await self._reply(chat_id, t("input.cancelled", language))

    async def _stats(
        self, chat_id: int, text: str, language: Language = DEFAULT_LANGUAGE
    ) -> None:
        arguments = text.split()[1:]
        if len(arguments) > 1 or (
            arguments and arguments[0] not in {"24h", "7d", "30d"}
        ):
            await self._reply(chat_id, t("command.stats_usage", language))
            return
        if self.statistics is None:
            await self._reply(chat_id, t("command.stats_unavailable", language))
            return
        try:
            stats = await self.statistics.get_stats(arguments[0] if arguments else "7d")
        except Exception as exc:
            logger.error("Statistics failed: %s", type(exc).__name__)
            await self._reply(chat_id, t("command.stats_failed", language))
            return
        for message in format_statistics(stats):
            await self._reply(chat_id, message)

    async def _admin(
        self,
        command: str,
        user_id: int,
        chat_id: int,
        language: Language = DEFAULT_LANGUAGE,
    ) -> None:
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
                        "sent": t("digest.already_sent", language),
                        "empty": t("digest.empty", language),
                        "pending": t("digest.in_progress", language),
                    }.get(run.status, t("digest.attempted", language))
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
            await self._reply(
                chat_id,
                t(
                    (
                        "command.collect_failed"
                        if command == "collect"
                        else "digest.failed"
                    ),
                    language,
                ),
            )
            return
        await self._reply(
            chat_id,
            t(
                "command.collect_started" if command == "collect" else "digest.queued",
                language,
            ),
        )
