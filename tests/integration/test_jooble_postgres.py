import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text

from src.collectors.base import BaseJobCollector
from src.collectors.jooble import parse_job
from src.models import (
    CollectorRunORM,
    CollectorStateORM,
    JobORM,
    UserFilterORM,
    UserORM,
)
from src.repositories.statistics import StatisticsRepository
from src.services.collection import CollectionService
from src.services.entitlements import EntitlementService
from src.services.jobs import JobSaveService
from src.services.normalization import NormalizationService
from src.services.statistics import StatisticsService
from src.services.user_filters import UserFilterService

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "existing_source",
    [
        "remoteok",
        "weworkremotely",
        "getonboard",
        "himalayas",
        "jobicy",
        "the_muse",
        "hacker_news",
    ],
)
async def test_cross_source_repeat_collection_state_and_statistics(pg, existing_source):
    raw = json.loads(
        (Path(__file__).parents[1] / "fixtures/jooble/jobs.json").read_text()
    )["jobs"][0]
    job = NormalizationService().normalize(parse_job(raw))
    async with pg() as session:
        await JobSaveService(session).save_if_new(
            job.model_copy(
                update={"source": existing_source, "external_id": "original"}
            )
        )

    class Collector(BaseJobCollector):
        source_name = "jooble"

        async def collect(self):
            return [
                job,
                job.model_copy(
                    update={
                        "external_id": "999000002",
                        "title": "Another Platform Role",
                        "url": "https://uk.jooble.org/jdp/999000002",
                    }
                ),
            ]

    redis = Mock()
    redis.lock.return_value.acquire = AsyncMock(return_value=True)
    redis.lock.return_value.release = AsyncMock()
    now = datetime.now(UTC)
    service = CollectionService(pg, redis, "America/Montevideo", clock=lambda: now)
    assert await service.collect("jooble", collector=Collector()) == {
        "received": 2,
        "new": 1,
        "duplicates": 1,
        "cross_source_duplicates": 1,
        "failed": 0,
    }
    repeated = await service.collect("jooble", collector=Collector())
    assert repeated["new"] == 0 and repeated["duplicates"] == 2
    async with pg() as session:
        rows = list(await session.scalars(select(JobORM)))
        assert len(rows) == 2 and {row.source for row in rows} == {
            existing_source,
            "jooble",
        }
        state = await session.scalar(
            select(CollectorStateORM).where(CollectorStateORM.source == "jooble")
        )
        assert (
            state.last_status == "success"
            and state.last_success_at
            and state.next_run_at
        )
        runs = list(await session.scalars(select(CollectorRunORM)))
        assert len(runs) == 2 and all(run.status == "success" for run in runs)
        assert sum(run.cross_source_duplicate_count for run in runs) == 2
        assert all(run.failed_count == 0 and run.duration_ms >= 0 for run in runs)
        stats = await StatisticsService(
            StatisticsRepository(session),
            EntitlementService(),
            clock=lambda: now + timedelta(seconds=1),
        ).get_stats()
        source = next(item for item in stats.collectors if item.source == "jooble")
        assert source.runs == 2 and source.new_count == 1
        assert source.cross_source_duplicate_count == 2
    assert redis.lock.call_args.args == ("collector:jooble:lock",)


def migrate(connection, revision, *, downgrade=False):
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    config.attributes["connection"] = connection
    (command.downgrade if downgrade else command.upgrade)(config, revision)
    if not downgrade:
        command.check(config)


async def test_data_migration_preserves_selections_other_preferences_and_new_defaults(
    pg,
):
    old_sources = [
        "remoteok",
        "getonboard",
        "weworkremotely",
        "himalayas",
        "jobicy",
        "the_muse",
        "hacker_news",
    ]
    async with pg() as session:
        connection = await session.connection()
        await connection.run_sync(lambda c: migrate(c, "d749a8b3e205", downgrade=True))
        for index, sources in enumerate([old_sources, ["jobicy"], ["jooble"]]):
            user = UserORM(telegram_id=1001 + index, language="es")
            session.add(user)
            await session.flush()
            await session.execute(
                text(
                    "INSERT INTO user_filters (user_id, sources, min_salary, keywords) "
                    "VALUES (:id, CAST(:sources AS varchar[]), 2500, '{backend}')"
                ),
                {"id": user.id, "sources": sources},
            )
        await session.commit()
    async with pg() as session:
        connection = await session.connection()
        await connection.run_sync(lambda c: migrate(c, "head"))
        await session.commit()
        rows = list(
            await session.scalars(select(UserFilterORM).order_by(UserFilterORM.user_id))
        )
        assert [row.sources for row in rows] == [
            old_sources + ["jooble"],
            ["jobicy", "jooble"],
            ["jooble"],
        ]
        assert all(
            row.min_salary == 2500 and row.keywords == ["backend"] for row in rows
        )
        assert all(
            user.language == "es" for user in await session.scalars(select(UserORM))
        )
        fresh = UserORM(telegram_id=1004)
        session.add(fresh)
        await session.commit()
        assert set(
            (await UserFilterService(session).get_filters(fresh.id)).sources
        ) == set(old_sources + ["jooble"])


