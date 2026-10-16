import random
from datetime import UTC, datetime, time, timedelta
from unittest.mock import AsyncMock, Mock
from zoneinfo import ZoneInfo

import pytest

from src.models.scheduling import (
    CollectorStateORM,
    UserNotificationSettingsORM,
    UserSubscriptionORM,
)
from src.models.user import UserORM
from src.services.collector_policy import COLLECTOR_POLICIES, next_collection
from src.services.entitlements import (
    EffectiveNotificationSettings,
    EntitlementService,
    digest_due,
)
from src.services.scheduler import SchedulerService

ZONE = "America/Montevideo"
NOW = datetime(2026, 9, 27, 12, 2, tzinfo=UTC)


@pytest.mark.parametrize(
    "local_hour,initial,expected_hour,day",
    [
        (1, True, 2, 27),
        (3, True, 3, 27),
        (3, False, 10, 27),
        (4, False, 10, 27),
        (12, False, 18, 27),
        (20, False, 2, 28),
    ],
)
def test_next_window_utc_storage(local_hour, initial, expected_hour, day):
    now = datetime(2026, 9, 27, local_hour, tzinfo=ZoneInfo(ZONE))
    result = next_collection(
        now, COLLECTOR_POLICIES["remoteok"], ZONE, initial=initial, rng=random.Random(7)
    )
    local = result.astimezone(ZoneInfo(ZONE))
    assert local.day == day
    assert (
        expected_hour <= local.hour < (4 if expected_hour == 3 else expected_hour + 2)
    )
    assert result.tzinfo == UTC
    assert result >= now


def test_jitter_changes_with_seed_and_stays_in_window():
    values = {
        next_collection(
            NOW, COLLECTOR_POLICIES["remoteok"], ZONE, rng=random.Random(seed)
        )
        for seed in range(20)
    }
    assert len(values) > 1
    assert all(10 <= value.astimezone(ZoneInfo(ZONE)).hour < 12 for value in values)


def test_naive_clock_rejected():
    with pytest.raises(ValueError):
        next_collection(datetime(2026, 9, 27), COLLECTOR_POLICIES["remoteok"], ZONE)


def preferences():
    return UserNotificationSettingsORM(
        timezone=ZONE,
        digest_time=time(11, 30),
        min_score=42,
        max_jobs_per_digest=3,
        digest_enabled=True,
    )


@pytest.mark.parametrize(
    "status,end,premium",
    [
        ("trial", NOW + timedelta(seconds=1), True),
        ("trial", NOW, False),
        ("trial", NOW - timedelta(days=1), False),
        ("trial", None, False),
        ("active", None, True),
        ("active", NOW + timedelta(seconds=1), True),
        ("active", NOW, False),
        ("expired", NOW + timedelta(days=1), False),
    ],
)
def test_entitlements_boundaries_and_preserved_preferences(status, end, premium):
    prefs = preferences()
    subscription = UserSubscriptionORM(
        status=status, trial_ends_at=end, subscription_ends_at=end
    )
    effective = EntitlementService().effective(prefs, subscription, NOW)
    assert effective.premium == premium
    assert effective.digest_time == (time(11, 30) if premium else time(9))
    assert effective.min_score == (42 if premium else 70)
    assert effective.timezone == ZONE and effective.max_jobs_per_digest == 3
    assert prefs.digest_time == time(11, 30) and prefs.min_score == 42


def test_free_defaults_configurable_and_no_subscription():
    effective = EntitlementService(
        free_digest_time=time(8), free_min_score=80
    ).effective(preferences(), None, NOW)
    assert effective.digest_time == time(8) and effective.min_score == 80


@pytest.mark.parametrize(
    "hour,minute,enabled,expected",
    [
        (8, 59, True, False),
        (9, 2, True, True),
        (9, 2, False, False),
    ],
)
def test_digest_due_local_date(hour, minute, enabled, expected):
    settings = EffectiveNotificationSettings(ZONE, time(9), 70, 10, enabled, False)
    now = datetime(2026, 9, 27, hour, minute, tzinfo=ZoneInfo(ZONE)).astimezone(UTC)
    assert digest_due(settings, now) is expected


def test_local_calendar_day_and_dst_repeated_hour():
    settings = EffectiveNotificationSettings(
        "America/New_York", time(1, 30), 70, 10, True, False
    )
    first = datetime(2026, 11, 1, 5, 40, tzinfo=UTC)
    second = datetime(2026, 11, 1, 6, 40, tzinfo=UTC)
    assert digest_due(settings, first)
    assert digest_due(settings, second)
    # Daily uniqueness is enforced by DigestRepository, not a caller-owned set.
    settings = EffectiveNotificationSettings(ZONE, time(22), 70, 10, True, False)
    assert digest_due(settings, datetime(2026, 9, 28, 2, tzinfo=UTC))


