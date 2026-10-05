import asyncio
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text

from src.bot.client import TelegramClient
from src.models import (
    DigestRunORM,
    NotificationORM,
    UserNotificationSettingsORM,
    UserORM,
)
from src.repositories.digests import DigestRepository
from src.schemas.job import JobDTO
from src.services.digests import DailyDigestService
from src.services.entitlements import EntitlementService
from src.services.jobs import job_to_orm

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 5, 12, tzinfo=UTC)


async def seed(pg):
    async with pg() as session:
        user = UserORM(telegram_id=1001, language="es")
        session.add(user)
        await session.flush()
        session.add(
            UserNotificationSettingsORM(
                user_id=user.id, timezone="UTC", digest_time=time(9), min_score=0
            )
        )
        await session.commit()
        return user.id


@pytest.mark.parametrize("status", ["sent", "empty", "partial", "failed"])
async def test_manual_reservation_after_completed_daily_run_preserves_history(
    pg, status
):
    user_id = await seed(pg)
    repository = DigestRepository(pg)
    daily_id = await repository.reserve(user_id, NOW.date(), NOW)
    await repository.update(
        daily_id, status=status, finished_at=NOW, selected=3, sent=1
    )
    first = await repository.reserve(user_id, NOW.date(), NOW, manual=True)
    assert first is not None and first != daily_id
    assert await repository.reserve(user_id, NOW.date(), NOW, manual=True) is None
    await repository.update(first, status="empty", finished_at=NOW)
    second = await repository.reserve(user_id, NOW.date(), NOW, manual=True)
    assert second is not None and second != first
    assert await repository.attempted(user_id, NOW.date())
    assert await repository.reserve(user_id, NOW.date(), NOW) is None
    async with pg() as session:
        original = await session.get(DigestRunORM, daily_id)
        assert not original.manual
        assert (original.status, original.selected, original.sent) == (status, 3, 1)
        assert await session.scalar(select(func.count()).select_from(DigestRunORM)) == 3


async def test_manual_runs_do_not_consume_schedule_and_concurrent_runs_are_serialized(
    pg,
):
    user_id = await seed(pg)
    repository = DigestRepository(pg)
    reservations = await asyncio.gather(
        *[repository.reserve(user_id, NOW.date(), NOW, manual=True) for _ in range(3)]
    )
    assert sum(run_id is not None for run_id in reservations) == 1
    assert not await repository.attempted(user_id, NOW.date())
    assert await repository.reserve(user_id, NOW.date(), NOW) is None
    manual_id = next(run_id for run_id in reservations if run_id is not None)
    await repository.update(manual_id, status="sent", finished_at=NOW)
    daily_id = await repository.reserve(user_id, NOW.date(), NOW)
    assert daily_id is not None
    assert await repository.reserve(user_id, NOW.date(), NOW, manual=True) is None
    await repository.update(daily_id, status="sent", finished_at=NOW)
    assert await repository.reserve(user_id, NOW.date(), NOW, manual=True) is not None


async def test_manual_digest_delivers_only_new_jobs_after_failed_daily_attempt(pg):
    user_id = await seed(pg)
    repository = DigestRepository(pg)
    daily_id = await repository.reserve(user_id, NOW.date(), NOW)
    await repository.update(daily_id, status="failed", finished_at=NOW)

    async def add_job(number):
        async with pg() as session:
            row = job_to_orm(
                JobDTO(
                    source="remoteok",
                    external_id=str(number),
                    title=f"Python Developer {number}",
                    url=f"https://example.com/{number}",
                    remote=True,
                    remote_regions=["worldwide"],
                    technologies=["python"],
                    collected_at=NOW,
                ),
                f"manual-{number}",
            )
            session.add(row)
            await session.commit()
            return row.id

    already_sent = await add_job(1)
    fresh = await add_job(2)
    async with pg() as session:
        session.add(
            NotificationORM(
                user_id=user_id, job_id=already_sent, status="sent", score=70
            )
        )
        await session.commit()
    client = AsyncMock(spec=TelegramClient)
    client.send_message.return_value = 42
    service = DailyDigestService(
        pg, client, EntitlementService(free_min_score=0), clock=lambda: NOW
    )
    assert (await service.send(user_id, run_now=True))["sent"] == 1
    assert "Python Developer 2" in client.send_message.call_args.args[1]
    assert (await service.send(user_id, run_now=True))["status"] == "empty"
    assert client.send_message.call_args.args[1] == (
        "No hay nuevas vacantes que coincidan con tus filtros."
    )
    latest = await add_job(3)
    assert (await service.send(user_id, run_now=True))["sent"] == 1
    assert "Python Developer 3" in client.send_message.call_args.args[1]
    assert client.send_message.await_count == 5
    assert (await service.send(user_id))["reason"] == "already_attempted_today"
    async with pg() as session:
        notifications = list(await session.scalars(select(NotificationORM)))
        assert {row.job_id for row in notifications} == {already_sent, fresh, latest}
        assert all(row.status == "sent" for row in notifications)
        original = await session.get(DigestRunORM, daily_id)
        assert original.status == "failed" and not original.manual


async def test_manual_digest_migration_preserves_existing_daily_runs(pg):
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    async with pg() as session:
        connection = await session.connection()

        def downgrade(connection):
            config.attributes["connection"] = connection
            command.downgrade(config, "e93b6472a105")

        await connection.run_sync(downgrade)
        user_id = await session.scalar(
            text("INSERT INTO users (telegram_id) VALUES (1001) RETURNING id")
        )
        run_id = await session.scalar(
            text(
                "INSERT INTO digest_runs (user_id, local_date, status, started_at, "
                "selected, sent, failed, skipped) "
                "VALUES (:user_id, :day, 'partial', :now, 3, 2, 1, 0) RETURNING id"
            ),
            {"user_id": user_id, "day": NOW.date(), "now": NOW},
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
        run = await session.get(DigestRunORM, run_id)
        assert not run.manual
        assert (run.status, run.selected, run.sent, run.failed) == ("partial", 3, 2, 1)


async def test_manual_stale_recovery_preserves_original_reservation(pg):
    user_id = await seed(pg)
    repository = DigestRepository(pg)
    original = await repository.reserve(user_id, NOW.date(), NOW, manual=True)
    later = NOW + timedelta(hours=1)
    replacement = await repository.reserve(user_id, NOW.date(), later, manual=True)
    assert replacement is not None and replacement != original
    async with pg() as session:
        run = await session.get(DigestRunORM, original)
        assert run.status == "abandoned" and run.manual
        assert run.last_error == "StaleDigestReservation"
