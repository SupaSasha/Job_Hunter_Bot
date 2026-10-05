import asyncio
import json
import time
from unittest.mock import AsyncMock, patch

import pytest

from src.bot.client import TelegramAPIError, TelegramClient
from src.bot.polling import (
    OFFSET_MAX_AGE_SECONDS,
    OffsetCheckpoint,
    RedisOffsetStore,
    poll_updates,
)


async def test_offset_advances_and_duplicate_updates_are_ignored() -> None:
    client = AsyncMock(spec=TelegramClient)
    client.get_updates.side_effect = [
        [{"update_id": 11}, {"update_id": 10}],
        [{"update_id": 11}, {"update_id": 12, "message": {}}],
        asyncio.CancelledError(),
    ]
    handler = AsyncMock()
    with pytest.raises(asyncio.CancelledError):
        await poll_updates(client, handler)
    assert [call.args[0]["update_id"] for call in handler.await_args_list] == [
        10,
        11,
        12,
    ]
    assert [call.kwargs["offset"] for call in client.get_updates.await_args_list] == [
        None,
        12,
        13,
    ]
    assert all(
        call.kwargs["timeout"] == 30 for call in client.get_updates.await_args_list
    )


async def test_network_failure_retries_with_pause_and_same_offset() -> None:
    client = AsyncMock(spec=TelegramClient)
    client.get_updates.side_effect = [
        [{"update_id": 10}],
        TelegramAPIError("Telegram network error"),
        [],
        asyncio.CancelledError(),
    ]
    with patch("src.bot.polling.asyncio.sleep", new_callable=AsyncMock) as sleep:
        with pytest.raises(asyncio.CancelledError):
            await poll_updates(client, AsyncMock())
    sleep.assert_awaited_once_with(3.0)
    assert [call.kwargs["offset"] for call in client.get_updates.await_args_list] == [
        None,
        11,
        11,
        11,
    ]


async def test_failed_update_is_retried_before_later_updates() -> None:
    client = AsyncMock(spec=TelegramClient)
    client.get_updates.side_effect = [
        [{"update_id": 10}, {"update_id": 11}, {"update_id": 12}],
        [{"update_id": 11}, {"update_id": 12}],
        asyncio.CancelledError(),
    ]
    handler = AsyncMock(side_effect=[None, RuntimeError("database down"), None, None])
    with patch("src.bot.polling.asyncio.sleep", new_callable=AsyncMock) as sleep:
        with pytest.raises(asyncio.CancelledError):
            await poll_updates(client, handler)
    sleep.assert_awaited_once_with(3.0)
    assert [call.args[0]["update_id"] for call in handler.await_args_list] == [
        10,
        11,
        11,
        12,
    ]
    assert [call.kwargs["offset"] for call in client.get_updates.await_args_list] == [
        None,
        11,
        13,
    ]


async def test_cancellation_during_handling_is_not_swallowed() -> None:
    client = AsyncMock(spec=TelegramClient)
    client.get_updates.return_value = [{"update_id": 10}]
    with pytest.raises(asyncio.CancelledError):
        await poll_updates(client, AsyncMock(side_effect=asyncio.CancelledError()))
    client.get_updates.assert_awaited_once()


@pytest.mark.parametrize("kwargs", [{"timeout": 0}, {"retry_delay": 0}])
async def test_polling_rejects_busy_loop_configuration(kwargs) -> None:
    with pytest.raises(ValueError):
        await poll_updates(AsyncMock(), AsyncMock(), **kwargs)