async def test_dispatch_uses_persisted_timestamp():
    publish = Mock()
    service = SchedulerService(None, publish, ZONE, EntitlementService())
    service.collectors = AsyncMock()
    due = NOW - timedelta(minutes=1)
    service.collectors.due.return_value = [
        CollectorStateORM(source="remoteok", next_run_at=due)
    ]
    for _ in range(2):
        assert await service.dispatch_collectors(NOW) == 1
    assert publish.call_args.kwargs["args"] == [due.isoformat()]
    assert publish.call_args.args == ("jobs.collect_remoteok",)
    assert len(publish.call_args_list) == 2
    service.collectors.update.assert_not_called()


async def test_digest_dispatches_users_and_skips_finished_day():
    service = SchedulerService(None, Mock(), ZONE, EntitlementService())
    service.digests = AsyncMock()
    prefs = preferences()
    service.digests.users.return_value = [
        (UserORM(id=17, telegram_id=123), prefs, None)
    ]
    service.digests.attempted.return_value = False
    assert await service.dispatch_digests(NOW) == 1
    service.publish.assert_called_once_with(
        "notifications.send_daily_digest", args=[17, "2026-09-27"]
    )
    service.digests.attempted.return_value = True
    assert await service.dispatch_digests(NOW) == 0


async def test_active_trial_custom_time_not_yet_due():
    service = SchedulerService(None, Mock(), ZONE, EntitlementService())
    service.digests = AsyncMock()
    service.digests.users.return_value = [
        (
            UserORM(id=17),
            preferences(),
            UserSubscriptionORM(status="trial", trial_ends_at=NOW + timedelta(days=1)),
        ),
    ]
    assert await service.dispatch_digests(NOW) == 0
    service.publish.assert_not_called()


@pytest.mark.parametrize(
    "hour,initial,start,day",
    [
        (3, True, 4, 27),
        (5, True, 5, 27),
        (5, False, 16, 27),
        (6, False, 16, 27),
        (18, False, 4, 28),
    ],
)
def test_wwr_windows_and_independent_jitter(hour, initial, start, day):
    now = datetime(2026, 9, 27, hour, tzinfo=ZoneInfo(ZONE))
    values = [
        next_collection(
            now,
            COLLECTOR_POLICIES["weworkremotely"],
            ZONE,
            initial=initial,
            rng=random.Random(seed),
        )
        for seed in range(10)
    ]
    assert len(set(values)) > 1
    for value in values:
        local = value.astimezone(ZoneInfo(ZONE))
        assert local.day == day
        assert start <= local.hour < (6 if start == 5 else start + 2)
        assert value.tzinfo == UTC


async def test_dispatch_routes_active_collectors_without_future_sources():
    service = SchedulerService(None, Mock(), ZONE, EntitlementService())
    service.collectors = AsyncMock()
    service.collectors.due.return_value = [
        CollectorStateORM(source=source, next_run_at=NOW)
        for source in (
            "remoteok",
            "weworkremotely",
            "getonboard",
            "himalayas",
            "jobicy",
            "the_muse",
            "hacker_news",
            "jooble",
            "unknown",
        )
    ]
    assert await service.dispatch_collectors(NOW) == 8
    assert [call.args[0] for call in service.publish.call_args_list] == [
        "jobs.collect_remoteok",
        "jobs.collect_weworkremotely",
        "jobs.collect_getonboard",
        "jobs.collect_himalayas",
        "jobs.collect_jobicy",
        "jobs.collect_the_muse",
        "jobs.collect_hacker_news",
        "jobs.collect_jooble",
    ]
    assert [call.args[0] for call in service.collectors.ensure.call_args_list] == [
        "remoteok",
        "getonboard",
        "weworkremotely",
        "himalayas",
        "jobicy",
        "the_muse",
        "hacker_news",
        "jooble",
    ]


@pytest.mark.parametrize(
    "hour,initial,start,day",
    [(5, True, 6, 27), (7, True, 7, 27), (7, False, 20, 27), (22, False, 6, 28)],
)
def test_getonboard_windows(hour, initial, start, day):
    now = datetime(2026, 9, 27, hour, tzinfo=ZoneInfo(ZONE))
    values = {
        next_collection(
            now,
            COLLECTOR_POLICIES["getonboard"],
            ZONE,
            initial=initial,
            rng=random.Random(seed),
        )
        for seed in range(10)
    }
    assert len(values) > 1
    for value in values:
        local = value.astimezone(ZoneInfo(ZONE))
        assert local.day == day
        assert start <= local.hour < (8 if start == 7 else start + 2)


