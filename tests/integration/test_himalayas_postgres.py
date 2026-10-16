import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text

from src.collectors.base import BaseJobCollector
from src.collectors.himalayas import parse_job
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


def fixture_job():
    raw = json.loads(
        (Path(__file__).parents[1] / "fixtures/himalayas/jobs.json").read_text()
    )[0]
    return NormalizationService().normalize(parse_job(raw))


@pytest.mark.parametrize(
    "existing_source", ["remoteok", "weworkremotely", "getonboard"]
)
async def test_cross_source_dedup_preserves_original_and_records_himalayas_run(
    pg, existing_source
):
    job = fixture_job()
    async with pg() as session:
        await JobSaveService(session).save_if_new(
            job.model_copy(
                update={"source": existing_source, "external_id": "original"}
            )
        )

    class Collector(BaseJobCollector):
        source_name = "himalayas"

        async def collect(self):
            return [
                job,
                job.model_copy(
                    update={"external_id": "fresh", "title": "Another Backend Engineer"}
                ),
            ]

    redis = Mock()
    redis.lock.return_value.acquire = AsyncMock(return_value=True)
    redis.lock.return_value.release = AsyncMock()
    service = CollectionService(pg, redis, "America/Montevideo")
    result = await service.collect("himalayas", collector=Collector())
    assert result == {
        "received": 2,
        "new": 1,
        "duplicates": 1,
        "cross_source_duplicates": 1,
        "failed": 0,
    }
    repeated = await service.collect("himalayas", collector=Collector())
    assert repeated["new"] == 0 and repeated["duplicates"] == 2
    async with pg() as session:
        jobs = list(await session.scalars(select(JobORM)))
        assert len(jobs) == 2 and {row.source for row in jobs} == {
            existing_source,
            "himalayas",
        }
        state = await session.scalar(
            select(CollectorStateORM).where(CollectorStateORM.source == "himalayas")
        )
        assert (
            state.last_status == "success"
            and state.last_success_at
            and state.next_run_at
        )
        runs = list(
            await session.scalars(select(CollectorRunORM).order_by(CollectorRunORM.id))
        )
        assert len(runs) == 2 and all(row.source == "himalayas" for row in runs)
        stats = await StatisticsService(
            StatisticsRepository(session), EntitlementService()
        ).get_stats()
        himalayas = next(row for row in stats.collectors if row.source == "himalayas")
        assert himalayas.runs == 2 and himalayas.new_count == 1
        assert himalayas.cross_source_duplicate_count == 2
    assert redis.lock.call_args.args == ("collector:himalayas:lock",)


async def test_migration_adds_new_source_without_reenabling_old_disabled_sources(pg):
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    async with pg() as session:
        connection = await session.connection()

        def downgrade(connection):
            config.attributes["connection"] = connection
            command.downgrade(config, "f72c4ea83910")

        await connection.run_sync(downgrade)
        ids = []
        for index, sources in enumerate(
            (["remoteok", "weworkremotely", "getonboard"], ["remoteok"])
        ):
            user = UserORM(telegram_id=1001 + index, language="es")
            session.add(user)
            await session.flush()
            ids.append(user.id)
            await session.execute(
                text(
                    "INSERT INTO user_filters (user_id, sources, min_salary) "
                    "VALUES (:id, CAST(:sources AS varchar[]), 2500)"
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
            "jooble",
        ]
        assert rows[1].sources == [
            "remoteok",
            "himalayas",
            "jobicy",
            "the_muse",
            "hacker_news",
            "jooble",
        ]
        assert all(row.min_salary == 2500 for row in rows)
        assert (await session.get(UserORM, ids[0])).language == "es"
        fresh = UserORM(telegram_id=1003)
        session.add(fresh)
        await session.commit()
        assert (
            "himalayas"
            in (await UserFilterService(session).get_filters(fresh.id)).sources
        )


async def test_himalayas_only_profile_prevents_lossy_downgrade(pg):
    async with pg() as session:
        user = UserORM(telegram_id=1001)
        session.add(user)
        await session.flush()
        session.add(UserFilterORM(user_id=user.id, sources=["himalayas"]))
        await session.commit()
        connection = await session.connection()

        def downgrade(connection):
            config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
            config.attributes["connection"] = connection
            command.downgrade(config, "f72c4ea83910")

        with pytest.raises(RuntimeError, match="Himalayas-only"):
            await connection.run_sync(downgrade)
        await session.rollback()
