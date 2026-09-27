from pydantic import BaseModel

from src.schemas.job import JobDTO
from src.services.jobs import JobSaveService
from src.services.normalization import NormalizationService


class CollectionResult(BaseModel):
    received: int = 0
    new: int = 0
    duplicates: int = 0
    failed: int = 0


class JobPipeline:
    """Collection only. Delivery never depends on a job being newly inserted."""

    def __init__(self, save_service: JobSaveService) -> None:
        self.save_service = save_service
        self.normalizer = NormalizationService()

    async def run(self, jobs: list[JobDTO]) -> CollectionResult:
        result = CollectionResult(received=len(jobs))
        for raw_job in jobs:
            try:
                job = self.normalizer.normalize(raw_job)
            except (TypeError, ValueError):
                result.failed += 1
                continue
            # Database failures abort the run; the collector schedules a later retry.
            saved = await self.save_service.save_if_new(job)
            if saved.status == "duplicate":
                result.duplicates += 1
            else:
                result.new += 1
        return result
