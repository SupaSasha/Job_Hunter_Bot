from datetime import datetime, timezone

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.notification import NotificationORM


class NotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_user_job(
        self, user_id: int, job_id: int
    ) -> NotificationORM | None:
        return await self.session.scalar(
            select(NotificationORM).where(
                NotificationORM.user_id == user_id,
                NotificationORM.job_id == job_id,
            )
        )

    async def add(self, notification: NotificationORM) -> NotificationORM:
        self.session.add(notification)
        await self.session.flush()
        return notification

    async def mark_sent(self, notification_id: int, telegram_message_id: int) -> None:
        await self.session.execute(
            update(NotificationORM)
            .where(NotificationORM.id == notification_id)
            .values(
                status="sent",
                telegram_message_id=telegram_message_id,
                sent_at=datetime.now(timezone.utc),
            )
        )

    async def claim_retryable(self, notification_id: int, now: datetime) -> int | None:
        return await self.session.scalar(
            update(NotificationORM)
            .where(
                NotificationORM.id == notification_id,
                NotificationORM.status == "retryable",
                or_(
                    NotificationORM.retry_after_until.is_(None),
                    NotificationORM.retry_after_until <= now,
                ),
            )
            .values(status="pending", retry_after_until=None)
            .returning(NotificationORM.id)
        )

    async def mark_failed(
        self,
        notification_id: int,
        *,
        status: str = "failed",
        retry_after_until: datetime | None = None,
    ) -> None:
        await self.session.execute(
            update(NotificationORM)
            .where(NotificationORM.id == notification_id)
            .values(status=status, retry_after_until=retry_after_until)
        )
