from datetime import date, datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.models.job import JobORM
from src.models.notification import NotificationORM
from src.models.scheduling import (
    DigestRunORM,
    UserNotificationSettingsORM,
    UserSubscriptionORM,
)
from src.models.user import UserORM
from src.schemas.job import JobDTO


class DigestRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]):
        self.sessions = sessions

    async def users(self, user_id: int | None = None) -> list[tuple]:
        query = (
            select(UserORM, UserNotificationSettingsORM, UserSubscriptionORM)
            .join(
                UserNotificationSettingsORM,
                UserNotificationSettingsORM.user_id == UserORM.id,
            )
            .outerjoin(UserSubscriptionORM, UserSubscriptionORM.user_id == UserORM.id)
            .where(
                UserORM.is_active.is_(True),
                UserNotificationSettingsORM.digest_enabled.is_(True),
            )
        )
        if user_id is not None:
            query = query.where(UserORM.id == user_id)
        async with self.sessions() as session:
            # Detached snapshots survive per-notification rollbacks.
            return list((await session.execute(query)).all())

    async def attempted(self, user_id: int, local_date: date) -> bool:
        async with self.sessions() as session:
            return (
                await session.scalar(
                    select(DigestRunORM.id).where(
                        DigestRunORM.user_id == user_id,
                        DigestRunORM.local_date == local_date,
                    )
                )
                is not None
            )

    async def reserve(
        self, user_id: int, local_date: date, now: datetime
    ) -> int | None:
        async with self.sessions() as session:
            run_id = await session.scalar(
                insert(DigestRunORM)
                .values(
                    user_id=user_id,
                    local_date=local_date,
                    started_at=now,
                    status="pending",
                    selected=0,
                    sent=0,
                    failed=0,
                    skipped=0,
                )
                .on_conflict_do_nothing(constraint="uq_digest_user_date")
                .returning(DigestRunORM.id)
            )
            # This commit MUST precede the summary and every individual message.
            await session.commit()
            return run_id

    async def candidates(self, user_id: int) -> list[tuple[int, JobDTO]]:
        already_attempted = (
            select(NotificationORM.id)
            .where(
                NotificationORM.user_id == user_id,
                NotificationORM.job_id == JobORM.id,
            )
            .exists()
        )
        async with self.sessions() as session:
            rows = await session.scalars(
                select(JobORM).where(~already_attempted).order_by(JobORM.id)
            )
            return [
                (row.id, JobDTO.model_validate(row, from_attributes=True))
                for row in rows
            ]

    async def update(self, run_id: int, **values: object) -> None:
        async with self.sessions() as session:
            await session.execute(
                update(DigestRunORM).where(DigestRunORM.id == run_id).values(**values)
            )
            await session.commit()
