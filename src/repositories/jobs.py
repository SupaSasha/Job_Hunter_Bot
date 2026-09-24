from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.job import JobORM


class JobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_source_external_id(
        self, source: str, external_id: str
    ) -> JobORM | None:
        return await self.session.scalar(
            select(JobORM).where(
                JobORM.source == source, JobORM.external_id == external_id
            )
        )

    async def get_by_fingerprint(self, fingerprint: str) -> JobORM | None:
        return await self.session.scalar(
            select(JobORM)
            .where(JobORM.fingerprint == fingerprint)
            .order_by(JobORM.id)
            .limit(1)
        )

    async def add(self, job: JobORM) -> JobORM:
        self.session.add(job)
        await self.session.flush()
        return job
