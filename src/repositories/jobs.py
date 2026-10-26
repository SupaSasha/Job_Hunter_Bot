from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.job import JobORM


class JobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, job_id: int) -> JobORM | None:
        return await self.session.get(JobORM, job_id)

    async def get_by_source_external_id(
        self, source: str, external_id: str
    ) -> JobORM | None:
        return await self.session.scalar(
            select(JobORM).where(
                JobORM.source == source, JobORM.external_id == external_id
            )
        )

    async def get_by_fingerprint(
        self, fingerprint: str, *, since: datetime
    ) -> JobORM | None:
        return await self.session.scalar(
            select(JobORM)
            .where(JobORM.fingerprint == fingerprint, JobORM.collected_at >= since)
            .order_by(JobORM.id)
            .limit(1)
        )

    async def add(self, job: JobORM) -> JobORM:
        self.session.add(job)
        await self.session.flush()
        return job

    async def add_source(self, job_id: int, source: str) -> None:
        # Append in SQL so concurrent discoveries cannot overwrite each other.
        await self.session.execute(
            update(JobORM)
            .where(
                JobORM.id == job_id,
                JobORM.source != source,
                ~JobORM.additional_sources.any(source),
            )
            .values(
                additional_sources=func.array_append(JobORM.additional_sources, source)
            )
        )

    async def update_details(self, job_id: int, values: dict) -> None:
        await self.session.execute(
            update(JobORM).where(JobORM.id == job_id).values(**values)
        )
