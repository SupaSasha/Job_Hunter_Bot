import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from src.models import DigestRunORM, JobORM, NotificationORM, UserORM
from src.repositories.digests import DigestRepository
from src.repositories.jobs import JobRepository
from src.repositories.notifications import NotificationRepository
from src.schemas.job import JobDTO
from src.schemas.scoring import ScoreResult
from src.services.jobs import JobSaveService, job_to_orm
from src.services.notifications import NotificationService

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)


def job(number=1, **values):
    return JobDTO(
        source="remoteok",
        external_id=str(number),
        title="Python developer",
        company="Acme",
        url=f"https://example.com/{number}",
        collected_at=NOW,
        **values,
    )


async def seed(pg):
    async with pg() as session:
        user = UserORM(telegram_id=123, is_active=True)
        row = job_to_orm(job(), "fingerprint")
        session.add_all([user, row])
        await session.commit()
        return user, row


async def test_source_external_id_uniqueness(pg):
    await seed(pg)
    async with pg() as session:
        session.add(job_to_orm(job(), "different"))
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()
        assert await session.scalar(select(func.count()).select_from(JobORM)) == 1


async def test_notification_uniqueness(pg):
    user, row = await seed(pg)
    async with pg() as session:
        session.add(
            NotificationORM(
                user_id=user.id, job_id=row.id, score=70, status="retryable"
            )
        )
        await session.commit()
        session.add(
            NotificationORM(user_id=user.id, job_id=row.id, score=70, status="pending")
        )
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_fingerprint_window_and_missing_company(pg):
    async with pg() as session:
        recent = job_to_orm(job(), "recent")
        old = job_to_orm(
            job(2).model_copy(update={"collected_at": NOW - timedelta(days=60)}), "old"
        )
        session.add_all([recent, old])
        await session.commit()
        repo = JobRepository(session)
        assert (
            await repo.get_by_fingerprint("recent", since=NOW - timedelta(days=30))
            is recent
        )
        assert (
            await repo.get_by_fingerprint("old", since=NOW - timedelta(days=30)) is None
        )
    async with pg() as session:
        save = JobSaveService(session)
        first = job(3).model_copy(update={"company": None})
        second = first.model_copy(update={"source": "getonboard"})
        assert (await save.save_if_new(first)).status == "saved"
        assert (await save.save_if_new(second)).status == "saved"
        assert (await save.save_if_new(first)).status == "duplicate"


@pytest.mark.parametrize(
    "status,eligible",
    [
        (None, True),
        ("retryable", True),
        ("sent", False),
        ("unknown", False),
        ("pending", False),
        ("failed", False),
    ],
)
async def test_candidate_statuses_and_age(pg, status, eligible):
    user, row = await seed(pg)
    async with pg() as session:
        session.add(
            job_to_orm(
                job(2).model_copy(update={"collected_at": NOW - timedelta(days=8)}),
                "old",
            )
        )
        if status:
            session.add(
                NotificationORM(user_id=user.id, job_id=row.id, score=70, status=status)
            )
        await session.commit()
    candidates = await DigestRepository(pg).candidates(user.id, now=NOW)
    assert [i for i, _ in candidates] == ([row.id] if eligible else [])


async def test_candidate_limit_order_and_retry_cooldown(pg, monkeypatch):
    from src.config import settings

    monkeypatch.setattr(settings, "DIGEST_CANDIDATE_LIMIT", 1)
    user, row = await seed(pg)
    async with pg() as session:
        session.add(
            NotificationORM(
                user_id=user.id,
                job_id=row.id,
                score=70,
                status="retryable",
                retry_after_until=NOW + timedelta(minutes=1),
            )
        )
        newer = job_to_orm(
            job(2).model_copy(update={"collected_at": NOW - timedelta(hours=1)}),
            "newer",
        )
        older = job_to_orm(
            job(3).model_copy(update={"collected_at": NOW - timedelta(hours=2)}),
            "older",
        )
        session.add_all([newer, older])
        await session.commit()
    repo = DigestRepository(pg)
    assert [i for i, _ in await repo.candidates(user.id, now=NOW)] == [newer.id]
    assert [
        i for i, _ in await repo.candidates(user.id, now=NOW + timedelta(minutes=2))
    ] == [row.id]


async def test_atomic_retry_claim_only_one_sender(pg):
    user, row = await seed(pg)
    async with pg() as session:
        notification = NotificationORM(
            user_id=user.id, job_id=row.id, score=70, status="retryable"
        )
        session.add(notification)
        await session.commit()
        notification_id = notification.id

    async def claim():
        async with pg() as session:
            result = await NotificationRepository(session).claim_retryable(
                notification_id, NOW
            )
            await session.commit()
            return result

    results = await asyncio.gather(claim(), claim())
    assert sum(result is not None for result in results) == 1


async def test_digest_reservation_race_stale_recovery_preserves_history(pg):
    user, _ = await seed(pg)
    repo = DigestRepository(pg)
    results = await asyncio.gather(
        repo.reserve(user.id, NOW.date(), NOW), repo.reserve(user.id, NOW.date(), NOW)
    )
    assert sum(result is not None for result in results) == 1
    old_id = next(result for result in results if result is not None)
    assert await repo.attempted(user.id, NOW.date())
    await repo.recover_stale(NOW + timedelta(minutes=10))
    assert await repo.reserve(user.id, NOW.date(), NOW + timedelta(minutes=10)) is None
    later = NOW + timedelta(minutes=31)
    results = await asyncio.gather(
        repo.reserve(user.id, NOW.date(), later),
        repo.reserve(user.id, NOW.date(), later),
    )
    assert sum(result is not None for result in results) == 1
    await repo.update(old_id, status="sent")
    async with pg() as session:
        rows = list(
            await session.scalars(select(DigestRunORM).order_by(DigestRunORM.id))
        )
        assert len(rows) == 2
        assert rows[0].status == "abandoned"
        assert rows[1].status == "pending"


async def test_postgresql_arrays_and_updated_status_constraints(pg):
    user, row = await seed(pg)
    async with pg() as session:
        row = await session.get(JobORM, row.id)
        row.technologies = ["python", "fastapi"]
        session.add(
            NotificationORM(user_id=user.id, job_id=row.id, score=80, status="unknown")
        )
        await session.commit()
        assert (
            await session.scalar(
                select(func.cardinality(JobORM.technologies)).where(
                    JobORM.technologies.any("python")
                )
            )
            == 2
        )
        assert (
            await session.scalar(text("SELECT version_num FROM alembic_version"))
            == "49f75b591334"
        )


async def test_end_to_end_rejected_notification_is_retryable_then_sent(pg):
    from src.bot.client import TelegramAPIError

    user, row = await seed(pg)
    client = AsyncMock()
    client.send_message.side_effect = [TelegramAPIError("Rejected", retryable=True), 42]
    async with pg() as session:
        service = NotificationService(session, client)
        assert not (
            await service.notify(
                user=user, job_id=row.id, job=job(), score=ScoreResult(score=70)
            )
        ).sent
    assert [i for i, _ in await DigestRepository(pg).candidates(user.id, now=NOW)] == [
        row.id
    ]
    async with pg() as session:
        result = await NotificationService(session, client).notify(
            user=user, job_id=row.id, job=job(), score=ScoreResult(score=70)
        )
        assert result.sent
    assert await DigestRepository(pg).candidates(user.id, now=NOW) == []
    assert client.send_message.await_count == 2