async def test_scheduler_recovers_stale_before_checking_reservations():
    service = SchedulerService(None, Mock(), ZONE, EntitlementService())
    service.digests = AsyncMock()
    service.digests.users.return_value = []
    await service.dispatch_digests(NOW)
    service.digests.recover_stale.assert_awaited_once_with(NOW)


@pytest.mark.parametrize(
    "hour,initial,start,day",
    [
        (5, True, 6, 27),
        (6, True, 6, 27),
        (6, False, 14, 27),
        (15, False, 22, 27),
        (23, False, 6, 28),
    ],
)
def test_himalayas_three_one_hour_windows_and_independent_jitter(
    hour, initial, start, day
):
    now = datetime(2026, 9, 27, hour, tzinfo=ZoneInfo(ZONE))
    values = [
        next_collection(
            now,
            COLLECTOR_POLICIES["himalayas"],
            ZONE,
            initial=initial,
            rng=random.Random(seed),
        )
        for seed in range(10)
    ]
    assert len(set(values)) > 1
    for value in values:
        local = value.astimezone(ZoneInfo(ZONE))
        assert local.day == day and start <= local.hour < start + 1


@pytest.mark.parametrize(
    "hour,initial,start,day",
    [
        (2, True, 3, 27),
        (3, True, 3, 27),
        (3, False, 11, 27),
        (12, False, 19, 27),
        (20, False, 3, 28),
    ],
)
def test_jobicy_windows_respect_daily_frequency(hour, initial, start, day):
    policy = COLLECTOR_POLICIES["jobicy"]
    assert policy.min_interval == timedelta(hours=1)
    now = datetime(2026, 9, 27, hour, tzinfo=ZoneInfo(ZONE))
    values = [
        next_collection(now, policy, ZONE, initial=initial, rng=random.Random(seed))
        for seed in range(10)
    ]
    assert len(set(values)) > 1
    for value in values:
        local = value.astimezone(ZoneInfo(ZONE))
        assert local.day == day and start <= local.hour < start + 1


@pytest.mark.parametrize(
    "hour,initial,start,day",
    [
        (6, True, 7, 27),
        (7, True, 7, 27),
        (7, False, 19, 27),
        (19, True, 19, 27),
        (20, False, 7, 28),
    ],
)
def test_the_muse_twice_daily_windows(hour, initial, start, day):
    policy = COLLECTOR_POLICIES["the_muse"]
    assert len(policy.windows) == 2 and policy.min_interval == timedelta(0)
    now = datetime(2026, 9, 27, hour, tzinfo=ZoneInfo(ZONE))
    values = [
        next_collection(now, policy, ZONE, initial=initial, rng=random.Random(seed))
        for seed in range(10)
    ]
    assert len(set(values)) > 1
    for value in values:
        local = value.astimezone(ZoneInfo(ZONE))
        assert local.day == day and start <= local.hour < start + 1


@pytest.mark.parametrize(
    "hour,initial,start,day",
    [
        (12, True, 13, 27),
        (13, True, 13, 27),
        (13, False, 13, 28),
        (14, False, 13, 28),
    ],
)
def test_hacker_news_once_daily_window(hour, initial, start, day):
    policy = COLLECTOR_POLICIES["hacker_news"]
    assert len(policy.windows) == 1
    now = datetime(2026, 9, 27, hour, tzinfo=ZoneInfo(ZONE))
    values = [
        next_collection(now, policy, ZONE, initial=initial, rng=random.Random(seed))
        for seed in range(10)
    ]
    assert len(set(values)) > 1
    for value in values:
        local = value.astimezone(ZoneInfo(ZONE))
        assert local.day == day and start <= local.hour < start + 1


@pytest.mark.parametrize(
    "hour,initial,start,day",
    [
        (8, True, 9, 27),
        (9, True, 9, 27),
        (9, False, 21, 27),
        (22, False, 9, 28),
    ],
)
def test_jooble_twice_daily_windows(hour, initial, start, day):
    policy = COLLECTOR_POLICIES["jooble"]
    assert len(policy.windows) == 2
    now = datetime(2026, 9, 27, hour, tzinfo=ZoneInfo(ZONE))
    values = [
        next_collection(now, policy, ZONE, initial=initial, rng=random.Random(seed))
        for seed in range(10)
    ]
    assert len(set(values)) > 1
    for value in values:
        local = value.astimezone(ZoneInfo(ZONE))
        assert local.day == day and start <= local.hour < start + 1
