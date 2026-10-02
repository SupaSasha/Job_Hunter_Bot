import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from src.bot.client import TelegramAPIError, TelegramClient
from src.bot.polling import poll_updates


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
    store.load.return_value = 10
    with patch("src.bot.polling.asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(asyncio.CancelledError):
            await poll_updates(client, handler, offset_store=store)
    assert [c.args[0]["update_id"] for c in handler.await_args_list] == [10, 10, 10, 11]
    assert [c.args[0] for c in store.save.await_args_list] == [11, 12]
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

        async def save(self, offset):
            self.offset = offset

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
    store.load.side_effect = [ConnectionError("secret"), 10]
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
    store.load.return_value = 10
    client = AsyncMock(spec=TelegramClient)
    client.get_updates.return_value = [{"update_id": 10}]
    with pytest.raises(asyncio.CancelledError):
        await poll_updates(
            client, AsyncMock(side_effect=asyncio.CancelledError()), offset_store=store
        )
    store.save.assert_not_awaited()


async def test_redis_offset_key_round_trip():
    from src.bot.polling import RedisOffsetStore

    redis = AsyncMock()
    redis.get.return_value = b"42"
    store = RedisOffsetStore(redis)
    assert await store.load() == 42
    await store.save(43)
    redis.set.assert_awaited_once_with("telegram:polling:offset", 43)
