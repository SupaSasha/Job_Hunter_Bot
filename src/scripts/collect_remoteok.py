import asyncio
import logging
from contextlib import AsyncExitStack

from src.bot.client import TelegramClient
from src.collectors.remoteok import RemoteOKCollector
from src.config import settings
from src.db.database import async_session_factory, engine
from src.schemas.filters import UserFilterDTO
from src.services.jobs import JobSaveService
from src.services.notifications import NotificationService
from src.services.pipeline import JobPipeline
from src.services.users import OwnerService


def owner_filters() -> UserFilterDTO:
    return UserFilterDTO(
        required_technologies=["python"],
        preferred_technologies=["fastapi", "postgresql", "redis", "celery", "docker"],
        remote_only=True,
        worldwide_allowed=True,
        latam_allowed=True,
        south_america_allowed=True,
        uruguay_allowed=True,
        exclude_us_only=True,
        timezone="America/Montevideo",
        timezone_tolerance_hours=2,
    )


async def main() -> None:
    try:
        async with AsyncExitStack() as stack:
            session = await stack.enter_async_context(async_session_factory())
            owner = None
            notifications = None
            if settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID is not None:
                # Keep the owner detached from per-job save/rollback transactions.
                async with async_session_factory() as owner_session:
                    owner = await OwnerService(owner_session).get_or_create(
                        settings.TELEGRAM_CHAT_ID
                    )
                client = await stack.enter_async_context(
                    TelegramClient(settings.TELEGRAM_BOT_TOKEN)
                )
                notifications = NotificationService(session, client)
            else:
                print("Telegram manual test skipped: credentials are not configured")

            jobs = await RemoteOKCollector().collect()
            pipeline = JobPipeline(
                JobSaveService(session),
                filters=owner_filters(),
                min_score=settings.MIN_NOTIFICATION_SCORE,
                max_notifications=settings.MAX_NOTIFICATIONS_PER_RUN,
                notifications=notifications,
                owner=owner,
            )
            summary = await pipeline.run(jobs)
            for key, value in summary.model_dump().items():
                print(f"{key}: {value}")
            if not jobs:
                logging.warning("No jobs received; pipeline has not been exercised.")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
