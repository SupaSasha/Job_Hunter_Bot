from unittest.mock import AsyncMock

import pytest

from src.bot.updates import route_update


async def test_routes_command_messages():
    commands, callbacks = AsyncMock(), AsyncMock()
    message = {"text": "/start", "from": {"id": 1}}
    await route_update({"message": message}, commands=commands, callbacks=callbacks)
    commands.handle.assert_awaited_once_with(message)
    callbacks.handle.assert_not_awaited()


async def test_callbacks_keep_existing_route():
    commands, callbacks = AsyncMock(), AsyncMock()
    callback = {"data": "save:42"}
    await route_update(
        {"callback_query": callback}, commands=commands, callbacks=callbacks
    )
    callbacks.handle.assert_awaited_once_with(callback)
    commands.handle.assert_not_awaited()


@pytest.mark.parametrize(
    "update",
    [
        {},
        {"message": None},
        {"message": {"text": "hello"}},
        {"message": {"photo": []}},
        {"edited_message": {"text": "/collect"}},
    ],
)
async def test_unrelated_updates_are_ignored(update):
    commands, callbacks = AsyncMock(), AsyncMock()
    await route_update(update, commands=commands, callbacks=callbacks)
    commands.handle.assert_not_awaited()
    callbacks.handle.assert_not_awaited()
