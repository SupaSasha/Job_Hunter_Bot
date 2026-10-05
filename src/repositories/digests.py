from datetime import UTC, date, datetime, timedelta

from sqlalchemy import or_, select, update
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
                        DigestRunORM.manual.is_(False),
                        DigestRunORM.status != "abandoned",
                    )
                )
                is not None
            )

    async def reserve(
        self, user_id: int, local_date: date, now: datetime, *, manual: bool = False
    ) -> int | None:
        async with self.sessions() as session:
            # Serialize scheduled/manual reservations for this user, including
            # completed-run retries; notification uniqueness remains separate.
            user = await session.scalar(
                select(UserORM.id).where(UserORM.id == user_id).with_for_update()
            )
            if user is None:
                return None
            await session.execute(
                self._stale_query(now).where(DigestRunORM.user_id == user_id)
            )
            pending = await session.scalar(
                select(DigestRunORM.id).where(
                    DigestRunORM.user_id == user_id,
                    DigestRunORM.status == "pending",
                )
            )
            if pending is not None:
                await session.commit()
                return None
            run_id = await session.scalar(
                insert(DigestRunORM)
                .values(
                    user_id=user_id,
                    local_date=local_date,
                    manual=manual,
                    started_at=now,
                    status="pending",
                    selected=0,
                    sent=0,
                    failed=0,
                    skipped=0,
                )
                .on_conflict_do_nothing()
                .returning(DigestRunORM.id)
            )
            # This commit MUST precede the summary and every individual message.
            await session.commit()
            return run_id

    @staticmethod
    def _stale_query(now: datetime):
        from src.config import settings

        cutoff = now - timedelta(minutes=settings.DIGEST_PENDING_TIMEOUT_MINUTES)
        return (
            update(DigestRunORM)
            .where(
                DigestRunORM.status == "pending",
                DigestRunORM.started_at < cutoff,
            )
            .values(
                status="abandoned", finished_at=now, last_error="StaleDigestReservation"
            )
        )

    async def recover_stale(self, now: datetime) -> None:
        async with self.sessions() as session:
            await session.execute(self._stale_query(now))
            await session.commit()

    async def candidates(
        self, user_id: int, *, now: datetime | None = None
    ) -> list[tuple[int, JobDTO]]:
        from src.config import settings

        now = now or datetime.now(UTC)
        since = now - timedelta(days=settings.DIGEST_JOB_MAX_AGE_DAYS)
        already_attempted = (
            select(NotificationORM.id)
            .where(
                NotificationORM.user_id == user_id,
                NotificationORM.job_id == JobORM.id,
                or_(
                    NotificationORM.status != "retryable",
                    NotificationORM.retry_after_until > now,
                ),
            )
            .exists()
        )
        async with self.sessions() as session:
            rows = await session.scalars(
                select(JobORM)
                .where(
                    JobORM.collected_at >= since,
                    JobORM.collected_at <= now,
                    ~already_attempted,
                )
                .order_by(JobORM.collected_at.desc(), JobORM.id.desc())
                .limit(settings.DIGEST_CANDIDATE_LIMIT)
            )
            return [
                (row.id, JobDTO.model_validate(row, from_attributes=True))
                for row in rows
            ]

    async def update(self, run_id: int, **values: object) -> None:
        async with self.sessions() as session:
            await session.execute(
                update(DigestRunORM)
                .where(DigestRunORM.id == run_id, DigestRunORM.status == "pending")
                .values(**values)
            )
            await session.commit()
