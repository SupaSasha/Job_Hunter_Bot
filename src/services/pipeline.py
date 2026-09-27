from pydantic import BaseModel

from src.models.user import UserORM
from src.schemas.filters import UserFilterDTO
from src.schemas.job import JobDTO
from src.services.filters import FilterService
from src.services.jobs import JobSaveService
from src.services.normalization import NormalizationService
from src.services.notifications import NotificationService
from src.services.scoring import ScoringService


class PipelineSummary(BaseModel):
    received: int = 0
    new: int = 0
    duplicates: int = 0
    filter_rejected: int = 0
    below_score: int = 0
    sent: int = 0
    failed: int = 0
    notification_skipped: int = 0
    limit_reached: int = 0


class JobPipeline:
    def __init__(
        self,
        save_service: JobSaveService,
        *,
        filters: UserFilterDTO,
        min_score: int,
        max_notifications: int,
        notifications: NotificationService | None = None,
        owner: UserORM | None = None,
    ) -> None:
        if not 0 <= min_score <= 100 or max_notifications < 0:
            raise ValueError("Invalid notification threshold or limit")
        self.save_service = save_service
        self.filters = filters
        self.min_score = min_score
        self.max_notifications = max_notifications
        self.notifications = notifications
        self.owner = owner
        self.normalizer = NormalizationService()
        self.filter_service = FilterService()
        self.scoring = ScoringService()

    async def run(self, jobs: list[JobDTO]) -> PipelineSummary:
        summary = PipelineSummary(received=len(jobs))
        attempts = 0
        for raw_job in jobs:
            job = self.normalizer.normalize(raw_job)
            saved = await self.save_service.save_if_new(job)
            if saved.status == "duplicate":
                summary.duplicates += 1
                continue
            summary.new += 1
            if not self.filter_service.evaluate(job, self.filters).accepted:
                summary.filter_rejected += 1
                continue
            score = self.scoring.calculate(job, self.filters)
            if score.score < self.min_score:
                summary.below_score += 1
                continue
            if self.notifications is None or self.owner is None:
                summary.notification_skipped += 1
                continue
            if attempts >= self.max_notifications:
                summary.limit_reached += 1
                continue
            result = await self.notifications.notify(
                user=self.owner, job_id=saved.job_id, job=job, score=score
            )
            if result.skipped:
                summary.notification_skipped += 1
                continue
            # Failed/ambiguous HTTP attempts count too: a timeout may have delivered.
            attempts += 1
            if result.sent:
                summary.sent += 1
            else:
                summary.failed += 1
        return summary
