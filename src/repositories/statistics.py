from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import (
    CollectorRunORM,
    DigestRunORM,
    FeedbackORM,
    JobORM,
    NotificationORM,
    UserORM,
    UserSubscriptionORM,
)
from src.schemas.digest_metrics import DigestMetrics
from src.schemas.statistics import (
    CollectorStats,
    DataQualityStats,
    DigestStats,
    FeedbackStats,
    NotificationStats,
)


def period_query(query, timestamp, since, until):
    query = query.where(timestamp >= since)
    return query.where(timestamp < until) if until is not None else query


def count_where(condition, name):
    return func.count().filter(condition).label(name)


def sum_column(column, name=None):
    return func.coalesce(func.sum(column), 0).label(name or column.key)


@dataclass
class UserSnapshot:
    total_users: int
    active_users: int
    subscriptions: list[UserSubscriptionORM]


class StatisticsRepository:
    """Read-only aggregates. All period windows are half-open UTC intervals."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_collector_stats(
        self, since: datetime, until: datetime | None = None
    ) -> list[CollectorStats]:
        run = CollectorRunORM
        counters = [
            "received_count",
            "new_count",
            "duplicate_count",
            "cross_source_duplicate_count",
            "failed_count",
            "duration_ms",
        ]
        query = (
            select(
                run.source,
                func.count().label("runs"),
                count_where(run.status == "success", "successful_runs"),
                count_where(run.status == "failed", "failed_runs"),
                count_where(run.status == "skipped", "skipped_runs"),
                count_where(run.status == "running", "running_runs"),
                *(sum_column(getattr(run, name)) for name in counters),
            )
            .group_by(run.source)
            .order_by(run.source)
        )
        result = await self.session.execute(
            period_query(query, run.started_at, since, until)
        )
        return [CollectorStats(**row) for row in result.mappings()]

    async def get_digest_stats(
        self, since: datetime, until: datetime | None = None
    ) -> DigestStats:
        run = DigestRunORM
        query = select(
            func.count().label("runs"),
            count_where(run.metrics_recorded.is_(True), "measured_runs"),
            count_where(run.metrics_recorded.is_(False), "unmeasured_runs"),
            count_where(run.status == "failed", "failed_runs"),
            count_where(run.status == "pending", "pending_runs"),
            *(
                func.coalesce(
                    func.sum(getattr(run, name)).filter(run.metrics_recorded.is_(True)),
                    0,
                ).label(name)
                for name in DigestMetrics.model_fields
            ),
            *(
                sum_column(getattr(run, name), name + "_count")
                for name in ["selected", "sent", "failed", "skipped"]
            ),
        )
        result = await self.session.execute(
            period_query(query, run.started_at, since, until)
        )
        return DigestStats(**result.mappings().one())

    async def get_feedback_stats(
        self, since: datetime, until: datetime | None = None
    ) -> FeedbackStats:
        query = select(
            count_where(FeedbackORM.feedback_type == "saved", "saved_count"),
            count_where(FeedbackORM.feedback_type == "rejected", "rejected_count"),
        )
        result = await self.session.execute(
            period_query(query, FeedbackORM.updated_at, since, until)
        )
        return FeedbackStats(**result.mappings().one())

    async def get_notification_stats(
        self, since: datetime, until: datetime | None = None
    ) -> NotificationStats:
        query = select(
            *(
                count_where(NotificationORM.status == status, status + "_count")
                for status in ["sent", "failed", "pending"]
            )
        )
        result = await self.session.execute(
            period_query(query, NotificationORM.created_at, since, until)
        )
        return NotificationStats(**result.mappings().one())

    async def get_user_stats(self) -> UserSnapshot:
        result = await self.session.execute(
            select(
                func.count(UserORM.id).label("total_users"),
                count_where(UserORM.is_active.is_(True), "active_users"),
            )
        )
        counts = result.mappings().one()
        # The entitlement service interprets subscription status and expiry dates.
        subscriptions = list(await self.session.scalars(select(UserSubscriptionORM)))
        return UserSnapshot(**counts, subscriptions=subscriptions)

    async def get_data_quality(
        self, since: datetime, until: datetime | None = None, *, by_source: bool = False
    ) -> DataQualityStats | dict[str, DataQualityStats]:
        job = JobORM
        query = select(
            func.count().label("job_count"),
            count_where(
                or_(job.salary_min > 0, job.salary_max > 0),
                "salary_known_count",
            ),
            count_where(func.cardinality(job.remote_regions) > 0, "region_known_count"),
            count_where(
                or_(
                    func.length(func.trim(job.timezone_text)) > 0,
                    job.timezone_min_utc_offset.is_not(None),
                    job.timezone_max_utc_offset.is_not(None),
                ),
                "timezone_known_count",
            ),
            count_where(
                func.cardinality(job.technologies) > 0, "technologies_known_count"
            ),
        )
        if by_source:
            query = query.add_columns(job.source).group_by(job.source)
        result = await self.session.execute(
            period_query(query, job.created_at, since, until)
        )
        if by_source:
            return {row["source"]: DataQualityStats(**row) for row in result.mappings()}
        return DataQualityStats(**result.mappings().one())
