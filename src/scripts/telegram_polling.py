import asyncio
import logging

from src.bot.callbacks import CallbackHandler
from src.bot.client import TelegramClient
from src.bot.commands import HELP, CommandHandler
from src.bot.dispatch import CeleryCommandDispatcher
from src.bot.polling import poll_updates
from src.bot.settings import SettingsHandler
from src.bot.updates import route_update
from src.config import settings
from src.db.database import async_session_factory, engine
from src.repositories.bot_queries import BotQueryRepository
from src.repositories.feedback import FeedbackRepository
from src.repositories.jobs import JobRepository
from src.repositories.scheduling import DeliveryBootstrap
from src.repositories.statistics import StatisticsRepository
from src.repositories.users import UserRepository
from src.services.entitlements import EntitlementService
from src.services.feedback import FeedbackService
from src.services.notification_settings import NotificationSettingsService
from src.services.statistics import StatisticsService
from src.services.users import OwnerService
from src.tasks.jobs import COLLECTOR_TASKS
from src.tasks.notifications import send_daily_digest

logger = logging.getLogger(__name__)


async def main() -> None:
    try:
        if not settings.TELEGRAM_BOT_TOKEN:
            logger.warning("Telegram polling skipped: bot token is not configured")
            return
        if settings.TELEGRAM_CHAT_ID is not None:
            async with async_session_factory() as session:
                await OwnerService(session).get_or_create(settings.TELEGRAM_CHAT_ID)

        await DeliveryBootstrap(async_session_factory, settings).ensure_users()

        async with TelegramClient(settings.TELEGRAM_BOT_TOKEN) as client:
            bot_username = await client.get_bot_username()
            dispatcher = CeleryCommandDispatcher(
                COLLECTOR_TASKS.values(), send_daily_digest
            )
            entitlements = EntitlementService(
                free_digest_time=settings.FREE_DIGEST_TIME,
                free_min_score=settings.FREE_MIN_SCORE,
            )

            async def handle_update(update: dict) -> None:
                # A fresh session for each update, released before long polling.
                async with async_session_factory() as session:
                    callbacks = CallbackHandler(
                        UserRepository(session),
                        JobRepository(session),
                        FeedbackService(session),
                        client,
                    )
                    settings_handler = SettingsHandler(
                        UserRepository(session),
                        NotificationSettingsService(session, entitlements),
                        client,
                        help_text=HELP,
                    )
                    commands = CommandHandler(
                        UserRepository(session),
                        BotQueryRepository(session),
                        FeedbackRepository(session),
                        client,
                        dispatcher,
                        entitlements,
                        owner_telegram_id=settings.TELEGRAM_CHAT_ID,
                        bot_username=bot_username,
                        settings_handler=settings_handler,
                        statistics=StatisticsService(
                            StatisticsRepository(session), entitlements
                        ),
                    )
                    await route_update(
                        update,
                        commands=commands,
                        callbacks=callbacks,
                        settings=settings_handler,
                    )

            logger.info("Telegram command and callback polling started")
            await poll_updates(client, handle_update)
    finally:
        await engine.dispose()


def run() -> None:
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Telegram polling stopped")


if __name__ == "__main__":
    run()
