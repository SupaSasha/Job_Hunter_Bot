from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.feedback import FeedbackORM
from src.models.job import JobORM


class FeedbackRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_user_job(self, user_id: int, job_id: int) -> FeedbackORM | None:
        return await self.session.scalar(
            select(FeedbackORM).where(
                FeedbackORM.user_id == user_id, FeedbackORM.job_id == job_id
            )
        )

    async def add(self, feedback: FeedbackORM) -> FeedbackORM:
        self.session.add(feedback)
        await self.session.flush()
        return feedback

    async def update_type(
        self, feedback: FeedbackORM, feedback_type: str
    ) -> FeedbackORM:
        # Always issue UPDATE, even if the local ORM snapshot has the same type:
        # another transaction may have changed the row since it was read.
        updated = await self.session.scalar(
            update(FeedbackORM)
            .where(FeedbackORM.id == feedback.id)
            .values(feedback_type=feedback_type, updated_at=func.now())
            .returning(FeedbackORM),
            execution_options={"populate_existing": True},
        )
        if updated is None:
            raise LookupError("Feedback no longer exists")
        return updated

    async def get_saved_jobs_for_user(
        self, user_id: int, limit: int = 10
    ) -> list[JobORM]:
        rows = await self.session.scalars(
            select(JobORM)
            .join(FeedbackORM, FeedbackORM.job_id == JobORM.id)
            .where(FeedbackORM.user_id == user_id, FeedbackORM.feedback_type == "saved")
            .order_by(FeedbackORM.updated_at.desc(), FeedbackORM.id.desc())
            .limit(limit)
        )
        return list(rows)
