import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text

from src.collectors.base import BaseJobCollector
from src.collectors.the_muse import parse_job
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
    ["remoteok", "weworkremotely", "getonboard", "himalayas", "jobicy"],
)
async def test_cross_source_repeat_collection_state_and_statistics(pg, existing_source):
    raw = json.loads(
        (Path(__file__).parents[1] / "fixtures/the_muse/jobs.json").read_text()
    )["results"][0]
    job = NormalizationService().normalize(parse_job(raw))
    async with pg() as session:
        await JobSaveService(session).save_if_new(
            job.model_copy(
                update={"source": existing_source, "external_id": "original"}
            )
        )

    class Collector(BaseJobCollector):
        source_name = "the_muse"

        async def collect(self):
            return [
                job,
                job.model_copy(
                    update={
                        "external_id": "999000002",
                        "title": "Another Platform Role",
                        "url": "https://www.themuse.com/jobs/example/another-role",
                    }
                ),
            ]

    redis = Mock()
    redis.lock.return_value.acquire = AsyncMock(return_value=True)
    redis.lock.return_value.release = AsyncMock()
    now = datetime.now(UTC)
    service = CollectionService(pg, redis, "America/Montevideo", clock=lambda: now)
    assert await service.collect("the_muse", collector=Collector()) == {
        "received": 2,
        "new": 1,
        "duplicates": 1,
        "cross_source_duplicates": 1,
        "failed": 0,
    }
    repeated = await service.collect("the_muse", collector=Collector())
    assert repeated["new"] == 0 and repeated["duplicates"] == 2
    async with pg() as session:
        rows = list(await session.scalars(select(JobORM)))
        assert len(rows) == 2 and {row.source for row in rows} == {
            existing_source,
            "the_muse",
        }
        state = await session.scalar(
            select(CollectorStateORM).where(CollectorStateORM.source == "the_muse")
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
        source = next(item for item in stats.collectors if item.source == "the_muse")
        assert source.runs == 2 and source.new_count == 1
        assert source.cross_source_duplicate_count == 2
    assert redis.lock.call_args.args == ("collector:the_muse:lock",)


def migrate(connection, revision, *, downgrade=False):
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    config.attributes["connection"] = connection
    (command.downgrade if downgrade else command.upgrade)(config, revision)
    if not downgrade:
        command.check(config)


async def test_data_migration_preserves_selections_other_preferences_and_new_defaults(
    pg,
):
    old_sources = ["remoteok", "getonboard", "weworkremotely", "himalayas", "jobicy"]
    async with pg() as session:
        connection = await session.connection()
        await connection.run_sync(lambda c: migrate(c, "b927c64ed108", downgrade=True))
        for index, sources in enumerate([old_sources, ["jobicy"], ["the_muse"]]):
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
            old_sources + ["the_muse", "hacker_news", "jooble"],
            ["jobicy", "the_muse", "hacker_news", "jooble"],
            ["the_muse", "hacker_news", "jooble"],
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
        ) == set(old_sources + ["the_muse", "hacker_news", "jooble"])


async def test_downgrade_refuses_to_empty_the_muse_only_selection(pg):
    async with pg() as session:
        user = UserORM(telegram_id=1001)
        session.add(user)
        await session.flush()
        session.add(UserFilterORM(user_id=user.id, sources=["the_muse"]))
        await session.commit()
        connection = await session.connection()
        with pytest.raises(RuntimeError, match="The Muse-only"):
            await connection.run_sync(
                lambda c: migrate(c, "b927c64ed108", downgrade=True)
            )
        await session.rollback()
