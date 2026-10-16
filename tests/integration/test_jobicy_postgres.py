import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text

from src.collectors.base import BaseJobCollector
from src.collectors.jobicy import parse_job
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
    "existing_source", ["remoteok", "weworkremotely", "getonboard", "himalayas"]
)
async def test_jobicy_cross_source_dedup_state_statistics_and_persisted_cooldown(
    pg, existing_source
):
    raw = json.loads(
        (Path(__file__).parents[1] / "fixtures/jobicy/jobs.json").read_text()
    )["jobs"][0]
    job = NormalizationService().normalize(parse_job(raw))
    async with pg() as session:
        await JobSaveService(session).save_if_new(
            job.model_copy(
                update={"source": existing_source, "external_id": "original"}
            )
        )

    class Collector(BaseJobCollector):
        source_name = "jobicy"

        async def collect(self):
            return [
                job,
                job.model_copy(
                    update={
                        "external_id": "999999",
                        "title": "Another Security Engineer",
                        "url": "https://jobicy.com/jobs/999999-another-role",
                    }
                ),
            ]

    redis = Mock()
    redis.lock.return_value.acquire = AsyncMock(return_value=True)
    redis.lock.return_value.release = AsyncMock()
    clock = [datetime.now(UTC)]

    def service():
        return CollectionService(
            pg, redis, "America/Montevideo", clock=lambda: clock[0]
        )

    first = await service().collect("jobicy", collector=Collector())
    assert first == {
        "received": 2,
        "new": 1,
        "duplicates": 1,
        "cross_source_duplicates": 1,
        "failed": 0,
    }
    # A fresh service loads the committed start time; no in-memory limiter.
    assert await service().collect("jobicy", collector=Collector()) == {
        "status": "skipped",
        "reason": "cooldown",
    }
    clock[0] += timedelta(hours=1)
    repeated = await service().collect("jobicy", collector=Collector())
    assert repeated["new"] == 0 and repeated["duplicates"] == 2
    async with pg() as session:
        rows = list(await session.scalars(select(JobORM)))
        assert len(rows) == 2 and {row.source for row in rows} == {
            existing_source,
            "jobicy",
        }
        state = await session.scalar(
            select(CollectorStateORM).where(CollectorStateORM.source == "jobicy")
        )
        assert (
            state.last_status == "success"
            and state.last_success_at
            and state.next_run_at
        )
        runs = list(
            await session.scalars(select(CollectorRunORM).order_by(CollectorRunORM.id))
        )
        assert [run.status for run in runs] == ["success", "skipped", "success"]
        stats = await StatisticsService(
            StatisticsRepository(session),
            EntitlementService(),
            clock=lambda: clock[0] + timedelta(seconds=1),
        ).get_stats()
        source = next(item for item in stats.collectors if item.source == "jobicy")
        assert source.runs == 3 and source.skipped_runs == 1 and source.new_count == 1
        assert source.cross_source_duplicate_count == 2
    assert redis.lock.call_args.args == ("collector:jobicy:lock",)


async def test_migration_preserves_custom_sources_and_other_preferences(pg):
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    async with pg() as session:
        connection = await session.connection()

        def downgrade(connection):
            config.attributes["connection"] = connection
            command.downgrade(config, "a814d5c0732e")

        await connection.run_sync(downgrade)
        ids = []
        for index, sources in enumerate(
            (["remoteok", "weworkremotely", "getonboard", "himalayas"], ["himalayas"])
        ):
            user = UserORM(telegram_id=1001 + index, language="es")
            session.add(user)
            await session.flush()
            ids.append(user.id)
            await session.execute(
                text(
                    "INSERT INTO user_filters (user_id,sources,min_salary) "
                    "VALUES (:id,CAST(:sources AS varchar[]),2500)"
                ),
                {"id": user.id, "sources": sources},
            )
        await session.commit()
    async with pg() as session:
        connection = await session.connection()

        def upgrade(connection):
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            command.check(config)

        await connection.run_sync(upgrade)
        await session.commit()
        rows = list(
            await session.scalars(select(UserFilterORM).order_by(UserFilterORM.user_id))
        )
        assert rows[0].sources == [
            "remoteok",
            "weworkremotely",
            "getonboard",
            "himalayas",
            "jobicy",
            "the_muse",
            "hacker_news",
        ]
        assert rows[1].sources == ["himalayas", "jobicy", "the_muse", "hacker_news"]
        assert all(row.min_salary == 2500 for row in rows)
        assert (await session.get(UserORM, ids[0])).language == "es"
        fresh = UserORM(telegram_id=1003)
        session.add(fresh)
        await session.commit()
        sources = (await UserFilterService(session).get_filters(fresh.id)).sources
        assert set(sources) == {
            "remoteok",
            "weworkremotely",
            "getonboard",
            "himalayas",
            "jobicy",
            "the_muse",
            "hacker_news",
        }


async def test_downgrade_refuses_jobicy_only_filters(pg):
    async with pg() as session:
        user = UserORM(telegram_id=1001)
        session.add(user)
        await session.flush()
        session.add(UserFilterORM(user_id=user.id, sources=["jobicy"]))
        await session.commit()
        connection = await session.connection()

        def downgrade(connection):
            config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
            config.attributes["connection"] = connection
            command.downgrade(config, "a814d5c0732e")

        with pytest.raises(RuntimeError, match="Jobicy-only"):
            await connection.run_sync(downgrade)
        await session.rollback()
