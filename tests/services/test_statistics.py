from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from src.models import UserSubscriptionORM
from src.repositories.statistics import StatisticsRepository, UserSnapshot
from src.schemas.statistics import (
    CollectorStats,
    DataQualityStats,
    DigestStats,
    FeedbackStats,
    NotificationStats,
)
from src.services.entitlements import EntitlementService
from src.services.statistics import StatisticsService

NOW = datetime(2026, 9, 30, 15, tzinfo=UTC)


@pytest.fixture
def repository():
    repo = AsyncMock(spec=StatisticsRepository)
    repo.get_collector_stats.return_value = []
    repo.get_digest_stats.return_value = DigestStats()
    repo.get_feedback_stats.return_value = FeedbackStats()
    repo.get_notification_stats.return_value = NotificationStats()
    repo.get_user_stats.return_value = UserSnapshot(0, 0, [])
    repo.get_data_quality.side_effect = lambda *args, by_source=False: (
        {} if by_source else DataQualityStats()
    )
    return repo


@pytest.mark.parametrize("period,days", [("24h", 1), ("7d", 7), ("30d", 30)])
async def test_empty_stats_and_consistent_period_boundaries(repository, period, days):
    stats = await StatisticsService(
        repository, EntitlementService(), clock=lambda: NOW
    ).get_stats(period)
    assert stats.since == NOW - timedelta(days=days)
    assert stats.until == NOW
    assert stats.users.total_users == 0
    assert {row.source for row in stats.collectors} == {
        "remoteok",
        "weworkremotely",
        "getonboard",
        "himalayas",
    }
    assert all(
        getattr(stats, name) is None
        for name in [
            "duplicate_rate",
            "filter_rejection_rate",
            "save_rate",
            "reject_rate",
            "notification_success_rate",
        ]
    )
    assert stats.quality.salary_known_percent is None
    repository.get_collector_stats.assert_awaited_once_with(stats.since, NOW)
    repository.get_digest_stats.assert_awaited_once_with(stats.since, NOW)


async def test_rates_source_efficiency_completeness_and_expiry(repository):
    repository.get_collector_stats.return_value = [
        CollectorStats(
            source="remoteok",
            runs=5,
            successful_runs=1,
            failed_runs=1,
            skipped_runs=2,
            running_runs=1,
            received_count=10,
            new_count=2,
            duplicate_count=8,
        )
    ]
    repository.get_digest_stats.return_value = DigestStats(
        candidate_count=20, filter_rejected_count=15
    )
    repository.get_notification_stats.return_value = NotificationStats(
        sent_count=8, failed_count=2
    )
    repository.get_feedback_stats.return_value = FeedbackStats(
        saved_count=4, rejected_count=2
    )
    quality = DataQualityStats(
        job_count=4,
        salary_known_count=1,
        region_known_count=2,
        timezone_known_count=0,
        technologies_known_count=4,
    )
    repository.get_data_quality.side_effect = lambda *args, by_source=False: (
        {"remoteok": quality.model_copy()} if by_source else quality.model_copy()
    )
    repository.get_user_stats.return_value = UserSnapshot(
        5,
        3,
        [
            UserSubscriptionORM(status="trial", trial_ends_at=NOW + timedelta(days=1)),
            UserSubscriptionORM(status="trial", trial_ends_at=NOW),
            UserSubscriptionORM(status="active", subscription_ends_at=None),
            UserSubscriptionORM(
                status="active", subscription_ends_at=NOW - timedelta(days=1)
            ),
        ],
    )
    stats = await StatisticsService(
        repository, EntitlementService(), clock=lambda: NOW
    ).get_stats()
    assert stats.duplicate_rate == 0.8
    assert stats.filter_rejection_rate == 0.75
    assert stats.notification_success_rate == 0.8
    assert stats.save_rate == 0.5
    assert stats.reject_rate == 0.25
    source = next(s for s in stats.collectors if s.source == "remoteok")
    assert source.new_jobs_per_run == 1
    assert source.duplicate_rate == 0.8
    assert source.quality.salary_known_percent == 25
    assert stats.quality.region_known_percent == 50
    assert stats.quality.timezone_known_percent == 0
    assert stats.quality.technologies_known_percent == 100
    assert stats.users.model_dump() == dict(
        total_users=5, active_users=3, trial_users=1, premium_users=1, free_users=3
    )


async def test_invalid_period_rejected_before_queries(repository):
    with pytest.raises(ValueError):
        await StatisticsService(repository, EntitlementService()).get_stats("1y")
    repository.get_collector_stats.assert_not_awaited()
