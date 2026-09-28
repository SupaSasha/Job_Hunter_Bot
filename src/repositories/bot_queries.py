from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.job import JobORM
from src.models.scheduling import (
    CollectorStateORM,
    DigestRunORM,
    UserNotificationSettingsORM,
    UserSubscriptionORM,
)


class BotQueryRepository:
    """Read-only queries used by Telegram commands."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def collector_state(self, source: str) -> CollectorStateORM | None:
        return await self.session.scalar(
            select(CollectorStateORM).where(CollectorStateORM.source == source)
        )

    async def collector_states(self) -> list[CollectorStateORM]:
        return list(
            await self.session.scalars(
                select(CollectorStateORM).order_by(CollectorStateORM.source)
            )
        )

    async def job_count(self) -> int:
        return await self.session.scalar(select(func.count()).select_from(JobORM))

    async def preferences(self, user_id: int) -> UserNotificationSettingsORM | None:
        return await self.session.scalar(
            select(UserNotificationSettingsORM).where(
                UserNotificationSettingsORM.user_id == user_id
            )
        )

    async def subscription(self, user_id: int) -> UserSubscriptionORM | None:
        return await self.session.scalar(
            select(UserSubscriptionORM)
            .where(UserSubscriptionORM.user_id == user_id)
            .execution_options(populate_existing=True)
        )

    async def last_digest(self, user_id: int) -> DigestRunORM | None:
        return await self.session.scalar(
            select(DigestRunORM)
            .where(DigestRunORM.user_id == user_id)
            .order_by(DigestRunORM.started_at.desc(), DigestRunORM.id.desc())
            .limit(1)
        )
