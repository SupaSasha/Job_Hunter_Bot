from datetime import UTC, datetime, timedelta
from typing import Callable

from src.repositories.statistics import StatisticsRepository
from src.schemas.statistics import (
    BotStats,
    CollectorStats,
    DataQualityStats,
    StatsPeriod,
    UserStats,
)
from src.services.collector_policy import COLLECTOR_POLICIES
from src.services.entitlements import EntitlementService

PERIODS = {"24h": timedelta(days=1), "7d": timedelta(days=7), "30d": timedelta(days=30)}


def ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def quality_percentages(quality: DataQualityStats) -> DataQualityStats:
    for field in ["salary", "region", "timezone", "technologies"]:
        fraction = ratio(getattr(quality, field + "_known_count"), quality.job_count)
        setattr(
            quality,
            field + "_known_percent",
            None if fraction is None else fraction * 100,
        )
    return quality


class StatisticsService:
    def __init__(
        self,
        repository: StatisticsRepository,
        entitlements: EntitlementService,
        *,
        clock: Callable = lambda: datetime.now(UTC),
    ):
        self.repository = repository
        self.entitlements = entitlements
        self.clock = clock

    async def get_stats(self, period: StatsPeriod = "7d") -> BotStats:
        if period not in PERIODS:
            raise ValueError("Unsupported statistics period")
        now = self.clock()
        if now.utcoffset() is None:
            raise ValueError("Statistics clock must be timezone-aware")
        until = now.astimezone(UTC)
        since = until - PERIODS[period]
        repository = self.repository
        collectors = {
            s.source: s for s in await repository.get_collector_stats(since, until)
        }
        quality_by_source = await repository.get_data_quality(
            since, until, by_source=True
        )
        for source in dict.fromkeys([*COLLECTOR_POLICIES, *quality_by_source]):
            collectors.setdefault(source, CollectorStats(source=source))
        for source, stats in collectors.items():
            stats.duplicate_rate = ratio(stats.duplicate_count, stats.received_count)
            stats.new_jobs_per_run = ratio(
                stats.new_count, stats.successful_runs + stats.failed_runs
            )
            stats.quality = quality_percentages(
                quality_by_source.get(source, DataQualityStats())
            )
        digest = await repository.get_digest_stats(since, until)
        feedback = await repository.get_feedback_stats(since, until)
        notifications = await repository.get_notification_stats(since, until)
        snapshot = await repository.get_user_stats()
        users = UserStats(
            total_users=snapshot.total_users, active_users=snapshot.active_users
        )
        for subscription in snapshot.subscriptions:
            plan, _ = self.entitlements.plan(subscription, until)
            users.trial_users += int(plan == "Trial")
            users.premium_users += int(plan == "Premium")
        users.free_users = users.total_users - users.trial_users - users.premium_users
        return BotStats(
            period=period,
            since=since,
            until=until,
            collectors=list(collectors.values()),
            digest=digest,
            feedback=feedback,
            notifications=notifications,
            users=users,
            quality=quality_percentages(
                await repository.get_data_quality(since, until)
            ),
            duplicate_rate=ratio(
                sum(s.duplicate_count for s in collectors.values()),
                sum(s.received_count for s in collectors.values()),
            ),
            filter_rejection_rate=ratio(
                digest.filter_rejected_count, digest.candidate_count
            ),
            notification_success_rate=ratio(
                notifications.sent_count,
                notifications.sent_count
                + notifications.failed_count
                + notifications.retryable_count,
            ),
            save_rate=ratio(feedback.saved_count, notifications.sent_count),
            reject_rate=ratio(feedback.rejected_count, notifications.sent_count),
        )
