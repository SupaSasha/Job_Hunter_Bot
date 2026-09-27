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
