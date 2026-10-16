import asyncio

from src.config import settings
from src.services.collection import CollectionService
from src.tasks.celery_app import celery_app
from src.tasks.runtime import task_resources


async def collect_source_async(
    source: str, expected_next_run: str | None = None
) -> dict:
    async with task_resources() as (sessions, redis):
        return await CollectionService(
            sessions, redis, settings.SCHEDULER_TIMEZONE
        ).collect(source, expected_next_run)


async def collect_remoteok_async(expected_next_run: str | None = None) -> dict:
    return await collect_source_async("remoteok", expected_next_run)


@celery_app.task(name="jobs.collect_remoteok")
def collect_remoteok(expected_next_run: str | None = None) -> dict:
    return asyncio.run(collect_remoteok_async(expected_next_run))


async def collect_weworkremotely_async(expected_next_run: str | None = None) -> dict:
    return await collect_source_async("weworkremotely", expected_next_run)


@celery_app.task(name="jobs.collect_weworkremotely")
def collect_weworkremotely(expected_next_run: str | None = None) -> dict:
    return asyncio.run(collect_weworkremotely_async(expected_next_run))


async def collect_getonboard_async(expected_next_run: str | None = None) -> dict:
    return await collect_source_async("getonboard", expected_next_run)


@celery_app.task(name="jobs.collect_getonboard")
def collect_getonboard(expected_next_run: str | None = None) -> dict:
    return asyncio.run(collect_getonboard_async(expected_next_run))


async def collect_himalayas_async(expected_next_run: str | None = None) -> dict:
    return await collect_source_async("himalayas", expected_next_run)


@celery_app.task(name="jobs.collect_himalayas")
def collect_himalayas(expected_next_run: str | None = None) -> dict:
    return asyncio.run(collect_himalayas_async(expected_next_run))


async def collect_jobicy_async(expected_next_run: str | None = None) -> dict:
    return await collect_source_async("jobicy", expected_next_run)


@celery_app.task(name="jobs.collect_jobicy")
def collect_jobicy(expected_next_run: str | None = None) -> dict:
    return asyncio.run(collect_jobicy_async(expected_next_run))


async def collect_the_muse_async(expected_next_run: str | None = None) -> dict:
    return await collect_source_async("the_muse", expected_next_run)


@celery_app.task(name="jobs.collect_the_muse")
def collect_the_muse(expected_next_run: str | None = None) -> dict:
    return asyncio.run(collect_the_muse_async(expected_next_run))


async def collect_hacker_news_async(expected_next_run: str | None = None) -> dict:
    return await collect_source_async("hacker_news", expected_next_run)


@celery_app.task(name="jobs.collect_hacker_news")
def collect_hacker_news(expected_next_run: str | None = None) -> dict:
    return asyncio.run(collect_hacker_news_async(expected_next_run))


async def collect_jooble_async(expected_next_run: str | None = None) -> dict:
    return await collect_source_async("jooble", expected_next_run)


@celery_app.task(name="jobs.collect_jooble")
def collect_jooble(expected_next_run: str | None = None) -> dict:
    return asyncio.run(collect_jooble_async(expected_next_run))


COLLECTOR_TASKS = {
    "remoteok": collect_remoteok,
    "weworkremotely": collect_weworkremotely,
    "getonboard": collect_getonboard,
    "himalayas": collect_himalayas,
    "jobicy": collect_jobicy,
    "the_muse": collect_the_muse,
    "hacker_news": collect_hacker_news,
    "jooble": collect_jooble,
}
