from unittest.mock import AsyncMock

import pytest

from src.schemas.deduplication import JobSaveResult
from src.schemas.job import JobDTO
from src.services.jobs import JobSaveService
from src.services.pipeline import JobPipeline


def make_job(number: int = 1) -> JobDTO:
    return JobDTO(
        source="remoteok",
        external_id=str(number),
        title="  Python   Developer ",
        company="Acme",
        url=f"https://example.com/{number}",
        remote=True,
        technologies=["Python", "Fast API"],
        remote_regions=["Worldwide"],
    )


async def test_collection_normalizes_saves_and_counts_duplicates():
    save = AsyncMock(spec=JobSaveService)
    save.save_if_new.side_effect = [
        JobSaveResult(status="saved", job_id=7),
        JobSaveResult(status="duplicate", job_id=7),
    ]
    pipeline = JobPipeline(save)
    result = await pipeline.run([make_job(), make_job()])
    assert result.model_dump() == dict(
        received=2, new=1, duplicates=1, failed=0, cross_source_duplicates=0
    )
    job = save.save_if_new.call_args.args[0]
    assert job.title == "Python Developer"
    assert job.technologies == ["python", "fastapi"]
    assert job.remote_regions == ["worldwide"]


async def test_collection_stores_jobs_that_would_fail_delivery_filters():
    save = AsyncMock(spec=JobSaveService)
    save.save_if_new.return_value = JobSaveResult(status="saved", job_id=7)
    job = make_job().model_copy(update={"remote": False, "technologies": ["java"]})
    result = await JobPipeline(save).run([job])
    assert result.new == 1


async def test_database_error_is_not_reported_as_success():
    save = AsyncMock(spec=JobSaveService)
    save.save_if_new.side_effect = RuntimeError("database unavailable")
    with pytest.raises(RuntimeError):
        await JobPipeline(save).run([make_job()])


async def test_invalid_job_does_not_prevent_other_jobs_being_saved():
    save = AsyncMock(spec=JobSaveService)
    save.save_if_new.return_value = JobSaveResult(status="saved", job_id=7)
    pipeline = JobPipeline(save)
    from unittest.mock import Mock

    pipeline.normalizer = Mock()
    pipeline.normalizer.normalize.side_effect = [ValueError("bad input"), make_job()]
    result = await pipeline.run([make_job(), make_job(2)])
    assert result.failed == result.new == 1


async def test_cross_source_counter_and_progress_survive_failure():
    from src.services.pipeline import CollectionResult

    save = AsyncMock(spec=JobSaveService)
    save.save_if_new.side_effect = [
        JobSaveResult(status="saved", job_id=7),
        JobSaveResult(status="duplicate", job_id=8, cross_source_duplicate=True),
        JobSaveResult(status="duplicate", job_id=7),
        RuntimeError("failure"),
    ]
    progress = CollectionResult()
    with pytest.raises(RuntimeError):
        await JobPipeline(save).run([make_job(i) for i in range(5)], result=progress)
    assert progress.model_dump() == dict(
        received=5, new=1, duplicates=2, cross_source_duplicates=1, failed=1
    )
