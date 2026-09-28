from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock

import pytest
from redis.exceptions import LockNotOwnedError

from src.models.scheduling import CollectorStateORM
from src.services.collection import CollectionService
from src.services.locks import collector_lock


@pytest.mark.parametrize("acquired", [True, False])
async def test_lock_ownership_and_release_on_exception(acquired):
    redis = Mock()
    lock = redis.lock.return_value
    lock.acquire = AsyncMock(return_value=acquired)
    lock.release = AsyncMock()
    with pytest.raises(RuntimeError):
        async with collector_lock(redis, "remoteok") as result:
            assert result == acquired
            raise RuntimeError("failure")
    assert lock.release.await_count == int(acquired)
    redis.lock.assert_called_once_with(
        "collector:remoteok:lock", timeout=660, blocking=False, thread_local=False
    )


async def test_expired_lock_does_not_delete_new_owner():
    redis = Mock()
    redis.lock.return_value.acquire = AsyncMock(return_value=True)
    redis.lock.return_value.release = AsyncMock(side_effect=LockNotOwnedError)
    async with collector_lock(redis, "remoteok") as acquired:
        assert acquired


@pytest.fixture
def setup(monkeypatch):
    @asynccontextmanager
    async def sessions():
        yield None

    redis = Mock()
    redis.lock.return_value.acquire = AsyncMock(return_value=True)
    redis.lock.return_value.release = AsyncMock()
    now = datetime(2026, 9, 27, 6, tzinfo=UTC)
    service = CollectionService(
        sessions, redis, "America/Montevideo", clock=lambda: now
    )
    service.states = AsyncMock()
    service.states.get.return_value = CollectorStateORM(
        source="remoteok", next_run_at=now - timedelta(minutes=1)
    )
    collector = AsyncMock()
    collector.collect.return_value = []
    from src.collectors.registry import COLLECTORS

    monkeypatch.setitem(COLLECTORS, "remoteok", lambda: collector)
    return service, redis, collector, now


async def test_collection_updates_success_and_next_window(setup):
    service, _, collector, now = setup
    assert await service.collect_remoteok() == dict(
        received=0, new=0, duplicates=0, failed=0
    )
    final = service.states.update.call_args.kwargs
    assert final["last_status"] == "success"
    assert final["last_success_at"] == now and final["last_finished_at"] == now
    assert 13 <= final["next_run_at"].hour < 15
    collector.collect.assert_awaited_once()


async def test_failure_schedules_nonaggressive_retry(setup):
    service, _, collector, now = setup
    collector.collect.side_effect = RuntimeError("sensitive details")
    assert (await service.collect_remoteok())["status"] == "failed"
    final = service.states.update.call_args.kwargs
    assert final["last_status"] == "failed"
    assert final["last_error"] == "RuntimeError"
    assert final["next_run_at"] == now + timedelta(hours=1)
    assert "last_success_at" not in final


async def test_already_running_does_not_fetch_or_update_state(setup):
    service, redis, collector, _ = setup
    redis.lock.return_value.acquire.return_value = False
    assert (await service.collect_remoteok())["reason"] == "already_running"
    collector.collect.assert_not_awaited()
    service.states.ensure.assert_not_awaited()


async def test_queued_duplicate_uses_expected_schedule_to_skip_old_task(setup):
    service, _, collector, now = setup
    assert (await service.collect_remoteok(now.isoformat()))[
        "reason"
    ] == "stale_schedule"
    collector.collect.assert_not_awaited()
    service.states.update.assert_not_awaited()


async def test_wwr_has_own_state_window_and_same_pipeline(setup, monkeypatch):
    from zoneinfo import ZoneInfo

    from src.collectors.registry import COLLECTORS

    service, redis, collector, now = setup
    monkeypatch.setitem(COLLECTORS, "weworkremotely", lambda: collector)
    result = await service.collect("weworkremotely")
    assert result == dict(received=0, new=0, duplicates=0, failed=0)
    service.states.ensure.assert_awaited_once_with(
        "weworkremotely", now, "America/Montevideo"
    )
    assert service.states.update.call_args.args == ("weworkremotely",)
    local = service.states.update.call_args.kwargs["next_run_at"].astimezone(
        ZoneInfo("America/Montevideo")
    )
    assert 4 <= local.hour < 6
    assert redis.lock.call_args.args == ("collector:weworkremotely:lock",)


async def test_source_locks_are_independent():
    held = set()

    class Lock:
        def __init__(self, key):
            self.key = key

        async def acquire(self):
            if self.key in held:
                return False
            held.add(self.key)
            return True

        async def release(self):
            held.remove(self.key)

    redis = Mock()
    redis.lock.side_effect = lambda key, **kwargs: Lock(key)
    async with collector_lock(redis, "remoteok") as first:
        async with collector_lock(redis, "remoteok") as duplicate:
            async with collector_lock(redis, "weworkremotely") as second:
                assert first and second and not duplicate
    assert held == set()


async def test_retry_after_extends_scheduler_cooldown(setup):
    from src.collectors.base import CollectionError

    service, _, collector, now = setup
    collector.collect.side_effect = CollectionError(
        "rate limited", retry_at=now + timedelta(hours=12)
    )
    await service.collect_remoteok()
    assert service.states.update.call_args.kwargs["next_run_at"] == now + timedelta(
        hours=12
    )


async def test_invalid_source_never_acquires_lock(setup):
    service, redis, _, _ = setup
    with pytest.raises(ValueError):
        await service.collect("future-source")
    redis.lock.assert_not_called()
