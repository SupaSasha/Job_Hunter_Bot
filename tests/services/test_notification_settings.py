from datetime import UTC, datetime, time, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.scheduling import UserNotificationSettingsORM, UserSubscriptionORM
from src.repositories.bot_queries import BotQueryRepository
from src.repositories.notification_settings import NotificationSettingsRepository
from src.services.entitlements import EntitlementService
from src.services.notification_settings import (
    NotificationSettingsService,
    PremiumRequired,
    SettingsUnavailable,
)

NOW = datetime(2026, 9, 28, 15, tzinfo=UTC)


@pytest.fixture
def service():
    result = NotificationSettingsService(
        AsyncMock(spec=AsyncSession),
        EntitlementService(free_digest_time=time(10, 15), free_min_score=65),
        clock=lambda: NOW,
    )
    result.repository = AsyncMock(spec=NotificationSettingsRepository)
    result.repository.get_by_user_id.return_value = UserNotificationSettingsORM(
        user_id=7,
        timezone="America/Montevideo",
        digest_time=time(7, 30),
        min_score=85,
        max_jobs_per_digest=10,
        digest_enabled=True,
    )
    result.queries = AsyncMock(spec=BotQueryRepository)
    result.queries.subscription.return_value = UserSubscriptionORM(
        status="trial",
        trial_ends_at=NOW + timedelta(days=1),
    )
    return result


@pytest.mark.parametrize(
    "status,end,plan",
    [
        ("trial", NOW + timedelta(days=1), "Trial"),
        ("trial", NOW, "Free"),
        ("trial", None, "Free"),
        ("active", None, "Premium"),
        ("active", NOW + timedelta(days=1), "Premium"),
        ("active", NOW, "Free"),
        ("expired", None, "Free"),
        (None, None, "Free"),
    ],
)
async def test_effective_plan_and_values(service, status, end, plan):
    service.queries.subscription.return_value = (
        UserSubscriptionORM(status=status, trial_ends_at=end, subscription_ends_at=end)
        if status
        else None
    )
    view = await service.get(7)
    assert view.plan == plan
    assert view.effective.digest_time == (
        time(10, 15) if plan == "Free" else time(7, 30)
    )
    assert view.effective.min_score == (65 if plan == "Free" else 85)
    assert view.trial_ends_at == (end if plan == "Trial" else None)


async def test_expired_then_reactivated_preserves_custom_values(service):
    subscription = service.queries.subscription.return_value
    subscription.trial_ends_at = NOW - timedelta(seconds=1)
    assert (await service.get(7)).effective.min_score == 65
    for method, value in (("update_digest_time", time(8)), ("update_min_score", 80)):
        with pytest.raises(PremiumRequired):
            await getattr(service, method)(7, value)
        getattr(service.repository, method).assert_not_awaited()
    preferences = service.repository.get_by_user_id.return_value
    assert (preferences.digest_time, preferences.min_score) == (time(7, 30), 85)
    subscription.status = "active"
    subscription.subscription_ends_at = None
    view = await service.get(7)
    assert (view.effective.digest_time, view.effective.min_score) == (time(7, 30), 85)
    service.session.commit.assert_not_awaited()
    assert service.session.rollback.await_count == 2


@pytest.mark.parametrize("status", ["trial", "active"])
@pytest.mark.parametrize(
    "method,value",
    [
        ("update_digest_time", time(8)),
        ("update_min_score", 80),
        ("update_min_score", 0),
        ("update_min_score", 100),
    ],
)
async def test_custom_settings_commit_for_trial_and_premium(
    service, status, method, value
):
    service.queries.subscription.return_value.status = status
    await getattr(service, method)(7, value)
    getattr(service.repository, method).assert_awaited_once_with(7, value)
    service.session.commit.assert_awaited_once()
    service.session.rollback.assert_not_awaited()


async def test_timezone_is_available_without_subscription(service):
    service.queries.subscription.return_value = None
    await service.update_timezone(7, "Europe/Madrid")
    service.repository.update_timezone.assert_awaited_once_with(7, "Europe/Madrid")
    service.session.commit.assert_awaited_once()


@pytest.mark.parametrize(
    "method,value",
    [
        ("update_timezone", "Not/AZone"),
        ("update_timezone", "/etc/passwd"),
        ("update_timezone", ""),
        ("update_timezone", None),
        ("update_digest_time", "09:00"),
        ("update_digest_time", datetime.now(UTC)),
        ("update_digest_time", time(9, tzinfo=UTC)),
        ("update_digest_time", time(9, 0, 1)),
        ("update_digest_time", time(9, 0, 0, 1)),
        ("update_min_score", -1),
        ("update_min_score", 101),
        ("update_min_score", True),
        ("update_min_score", 80.0),
        ("update_min_score", "80"),
    ],
)
async def test_invalid_values_never_reach_repository(service, method, value):
    with pytest.raises(ValueError):
        await getattr(service, method)(7, value)
    getattr(service.repository, method).assert_not_awaited()
    service.session.commit.assert_not_awaited()


async def test_expiration_is_checked_again_on_save(service):
    assert (await service.get(7)).effective.premium
    service.clock = lambda: NOW + timedelta(days=2)
    with pytest.raises(PremiumRequired):
        await service.update_min_score(7, 80)
    service.repository.update_min_score.assert_not_awaited()


async def test_missing_preferences(service):
    service.repository.get_by_user_id.return_value = None
    with pytest.raises(SettingsUnavailable):
        await service.update_timezone(7, "UTC")
    service.session.rollback.assert_awaited_once()
    service.repository.update_timezone.assert_not_awaited()


async def test_write_failure_rolls_back(service):
    service.repository.update_min_score.side_effect = RuntimeError
    with pytest.raises(RuntimeError):
        await service.update_min_score(7, 80)
    service.session.rollback.assert_awaited_once()
    service.session.commit.assert_not_awaited()


@pytest.mark.parametrize("subscription", [None, UserSubscriptionORM(status="expired")])
@pytest.mark.parametrize(
    "method,value",
    [
        ("update_digest_time", time(8)),
        ("update_min_score", 80),
    ],
)
async def test_free_without_current_subscription_cannot_write(
    service, subscription, method, value
):
    service.queries.subscription.return_value = subscription
    with pytest.raises(PremiumRequired):
        await getattr(service, method)(7, value)
    getattr(service.repository, method).assert_not_awaited()
    service.session.commit.assert_not_awaited()


async def test_commit_failure_rolls_back(service):
    service.session.commit.side_effect = RuntimeError
    with pytest.raises(RuntimeError):
        await service.update_min_score(7, 80)
    service.session.rollback.assert_awaited_once()


@pytest.mark.parametrize(
    "timezone",
    [
        "America/Montevideo",
        "Europe/Berlin",
        "Asia/Tokyo",
        "Africa/Johannesburg",
        "Australia/Sydney",
    ],
)
async def test_global_iana_timezones(service, timezone):
    await service.update_timezone(7, timezone)
    service.repository.update_timezone.assert_awaited_once_with(7, timezone)