async def test_downgrade_refuses_to_empty_jooble_only_selection(pg):
    async with pg() as session:
        user = UserORM(telegram_id=1001)
        session.add(user)
        await session.flush()
        session.add(UserFilterORM(user_id=user.id, sources=["jooble"]))
        await session.commit()
        connection = await session.connection()
        with pytest.raises(RuntimeError, match="Jooble-only"):
            await connection.run_sync(
                lambda c: migrate(c, "d749a8b3e205", downgrade=True)
            )
        await session.rollback()


async def test_missing_key_records_failed_configuration_without_blocking_other_sources(
    pg, monkeypatch
):
    from src.config import settings

    monkeypatch.setattr(settings, "JOOBLE_API_KEY", None)
    redis = Mock()
    redis.lock.return_value.acquire = AsyncMock(return_value=True)
    redis.lock.return_value.release = AsyncMock()
    service = CollectionService(pg, redis, "America/Montevideo")
    failed = await service.collect("jooble")
    assert failed == {"status": "failed", "error": "CollectorConfigurationError"}
    raw = json.loads(
        (Path(__file__).parents[1] / "fixtures/jooble/jobs.json").read_text()
    )["jobs"][0]

    class OtherCollector(BaseJobCollector):
        source_name = "remoteok"

        async def collect(self):
            return [parse_job(raw).model_copy(update={"source": "remoteok"})]

    assert (await service.collect("remoteok", collector=OtherCollector()))["new"] == 1
    async with pg() as session:
        state = await session.scalar(
            select(CollectorStateORM).where(CollectorStateORM.source == "jooble")
        )
        run = await session.scalar(
            select(CollectorRunORM).where(CollectorRunORM.source == "jooble")
        )
        assert (
            state.last_status == "failed"
            and state.last_error == "CollectorConfigurationError"
        )
        assert run.status == "failed" and run.received_count == 0
        assert run.error == "CollectorConfigurationError" and state.next_run_at


async def test_multi_query_effectiveness_through_actual_collector_and_global_dedup(
    pg, monkeypatch
):
    import httpx

    from src.collectors.jooble import JoobleCollector
    from src.config import settings

    monkeypatch.setattr(settings, "JOOBLE_API_KEY", "test-private-key")
    monkeypatch.setattr(settings, "JOOBLE_API_DOMAIN", "uk.jooble.org")
    monkeypatch.setattr(settings, "JOOBLE_SEARCH_LOCATION", "United Kingdom")
    raw = json.loads(
        (Path(__file__).parents[1] / "fixtures/jooble/jobs.json").read_text()
    )["jobs"][0]
    async with pg() as session:
        await JobSaveService(session).save_if_new(
            parse_job(raw).model_copy(update={"source": "remoteok"})
        )

    def respond(request):
        query = json.loads(request.content)["keywords"]
        identity = 124 if query == "software" else 125
        item = dict(
            raw,
            id=identity,
            title=f"Role {identity}",
            link=f"https://uk.jooble.org/jdp/{identity}",
        )
        return httpx.Response(200, json={"totalCount": 2, "jobs": [raw, item]})

    client_type = httpx.AsyncClient
    monkeypatch.setattr(
        "src.collectors.jooble.httpx.AsyncClient",
        lambda **kw: client_type(transport=httpx.MockTransport(respond), **kw),
    )

    async def sleep(_):
        pass

    monkeypatch.setattr("src.collectors.jooble.asyncio.sleep", sleep)
    redis = Mock()
    redis.lock.return_value.acquire = AsyncMock(return_value=True)
    redis.lock.return_value.release = AsyncMock()
    collector = JoobleCollector()
    result = await CollectionService(pg, redis, "America/Montevideo").collect(
        "jooble", collector=collector
    )
    assert result == {
        "received": 3,
        "new": 2,
        "duplicates": 1,
        "cross_source_duplicates": 1,
        "failed": 0,
    }
    async with pg() as session:
        new_ids = set(
            await session.scalars(
                select(JobORM.external_id).where(JobORM.source == "jooble")
            )
        )
    per_query_new = {
        query: len(new_ids.intersection(ids))
        for query, ids in collector.query_job_ids.items()
    }
    assert per_query_new == {"software": 1, "developer": 1}
    assert collector.last_report["api_results_received"] == 4
    assert collector.last_report["unique_jobs"] == 3
