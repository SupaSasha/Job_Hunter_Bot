import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text

from src.collectors.base import BaseJobCollector
from src.collectors.usajobs import USAJobsCollector, parse_job
from src.config import settings
from src.models import (
    CollectorRunORM,
    CollectorStateORM,
    JobORM,
    UserFilterORM,
    UserORM,
)
from src.models.user_filter import DEFAULT_SOURCES
from src.repositories.statistics import StatisticsRepository
from src.services.collection import CollectionService
from src.services.entitlements import EntitlementService
from src.services.jobs import JobSaveService
from src.services.normalization import NormalizationService
from src.services.statistics import StatisticsService
from src.services.user_filters import UserFilterService

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 16, 12, tzinfo=UTC)


def raw_job():
    return json.loads(
        (Path(__file__).parents[1] / "fixtures/usajobs/search.json").read_text()
    )["SearchResult"]["SearchResultItems"][0]


def redis_lock():
    redis = Mock()
    redis.lock.return_value.acquire = AsyncMock(return_value=True)
    redis.lock.return_value.release = AsyncMock()
    return redis


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
        "jooble",
    ],
)
async def test_cross_source_repeat_state_runs_and_stats(pg, existing_source):
    job = NormalizationService().normalize(parse_job(raw_job(), collected_at=NOW))
    async with pg() as session:
        await JobSaveService(session).save_if_new(
            job.model_copy(
                update={"source": existing_source, "external_id": "original"}
            )
        )

    class Collector(BaseJobCollector):
        source_name = "usajobs"

        async def collect(self):
            return [
                job,
                job.model_copy(
                    update={
                        "external_id": "800000099",
                        "title": "Different Technical Role",
                        "url": "https://www.usajobs.gov/job/800000099",
                    }
                ),
            ]

    redis = redis_lock()
    service = CollectionService(pg, redis, "America/Montevideo", clock=lambda: NOW)
    assert await service.collect("usajobs", collector=Collector()) == {
        "received": 2,
        "new": 1,
        "duplicates": 1,
        "cross_source_duplicates": 1,
        "failed": 0,
    }
    repeated = await service.collect("usajobs", collector=Collector())
    assert repeated["new"] == 0 and repeated["duplicates"] == 2
    async with pg() as session:
        rows = list(await session.scalars(select(JobORM)))
        assert len(rows) == 2 and {row.source for row in rows} == {
            existing_source,
            "usajobs",
        }
        state = await session.scalar(
            select(CollectorStateORM).where(CollectorStateORM.source == "usajobs")
        )
        assert (
            state.last_status == "success"
            and state.last_success_at == NOW
            and state.next_run_at > NOW
        )
        runs = list(await session.scalars(select(CollectorRunORM)))
        assert len(runs) == 2 and all(run.status == "success" for run in runs)
        assert all(run.failed_count == 0 and run.duration_ms >= 0 for run in runs)
        stats = await StatisticsService(
            StatisticsRepository(session),
            EntitlementService(),
            clock=lambda: NOW + timedelta(seconds=1),
        ).get_stats()
        source = next(row for row in stats.collectors if row.source == "usajobs")
        assert (
            source.runs == 2
            and source.new_count == 1
            and source.cross_source_duplicate_count == 2
        )
    redis.lock.assert_called_with(
        "collector:usajobs:lock", timeout=660, blocking=False, thread_local=False
    )


async def test_defaults_off_existing_preserved_opt_in_and_schema_parity(
    pg,
):
    async with pg() as session:
        old = UserORM(telegram_id=7001, language="es")
        fresh = UserORM(telegram_id=7002)
        bootstrap = UserORM(telegram_id=7003)
        session.add_all([old, fresh, bootstrap])
        await session.flush()
        session.add(
            UserFilterORM(
                user_id=old.id, sources=["jooble"], keywords=["custom"], min_salary=2500
            )
        )
        await session.execute(
            text("INSERT INTO user_filters (user_id) VALUES (:id)"), {"id": fresh.id}
        )
        await session.commit()
        service = UserFilterService(session, owner_telegram_id=None)
        existing = await service.get_filters(old.id)
        assert (
            existing.sources == ["jooble"]
            and existing.keywords == ["custom"]
            and existing.min_salary == 2500
        )
        assert "usajobs" not in (await service.get_filters(fresh.id)).sources
        assert (await service.get_filters(bootstrap.id)).sources == list(
            DEFAULT_SOURCES
        )
        enabled = await service.toggle(old.id, "sources", "usajobs")
        assert enabled.sources == ["jooble", "usajobs"] and enabled.exclude_us_only
        await session.refresh(old)
        assert old.language == "es"
        connection = await session.connection()
        config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))

        def check(sync_connection):
            config.attributes["connection"] = sync_connection
            command.check(config)

        await connection.run_sync(check)


async def test_missing_credentials_failed_configuration_does_not_block_other_source(
    pg, monkeypatch
):
    monkeypatch.setattr(settings, "USAJOBS_API_KEY", None)
    service = CollectionService(pg, redis_lock(), "America/Montevideo")
    assert await service.collect("usajobs") == {
        "status": "failed",
        "error": "CollectorConfigurationError",
    }

    class OtherCollector(BaseJobCollector):
        source_name = "jooble"

        async def collect(self):
            return [parse_job(raw_job()).model_copy(update={"source": "jooble"})]

    assert (await service.collect("jooble", collector=OtherCollector()))["new"] == 1
    async with pg() as session:
        state = await session.scalar(
            select(CollectorStateORM).where(CollectorStateORM.source == "usajobs")
        )
        run = await session.scalar(
            select(CollectorRunORM).where(CollectorRunORM.source == "usajobs")
        )
        assert state.last_status == run.status == "failed"
        assert state.last_error == run.error == "CollectorConfigurationError"
        assert state.last_success_at is None and run.received_count == 0


async def test_real_collector_mock_http_common_pipeline_and_query_audit(
    pg, monkeypatch
):
    monkeypatch.setattr(settings, "USAJOBS_API_KEY", "test-private-key")
    monkeypatch.setattr(settings, "USAJOBS_EMAIL", "test@example.com")
    raw = raw_job()
    async with pg() as session:
        await JobSaveService(session).save_if_new(
            parse_job(raw).model_copy(update={"source": "jooble"})
        )
    real = httpx.AsyncClient

    def handler(request):
        row = copy.deepcopy(raw)
        if request.url.params["Page"] == "2":
            row["MatchedObjectId"] = "800000100"
            row["MatchedObjectDescriptor"].update(
                PositionTitle="Another IT Role",
                PositionURI="https://www.usajobs.gov/job/800000100",
            )
        return httpx.Response(
            200,
            json={
                "SearchResult": {
                    "SearchResultCount": 1,
                    "SearchResultCountAll": 2,
                    "SearchResultItems": [row],
                }
            },
        )

    monkeypatch.setattr(
        "src.collectors.usajobs.httpx.AsyncClient",
        lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs),
    )
    monkeypatch.setattr("src.collectors.usajobs.asyncio.sleep", AsyncMock())
    collector = USAJobsCollector()
    collector.page_size = 1
    result = await CollectionService(pg, redis_lock(), "America/Montevideo").collect(
        "usajobs", collector=collector
    )
    assert result == {
        "received": 2,
        "new": 1,
        "duplicates": 1,
        "cross_source_duplicates": 1,
        "failed": 0,
    }
    assert (
        collector.last_report["api_results_received"]
        == collector.last_report["unique_jobs"]
        == 2
    )
    assert collector.query_job_ids == {"2210": ["800000001", "800000100"]}