@pytest.mark.parametrize(
    "payload",
    [{"message": {"text": "/collect"}}, {"callback_query": {"data": "save:1"}}],
)
async def test_poison_update_skipped_after_three_failures(payload, caplog):
    client = AsyncMock(spec=TelegramClient)
    batch = [{"update_id": 10, **payload}, {"update_id": 11}]
    client.get_updates.side_effect = [batch, batch, batch, asyncio.CancelledError()]
    handler = AsyncMock(side_effect=[RuntimeError("private")] * 3 + [None])
    store = AsyncMock()
    store.load.return_value = OffsetCheckpoint(10, time.time())
    with patch("src.bot.polling.asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(asyncio.CancelledError):
            await poll_updates(client, handler, offset_store=store)
    assert [c.args[0]["update_id"] for c in handler.await_args_list] == [10, 10, 10, 11]
    assert [c.args[0].offset for c in store.save.await_args_list] == [11, 12]
    assert "poison update 10" in caplog.text
    assert "private" not in caplog.text


@pytest.mark.parametrize(
    "payload",
    [
        {"message": {"text": "/collect"}},
        {"message": {"text": "/digest"}},
        {"callback_query": {"data": "save:1"}},
    ],
)
async def test_restart_loads_confirmed_offset_without_replaying_update(payload):
    class Store:
        offset = None

        async def load(self):
            return self.offset

        async def save(self, checkpoint):
            self.offset = checkpoint

    store = Store()
    handler = AsyncMock()
    command = {"update_id": 10, **payload}
    for _ in range(2):
        client = AsyncMock(spec=TelegramClient)
        client.get_updates.side_effect = [[command], asyncio.CancelledError()]
        with pytest.raises(asyncio.CancelledError):
            await poll_updates(client, handler, offset_store=store)
    handler.assert_awaited_once_with(command)
    assert client.get_updates.call_args_list[0].kwargs["offset"] == 11


async def test_redis_outage_pauses_without_replaying_handled_command():
    store = AsyncMock()
    store.load.side_effect = [
        ConnectionError("secret"),
        OffsetCheckpoint(10, time.time()),
    ]
    store.save.side_effect = [ConnectionError("secret"), None]
    client = AsyncMock(spec=TelegramClient)
    client.get_updates.side_effect = [[{"update_id": 10}], asyncio.CancelledError()]
    handler = AsyncMock()
    with patch("src.bot.polling.asyncio.sleep", new_callable=AsyncMock) as sleep:
        with pytest.raises(asyncio.CancelledError):
            await poll_updates(client, handler, offset_store=store)
    handler.assert_awaited_once()
    assert store.save.await_count == 2
    assert sleep.await_count == 2
    assert client.get_updates.call_args_list[-1].kwargs["offset"] == 11


async def test_offset_not_persisted_if_handler_cancelled():
    store = AsyncMock()
    store.load.return_value = OffsetCheckpoint(10, time.time())
    client = AsyncMock(spec=TelegramClient)
    client.get_updates.return_value = [{"update_id": 10}]
    with pytest.raises(asyncio.CancelledError):
        await poll_updates(
            client, AsyncMock(side_effect=asyncio.CancelledError()), offset_store=store
        )
    store.save.assert_not_awaited()


async def test_redis_offset_key_round_trip():
    redis = AsyncMock()
    redis.get.return_value = b'{"offset": 42, "saved_at": 1000}'
    store = RedisOffsetStore(redis, clock=lambda: 2000)
    assert await store.load() == OffsetCheckpoint(42, 1000)
    redis.set.assert_not_awaited()
    await store.save(OffsetCheckpoint(43, 2000))
    key, value = redis.set.await_args.args
    assert key == "telegram:polling:offset"
    assert json.loads(value) == {"offset": 43, "saved_at": 2000}


async def test_legacy_offset_migrates_once_without_losing_acknowledgement():
    redis = AsyncMock()
    redis.get.return_value = b"42"
    now = 1000
    store = RedisOffsetStore(redis, clock=lambda: now)
    assert await store.load() == OffsetCheckpoint(42, 1000)
    redis.get.return_value = redis.set.await_args.args[1]
    now = 2000
    assert await store.load() == OffsetCheckpoint(42, 1000)
    redis.set.assert_awaited_once()


@pytest.mark.parametrize(
    "payload",
    [
        b"-1",
        b"null",
        b"true",
        b"[]",
        b"not-json",
        b'{"offset": true, "saved_at": 1}',
        b'{"offset": 1}',
        b'{"offset": 1, "saved_at": -1}',
        b'{"offset": 1, "saved_at": NaN}',
    ],
)
async def test_invalid_checkpoint_is_not_treated_as_missing(payload):
    redis = AsyncMock()
    redis.get.return_value = payload
    with pytest.raises(ValueError):
        await RedisOffsetStore(redis).load()
    redis.set.assert_not_awaited()


async def test_stale_checkpoint_resets_before_first_request_after_restart():
    now = 10 * OFFSET_MAX_AGE_SECONDS
    redis = AsyncMock()
    redis.get.return_value = json.dumps(
        {"offset": 900000001, "saved_at": now - OFFSET_MAX_AGE_SECONDS}
    )
    store = RedisOffsetStore(redis, clock=lambda: now)
    client = AsyncMock(spec=TelegramClient)
    command = {"update_id": 100, "message": {"text": "/digest"}}
    client.get_updates.side_effect = [[command], asyncio.CancelledError()]
    handler = AsyncMock()
    with pytest.raises(asyncio.CancelledError):
        await poll_updates(client, handler, offset_store=store, clock=lambda: now)
    assert [c.kwargs["offset"] for c in client.get_updates.await_args_list] == [
        None,
        101,
    ]
    handler.assert_awaited_once_with(command)
    assert json.loads(redis.set.await_args.args[1]) == {"offset": 101, "saved_at": now}


async def test_fresh_checkpoint_survives_restart_without_refreshing_its_age():
    now = 10 * OFFSET_MAX_AGE_SECONDS
    store = AsyncMock()
    store.load.return_value = OffsetCheckpoint(42, now - OFFSET_MAX_AGE_SECONDS + 1)
    client = AsyncMock(spec=TelegramClient)

    async def get_updates(**kwargs):
        nonlocal now
        if client.get_updates.await_count == 1:
            assert kwargs["offset"] == 42
            now += 1
            return []
        assert kwargs["offset"] is None
        raise asyncio.CancelledError()

    client.get_updates.side_effect = get_updates
    with pytest.raises(asyncio.CancelledError):
        await poll_updates(client, AsyncMock(), offset_store=store, clock=lambda: now)
    store.save.assert_not_awaited()


async def test_checkpoint_expires_in_running_process_after_network_outage():
    now = 1000
    client = AsyncMock(spec=TelegramClient)
    commands = [{"update_id": 900}, {"update_id": 100}]

    async def get_updates(**kwargs):
        nonlocal now
        calls = client.get_updates.await_count
        if calls == 1:
            return [commands[0]]
        if calls == 2:
            assert kwargs["offset"] == 901
            now += OFFSET_MAX_AGE_SECONDS
            raise TelegramAPIError("Telegram network error")
        if calls == 3:
            assert kwargs["offset"] is None
            return [commands[1]]
        assert kwargs["offset"] == 101
        raise asyncio.CancelledError()

    client.get_updates.side_effect = get_updates
    handler = AsyncMock()
    with patch("src.bot.polling.asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(asyncio.CancelledError):
            await poll_updates(client, handler, clock=lambda: now)
    assert [c.args[0] for c in handler.await_args_list] == commands


async def test_redis_save_outage_does_not_refresh_acknowledgement_timestamp():
    now = 1000
    store = AsyncMock()
    store.load.return_value = None

    async def save(checkpoint):
        nonlocal now
        if store.save.await_count == 1:
            now += OFFSET_MAX_AGE_SECONDS
            raise ConnectionError("Redis unavailable")
        assert checkpoint == OffsetCheckpoint(901, 1000)

    store.save.side_effect = save
    client = AsyncMock(spec=TelegramClient)
    client.get_updates.side_effect = [[{"update_id": 900}], asyncio.CancelledError()]
    handler = AsyncMock()
    with patch("src.bot.polling.asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(asyncio.CancelledError):
            await poll_updates(client, handler, offset_store=store, clock=lambda: now)
    handler.assert_awaited_once()
    assert client.get_updates.await_args_list[-1].kwargs["offset"] is None
    assert store.save.await_args_list[0] == store.save.await_args_list[1]
