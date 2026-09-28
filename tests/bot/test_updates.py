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


@pytest.mark.parametrize(
    "data", ["settings:back", "settings:foobar", "tz:UTC", "time:0800", "score:80"]
)
async def test_settings_callbacks_have_separate_route(data):
    commands, callbacks, settings = AsyncMock(), AsyncMock(), AsyncMock()
    payload = {"data": data}
    await route_update(
        {"callback_query": payload},
        commands=commands,
        callbacks=callbacks,
        settings=settings,
    )
    settings.handle.assert_awaited_once_with(payload)
    callbacks.handle.assert_not_awaited()


@pytest.mark.parametrize("data", ["save:42", "reject:42"])
async def test_feedback_keeps_route_with_settings_enabled(data):
    commands, callbacks, settings = AsyncMock(), AsyncMock(), AsyncMock()
    payload = {"data": data}
    await route_update(
        {"callback_query": payload},
        commands=commands,
        callbacks=callbacks,
        settings=settings,
    )
    callbacks.handle.assert_awaited_once_with(payload)
    settings.handle.assert_not_awaited()
