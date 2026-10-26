from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.job import JobORM
from src.repositories.jobs import JobRepository
from src.schemas.job import JobDTO
from src.services.deduplication import DeduplicationService
from src.services.jobs import JobSaveService, job_to_orm


@pytest.fixture
def job() -> JobDTO:
    return JobDTO(
        source="remoteok",
        external_id="123",
        title="Python Developer",
        company="ACME Inc.",
        url="https://example.com/123",
        technologies=["python"],
        remote_regions=["worldwide"],
        published_at=datetime(2026, 9, 1, tzinfo=timezone(timedelta(hours=-3))),
    )


@pytest.fixture
def service() -> JobSaveService:
    service = JobSaveService(AsyncMock(spec=AsyncSession))
    repository = AsyncMock(spec=JobRepository)
    repository.get_by_source_external_id.return_value = None
    repository.get_by_fingerprint.return_value = None
    repository.add.return_value = JobORM(id=7)
    service.repository = repository
    service.deduplication = DeduplicationService(repository)
    return service


def make_integrity_error(
    constraint: str = "uq_jobs_source_external_id", sqlstate: str = "23505"
) -> IntegrityError:
    class DatabaseError(Exception):
        pass

    cause = DatabaseError()
    cause.constraint_name = constraint
    original = DatabaseError()
    original.sqlstate = sqlstate
    original.__cause__ = cause
    return IntegrityError("INSERT", {}, original)


def test_mapper_preserves_fields_and_utc(job: JobDTO) -> None:
    before = job.model_dump()
    orm = job_to_orm(job, DeduplicationService.calculate_fingerprint(job))
    for name, value in before.items():
        assert getattr(orm, name) == value
    assert orm.published_at.tzinfo == timezone.utc
    orm.technologies.append("docker")
    assert job.model_dump() == before


@pytest.mark.parametrize("field", ["published_at", "collected_at"])
def test_mapper_rejects_naive_timestamps(job: JobDTO, field: str) -> None:
    setattr(job, field, datetime(2026, 9, 1))
    with pytest.raises(ValueError, match=f"{field} must be timezone-aware"):
        job_to_orm(job, "a" * 64)


async def test_save_commits_new_job(service: JobSaveService, job: JobDTO) -> None:
    result = await service.save_if_new(job)
    assert result.status == "saved"
    assert result.job_id == 7
    persisted = service.repository.add.call_args.args[0]
    assert persisted.company == "ACME Inc."
    assert persisted.fingerprint == DeduplicationService.calculate_fingerprint(job)
    service.session.commit.assert_awaited_once()
    service.session.rollback.assert_not_awaited()


async def test_duplicate_does_not_insert(service: JobSaveService, job: JobDTO) -> None:
    service.repository.get_by_source_external_id.return_value = JobORM(id=8)
    result = await service.save_if_new(job)
    assert (result.status, result.job_id, result.reason) == (
        "duplicate",
        8,
        "source_external_id",
    )
    service.repository.add.assert_not_awaited()
    service.session.commit.assert_awaited_once()
    service.session.rollback.assert_not_awaited()


@pytest.mark.parametrize("boundary", ["add", "commit"])
async def test_concurrent_identity_conflict(
    service: JobSaveService, job: JobDTO, boundary: str
) -> None:
    service.repository.get_by_source_external_id.side_effect = [None, JobORM(id=9)]
    target = service.repository.add if boundary == "add" else service.session.commit
    target.side_effect = [make_integrity_error(), None]
    result = await service.save_if_new(job)
    assert (result.status, result.job_id, result.reason) == (
        "duplicate",
        9,
        "source_external_id",
    )
    assert service.session.rollback.await_count == 1


@pytest.mark.parametrize(
    ("constraint", "sqlstate"),
    [("other_unique", "23505"), ("uq_jobs_source_external_id", "23502")],
)
async def test_unrelated_integrity_error_is_not_hidden(
    service: JobSaveService, job: JobDTO, constraint: str, sqlstate: str
) -> None:
    error = make_integrity_error(constraint, sqlstate)
    service.repository.add.side_effect = error
    with pytest.raises(IntegrityError) as caught:
        await service.save_if_new(job)
    assert caught.value is error
    service.session.rollback.assert_awaited_once()
    assert service.repository.get_by_source_external_id.await_count == 1


async def test_missing_row_after_conflict_reraises(
    service: JobSaveService, job: JobDTO
) -> None:
    service.repository.add.side_effect = make_integrity_error()
    with pytest.raises(IntegrityError):
        await service.save_if_new(job)
    assert service.session.rollback.await_count == 2


async def test_commit_failure_rolls_back(service: JobSaveService, job: JobDTO) -> None:
    service.session.commit.side_effect = RuntimeError("connection lost")
    with pytest.raises(RuntimeError, match="connection lost"):
        await service.save_if_new(job)
    service.session.rollback.assert_awaited_once()
