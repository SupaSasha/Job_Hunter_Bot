import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from src.models.feedback import FeedbackORM
from src.models.job import JobORM
from src.models.notification import NotificationORM
from src.models.user import UserORM
from src.schemas.filters import UserFilterDTO
from src.schemas.job import JobDTO
from src.services.filters import FilterService
from src.services.jobs import JobSaveService

pytestmark = pytest.mark.integration


def vacancy(**updates):
    values = dict(
        source="remoteok",
        external_id="original",
        title="Sales Manager",
        company="Review Fixture",
        url="https://example.com/original",
        remote=True,
        remote_regions=["worldwide"],
        collected_at=datetime.now(UTC),
    )
    values.update(updates)
    return JobDTO(**values)


async def test_cross_source_dedup_preserves_source_filters_and_concurrent_discoveries(
    pg,
):
    async def save(job):
        async with pg() as session:
            return await JobSaveService(session).save_if_new(job)

    original = vacancy()
    first = await save(original)
    jooble = original.model_copy(update={"source": "jooble", "external_id": "second"})
    jobicy = original.model_copy(update={"source": "jobicy", "external_id": "third"})
    results = await asyncio.gather(save(jooble), save(jobicy))
    repeated = await save(jooble)

    assert all(result.job_id == first.job_id for result in [*results, repeated])
    assert all(result.status == "duplicate" for result in [*results, repeated])
    async with pg() as session:
        assert await session.scalar(select(func.count()).select_from(JobORM)) == 1
        row = await session.get(JobORM, first.job_id)
        assert sorted(row.additional_sources) == ["jobicy", "jooble"]
        job = JobDTO.model_validate(row, from_attributes=True)

    for source in ("remoteok", "jooble", "jobicy"):
        assert FilterService().evaluate(job, UserFilterDTO(sources=[source])).accepted
    assert (
        not FilterService().evaluate(job, UserFilterDTO(sources=["himalayas"])).accepted
    )


async def test_recollection_refreshes_details_without_resetting_history(pg):
    from src.collectors.remoteok import RemoteOKCollector
    from src.services.deduplication import DeduplicationService

    original = vacancy(
        remote=False,
        location="Remote",
        description="Old description",
        salary_min=1000,
        collected_at=datetime.now(UTC) - timedelta(days=8),
    )
    async with pg() as session:
        result = await JobSaveService(session).save_if_new(original)
        job_id = result.job_id
        user = UserORM(telegram_id=123456)
        session.add(user)
        await session.flush()
        session.add_all(
            [
                NotificationORM(
                    user_id=user.id,
                    job_id=job_id,
                    score=70,
                    status="sent",
                    telegram_message_id=42,
                ),
                FeedbackORM(user_id=user.id, job_id=job_id, feedback_type="saved"),
            ]
        )
        await session.commit()
        await JobSaveService(session).save_if_new(
            original.model_copy(update={"source": "jooble", "external_id": "alias"})
        )

    fresh = RemoteOKCollector.map_job(
        {
            "id": original.external_id,
            "position": "Updated Sales Manager",
            "company": original.company,
            "url": "https://example.com/updated",
            "location": "Remote",
            "description": "Updated description",
            "salary_min": 3000,
            "tags": ["salesforce"],
        }
    )
    async with pg() as session:
        result = await JobSaveService(session).save_if_new(fresh)
        assert result.status == "duplicate" and result.job_id == job_id

    async with pg() as session:
        row = await session.get(JobORM, job_id)
        assert row.description == "Updated description" and row.salary_min == 3000
        assert row.title == fresh.title and row.url == fresh.url
        assert row.remote is True and row.technologies == ["salesforce"]
        assert row.fingerprint == DeduplicationService.calculate_fingerprint(fresh)
        assert row.collected_at == original.collected_at
        assert row.source == original.source and row.external_id == original.external_id
        assert row.additional_sources == ["jooble"]
        assert await session.scalar(select(func.count()).select_from(JobORM)) == 1
        notification = await session.scalar(select(NotificationORM))
        assert notification.job_id == job_id and notification.status == "sent"
        assert notification.telegram_message_id == 42
        feedback = await session.scalar(select(FeedbackORM))
        assert feedback.job_id == job_id and feedback.feedback_type == "saved"
