import asyncio

from src.config import settings
from src.repositories.scheduling import DeliveryBootstrap
from src.services.entitlements import EntitlementService
from src.services.scheduler import SchedulerService
from src.services.users import OwnerService
from src.tasks.celery_app import celery_app
from src.tasks.runtime import task_resources


async def dispatch_collectors_async() -> int:
    async with task_resources() as (sessions, _):
        return await SchedulerService(
            sessions,
            celery_app.send_task,
            settings.SCHEDULER_TIMEZONE,
            EntitlementService(),
        ).dispatch_collectors()


async def dispatch_digests_async() -> int:
    async with task_resources() as (sessions, _):
        if settings.TELEGRAM_CHAT_ID is not None:
            async with sessions() as session:
                await OwnerService(session).get_or_create(settings.TELEGRAM_CHAT_ID)
        await DeliveryBootstrap(sessions, settings).ensure_users()
        if not settings.TELEGRAM_BOT_TOKEN:
            return 0
        return await SchedulerService(
            sessions,
            celery_app.send_task,
            settings.SCHEDULER_TIMEZONE,
            EntitlementService(
                free_digest_time=settings.FREE_DIGEST_TIME,
                free_min_score=settings.FREE_MIN_SCORE,
            ),
        ).dispatch_digests()


@celery_app.task(name="scheduler.dispatch_collectors")
def dispatch_collectors() -> int:
    return asyncio.run(dispatch_collectors_async())


@celery_app.task(name="scheduler.dispatch_digests")
def dispatch_digests() -> int:
    return asyncio.run(dispatch_digests_async())
