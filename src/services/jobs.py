from datetime import timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.job import JobORM
from src.repositories.jobs import JobRepository
from src.schemas.deduplication import JobSaveResult
from src.schemas.job import JobDTO
from src.services.deduplication import DeduplicationService


def _job_values(job: JobDTO) -> dict:
    data = job.model_dump()
    for field in ("published_at", "collected_at"):
        value = data[field]
        if value is not None:
            if value.utcoffset() is None:
                raise ValueError(f"{field} must be timezone-aware")
            data[field] = value.astimezone(timezone.utc)
    return data


def job_to_orm(job: JobDTO, fingerprint: str) -> JobORM:
    return JobORM(**_job_values(job), fingerprint=fingerprint)


class JobSaveService:
    """Own one transaction per save; use a session without unrelated pending work.

    Each concurrent task must have its own session. Source identity conflicts are
    recovered after rollback; fingerprint matching is a best-effort MVP heuristic.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = JobRepository(session)
        self.deduplication = DeduplicationService(self.repository)

    async def _refresh_existing(self, job_id: int, job: JobDTO) -> None:
        values = _job_values(job)
        # Preserve identity, first collection time and cross-source discoveries.
        for field in ("source", "external_id", "collected_at", "additional_sources"):
            values.pop(field)
        values["fingerprint"] = self.deduplication.calculate_fingerprint(job)
        await self.repository.update_details(job_id, values)
        await self.session.commit()

    async def save_if_new(self, job: JobDTO) -> JobSaveResult:
        try:
            duplicate = await self.deduplication.check(job)
            if duplicate.is_duplicate:
                result = JobSaveResult(
                    status="duplicate",
                    job_id=duplicate.existing_job_id,
                    reason=duplicate.reason,
                    cross_source_duplicate=duplicate.cross_source_duplicate,
                )
                if duplicate.reason == "source_external_id":
                    await self._refresh_existing(result.job_id, job)
                elif duplicate.cross_source_duplicate:
                    await self.repository.add_source(result.job_id, job.source)
                    await self.session.commit()
                else:
                    await self.session.rollback()
                return result

            persisted = await self.repository.add(
                job_to_orm(job, duplicate.fingerprint)
            )
            result = JobSaveResult(status="saved", job_id=persisted.id)
            await self.session.commit()
            return result
        except IntegrityError as exc:
            await self.session.rollback()
            # asyncpg's original error is chained by SQLAlchemy's adapter.
            original = exc.orig
            cause = original.__cause__
            sqlstate = getattr(original, "sqlstate", None)
            constraint = getattr(cause, "constraint_name", None)
            if sqlstate != "23505" or constraint != "uq_jobs_source_external_id":
                raise
            try:
                existing = await self.repository.get_by_source_external_id(
                    job.source, job.external_id
                )
                if existing is None:
                    raise exc
                existing_id = existing.id
                await self._refresh_existing(existing_id, job)
                return JobSaveResult(
                    status="duplicate",
                    job_id=existing_id,
                    reason="source_external_id",
                )
            except Exception:
                await self.session.rollback()
                raise
        except Exception:
            await self.session.rollback()
            raise
