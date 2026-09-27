from unittest.mock import AsyncMock, Mock

import pytest

from src.models.user import UserORM
from src.schemas.deduplication import JobSaveResult
from src.schemas.filters import FilterResult, UserFilterDTO
from src.schemas.job import JobDTO
from src.schemas.notifications import NotificationResult
from src.schemas.scoring import ScoreResult
from src.services.jobs import JobSaveService
from src.services.notifications import NotificationService
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


@pytest.fixture
def pipeline() -> JobPipeline:
    save = AsyncMock(spec=JobSaveService)
    save.save_if_new.return_value = JobSaveResult(status="saved", job_id=7)
    notifications = AsyncMock(spec=NotificationService)
    notifications.notify.return_value = NotificationResult(sent=True, skipped=False)
    pipeline = JobPipeline(
        save,
        filters=UserFilterDTO(required_technologies=["python"]),
        min_score=70,
        max_notifications=5,
        notifications=notifications,
        owner=UserORM(id=2, telegram_id=123, is_active=True),
    )
    pipeline.filter_service = Mock()
    pipeline.filter_service.evaluate.return_value = FilterResult(accepted=True)
    pipeline.scoring = Mock()
    pipeline.scoring.calculate.return_value = ScoreResult(score=70)
    return pipeline


async def test_only_new_persisted_jobs_reach_filters(pipeline) -> None:
    pipeline.save_service.save_if_new.return_value = JobSaveResult(
        status="duplicate", job_id=7
    )
    result = await pipeline.run([make_job()])
    assert result.duplicates == 1 and result.new == 0
    pipeline.filter_service.evaluate.assert_not_called()
    pipeline.scoring.calculate.assert_not_called()
    pipeline.notifications.notify.assert_not_awaited()


async def test_filter_rejected_job_is_still_saved(pipeline) -> None:
    pipeline.filter_service.evaluate.return_value = FilterResult(accepted=False)
    result = await pipeline.run([make_job()])
    assert result.new == result.filter_rejected == 1
    pipeline.save_service.save_if_new.assert_awaited_once()
    pipeline.scoring.calculate.assert_not_called()
    pipeline.notifications.notify.assert_not_awaited()


async def test_below_score_is_not_sent(pipeline) -> None:
    pipeline.scoring.calculate.return_value = ScoreResult(score=69)
    result = await pipeline.run([make_job()])
    assert result.below_score == 1
    pipeline.notifications.notify.assert_not_awaited()


async def test_exact_threshold_and_normalization(pipeline) -> None:
    result = await pipeline.run([make_job()])
    assert result.sent == 1
    job = pipeline.save_service.save_if_new.call_args.args[0]
    assert job.title == "Python Developer"
    assert job.technologies == ["python", "fastapi"]
    assert job.remote_regions == ["worldwide"]
    args = pipeline.notifications.notify.call_args.kwargs
    assert args["job_id"] == 7 and args["score"].score == 70
    assert args["job"] is job


@pytest.mark.parametrize("sent", [True, False])
async def test_limit_counts_failed_attempts_and_keeps_saving(pipeline, sent) -> None:
    pipeline.max_notifications = 1
    pipeline.notifications.notify.return_value = NotificationResult(
        sent=sent, skipped=False
    )
    result = await pipeline.run([make_job(n) for n in range(3)])
    assert result.new == 3 and result.limit_reached == 2
    assert result.sent == int(sent) and result.failed == int(not sent)
    assert pipeline.save_service.save_if_new.await_count == 3
    pipeline.notifications.notify.assert_awaited_once()


async def test_zero_limit_disables_sending(pipeline) -> None:
    pipeline.max_notifications = 0
    result = await pipeline.run([make_job()])
    assert result.limit_reached == 1
    pipeline.notifications.notify.assert_not_awaited()


async def test_no_credentials_preserves_persistence(pipeline) -> None:
    pipeline.notifications = pipeline.owner = None
    result = await pipeline.run([make_job()])
    assert result.new == result.notification_skipped == 1
    assert result.sent == 0


async def test_notification_skip_does_not_consume_http_attempt_limit(pipeline) -> None:
    pipeline.max_notifications = 1
    pipeline.notifications.notify.side_effect = [
        NotificationResult(sent=False, skipped=True, reason="already_sent"),
        NotificationResult(sent=True, skipped=False),
    ]
    result = await pipeline.run([make_job(), make_job(2)])
    assert result.notification_skipped == result.sent == 1
    assert result.limit_reached == 0
