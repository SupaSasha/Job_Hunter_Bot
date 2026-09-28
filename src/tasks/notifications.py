import asyncio

from src.bot.client import TelegramClient
from src.config import settings
from src.services.digests import DailyDigestService
from src.services.entitlements import EntitlementService
from src.tasks.celery_app import celery_app
from src.tasks.runtime import task_resources


async def send_daily_digest_async(
    user_id: int, expected_date: str | None = None, *, run_now: bool = False
) -> dict:
    if not settings.TELEGRAM_BOT_TOKEN:
        return {"status": "skipped", "reason": "telegram_not_configured"}
    async with task_resources() as (sessions, _):
        async with TelegramClient(settings.TELEGRAM_BOT_TOKEN) as client:
            return await DailyDigestService(
                sessions,
                client,
                EntitlementService(
                    free_digest_time=settings.FREE_DIGEST_TIME,
                    free_min_score=settings.FREE_MIN_SCORE,
                ),
            ).send(user_id, expected_date, run_now=run_now)


@celery_app.task(name="notifications.send_daily_digest")
def send_daily_digest(
    user_id: int, expected_date: str | None = None, *, run_now: bool = False
) -> dict:
    return asyncio.run(send_daily_digest_async(user_id, expected_date, run_now=run_now))
