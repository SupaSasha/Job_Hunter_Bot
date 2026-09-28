import asyncio

from src.config import settings
from src.services.collection import CollectionService
from src.tasks.celery_app import celery_app
from src.tasks.runtime import task_resources


async def collect_remoteok_async(expected_next_run: str | None = None) -> dict:
    async with task_resources() as (sessions, redis):
        return await CollectionService(
            sessions, redis, settings.SCHEDULER_TIMEZONE
        ).collect_remoteok(expected_next_run)


@celery_app.task(name="jobs.collect_remoteok")
def collect_remoteok(expected_next_run: str | None = None) -> dict:
    return asyncio.run(collect_remoteok_async(expected_next_run))


async def collect_weworkremotely_async(expected_next_run: str | None = None) -> dict:
    async with task_resources() as (sessions, redis):
        return await CollectionService(
            sessions, redis, settings.SCHEDULER_TIMEZONE
        ).collect("weworkremotely", expected_next_run)


@celery_app.task(name="jobs.collect_weworkremotely")
def collect_weworkremotely(expected_next_run: str | None = None) -> dict:
    return asyncio.run(collect_weworkremotely_async(expected_next_run))


COLLECTOR_TASKS = {
    "remoteok": collect_remoteok,
    "weworkremotely": collect_weworkremotely,
}
