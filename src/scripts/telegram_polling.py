import asyncio
import logging

from src.bot.callbacks import CallbackHandler
from src.bot.client import TelegramClient
from src.bot.polling import poll_updates
from src.config import settings
from src.db.database import async_session_factory, engine
from src.repositories.jobs import JobRepository
from src.repositories.scheduling import DeliveryBootstrap
from src.repositories.users import UserRepository
from src.services.feedback import FeedbackService
from src.services.users import OwnerService

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

            async def handle_update(update: dict) -> None:
                if "callback_query" not in update:
                    return
                # A fresh session for each callback, released before long polling.
                async with async_session_factory() as session:
                    handler = CallbackHandler(
                        UserRepository(session),
                        JobRepository(session),
                        FeedbackService(session),
                        client,
                    )
                    await handler.handle(update["callback_query"])

            logger.info("Telegram callback polling started")
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
