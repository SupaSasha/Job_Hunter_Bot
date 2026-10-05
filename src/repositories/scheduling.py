from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.models.scheduling import (
    CollectorStateORM,
    UserNotificationSettingsORM,
    UserSubscriptionORM,
)
from src.models.user import UserORM
from src.services.collector_policy import COLLECTOR_POLICIES, next_collection


class CollectorStateRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]):
        self.sessions = sessions

    async def ensure(self, source: str, now: datetime, timezone: str) -> None:
        async with self.sessions() as session:
            existing = await session.scalar(
                select(CollectorStateORM.id).where(CollectorStateORM.source == source)
            )
            if existing is not None:
                return
            next_run = next_collection(
                now, COLLECTOR_POLICIES[source], timezone, initial=True
            )
            await session.execute(
                insert(CollectorStateORM)
                .values(source=source, next_run_at=next_run, last_status="scheduled")
                .on_conflict_do_nothing(index_elements=["source"])
            )
            await session.commit()

    async def due(self, now: datetime) -> list[CollectorStateORM]:
        async with self.sessions() as session:
            return list(
                (
                    await session.scalars(
                        select(CollectorStateORM).where(
                            CollectorStateORM.next_run_at <= now
                        )
                    )
                ).all()
            )

    async def get(self, source: str) -> CollectorStateORM:
        async with self.sessions() as session:
            state = await session.scalar(
                select(CollectorStateORM).where(CollectorStateORM.source == source)
            )
            if state is None:
                raise LookupError(source)
            return state

    async def update(self, source: str, **values: object) -> None:
        async with self.sessions() as session:
            await session.execute(
                update(CollectorStateORM)
                .where(CollectorStateORM.source == source)
                .values(**values)
            )
            await session.commit()


def delivery_defaults(settings, now: datetime) -> list[tuple]:
    """Shared missing-only bootstrap values; never renew an existing trial."""
    return [
        (
            UserNotificationSettingsORM,
            dict(
                timezone=settings.SCHEDULER_TIMEZONE,
                digest_time=settings.FREE_DIGEST_TIME,
                min_score=settings.FREE_MIN_SCORE,
                digest_enabled=True,
                max_jobs_per_digest=settings.FREE_MAX_JOBS_PER_DIGEST,
            ),
        ),
        (
            UserSubscriptionORM,
            dict(
                status="trial",
                trial_started_at=now,
                trial_ends_at=now + timedelta(days=settings.TRIAL_DAYS),
            ),
        ),
    ]


class DeliveryBootstrap:
    """Idempotent defaults, including existing users; never renew an old trial."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession], settings):
        self.sessions = sessions
        self.settings = settings

    async def ensure_users(self, now: datetime | None = None) -> None:
        now = now or datetime.now(UTC)
        async with self.sessions() as session:
            inserted = False
            defaults = delivery_defaults(self.settings, now)
            for model, values in defaults:
                exists = select(model.id).where(model.user_id == UserORM.id).exists()
                missing = list(await session.scalars(select(UserORM.id).where(~exists)))
                if missing:
                    await session.execute(
                        insert(model)
                        .values(
                            [dict(user_id=user_id, **values) for user_id in missing]
                        )
                        .on_conflict_do_nothing(index_elements=["user_id"])
                    )
                    inserted = True
            if inserted:
                await session.commit()
