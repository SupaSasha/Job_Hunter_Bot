import logging
from unittest.mock import AsyncMock

import pytest

from src.bot.client import TelegramAPIError, TelegramClient
from src.bot.filters import LIST_EDITORS, ROOT_ITEMS, FiltersHandler, render_screen
from src.bot.pending_input import PendingInput, PendingInputStore
from src.bot.updates import route_update
from src.i18n import Language
from src.models.user import UserORM
from src.models.user_filter import UserFilterORM
from src.repositories.users import UserRepository
from src.services.user_filters import (
    FiltersUnavailable,
    UserFilterService,
    filter_defaults,
    filters_to_dto,
)


@pytest.mark.parametrize("language", [Language.EN, Language.ES])
def test_usajobs_available_but_unselected_in_sources_menu(language):
    filters = filters_to_dto(UserFilterORM(user_id=7, **filter_defaults()), "UTC")
    _, markup = render_screen(filters, "sources", language)
    rows = [row[0] for row in markup["inline_keyboard"]]
    assert {"text": "❌ USAJOBS", "callback_data": "filters:sources:usajobs"} in rows
    filters.sources.append("usajobs")
    _, markup = render_screen(filters, "sources", language)
    assert markup["inline_keyboard"][-2][0]["text"] == "✅ USAJOBS"


def message(text="python", sender_id=123, chat_type="private"):
    return {
        "text": text,
        "from": {"id": sender_id},
        "chat": {"id": sender_id, "type": chat_type},
    }


def callback(data, sender_id=123):
    return {
        "id": "query1",
        "from": {"id": sender_id},
        "data": data,
        "message": {"message_id": 42, "chat": {"id": sender_id, "type": "private"}},
    }


@pytest.fixture
def handler(fake_redis):
    users = AsyncMock(spec=UserRepository)
    users.get_by_telegram_id.return_value = UserORM(
        id=7, telegram_id=123, is_active=True
    )
    service = AsyncMock(spec=UserFilterService)
    filters = filters_to_dto(UserFilterORM(user_id=7, **filter_defaults()), "UTC")
    filters.keywords = ["backend"]
    filters.required_technologies = ["javascript"]
    filters.preferred_technologies = ["redis"]
    filters.min_salary, filters.currency = 2500, "USD"
    for method in (
        "get_filters",
        "update_list",
        "toggle",
        "update_min_salary",
        "update_currency",
        "update_timezone_tolerance",
        "reset",
    ):
        getattr(service, method).return_value = filters
    return FiltersHandler(
        users, service, AsyncMock(spec=TelegramClient), PendingInputStore(fake_redis)
    )


async def test_filters_show_saved_values_and_only_job_settings(handler):
    await handler.pending.set(123, PendingInput("filters:keywords", 10))
    await handler.show(7, 123)
    text, markup = handler.client.send_message.call_args.args[1:]
    assert "backend" in text and "javascript" in text and "USD 2500" in text
    assert "python" not in text
    assert (
        "Digest time" not in text
        and "Minimum score" not in text
        and "Plan:" not in text
    )
    assert "Timezone:" not in text
    assert "Timezone tolerance: ±2h" in text
    assert [row[0]["callback_data"] for row in markup["inline_keyboard"]] == [
        f"filters:{key}" for _, key in ROOT_ITEMS
    ]
    assert await handler.pending.get(123) is None


@pytest.mark.parametrize(
    "screen",
    [key for _, key in ROOT_ITEMS]
    + ["back", "currency", "blacklist_words", "blacklist_companies"],
)
async def test_all_screens_edit_existing_message(handler, screen):
    await handler.handle(callback(f"filters:{screen}"))
    handler.client.edit_message_text.assert_awaited_once()
    assert handler.client.edit_message_text.call_args.args[:2] == (123, 42)
    handler.client.send_message.assert_not_awaited()
    assert handler.client.answer_callback_query.call_args.args == ("query1", None)


@pytest.mark.parametrize(
    "screen,field", [(screen, field) for screen, (field, _) in LIST_EDITORS.items()]
)
@pytest.mark.parametrize("operation", ["add", "remove"])
async def test_all_text_editors_pending_and_commit(handler, screen, field, operation):
    await handler.handle(callback(f"filters:{screen}:{operation}"))
    state = await handler.pending.get(123)
    assert state == PendingInput(f"filters:{screen}", 42, operation)
    assert "separated by commas" in handler.client.edit_message_text.call_args.args[2]
    await handler.handle_input(message(" Python, Redis "))
    handler.service.update_list.assert_awaited_once_with(
        7, field, operation, " Python, Redis "
    )
    assert await handler.pending.get(123) is None
    assert "updated" in handler.client.edit_message_text.call_args.args[2]
    assert handler.client.edit_message_text.await_count == 2


@pytest.mark.parametrize(
    "screen,field", [(screen, field) for screen, (field, _) in LIST_EDITORS.items()]
)
async def test_clear_list_does_not_start_text_input(handler, screen, field):
    await handler.handle(callback(f"filters:{screen}:clear"))
    handler.service.update_list.assert_awaited_once_with(7, field, "clear")
    assert await handler.pending.get(123) is None


@pytest.mark.parametrize(
    "data,field,value",
    [
        ("filters:regions:worldwide", "allowed_regions", "worldwide"),
        ("filters:employment:full_time", "employment_types", "full_time"),
        ("filters:experience:junior", "experience_levels", "junior"),
        ("filters:sources:remoteok", "sources", "remoteok"),
    ],
)
async def test_toggle_callbacks(handler, data, field, value):
    await handler.handle(callback(data))
    handler.service.toggle.assert_awaited_once_with(7, field, value)
    assert "updated" in handler.client.edit_message_text.call_args.args[2]


@pytest.mark.parametrize("field", ["remote_only", "exclude_us_only"])
async def test_boolean_callbacks(handler, field):
    await handler.handle(callback(f"filters:{field}"))
    handler.service.toggle.assert_awaited_once_with(7, field)
    assert (
        "Select allowed regions" in handler.client.edit_message_text.call_args.args[2]
    )


async def test_salary_pending_valid_error_and_clear(handler):
    await handler.handle(callback("filters:min_salary"))
    assert (await handler.pending.get(123)).action == "filters:min_salary"
    handler.service.update_min_salary.side_effect = ValueError(
        "Send a whole number without currency symbols."
    )
    await handler.handle_input(message("$2500"))
    assert await handler.pending.get(123) is not None
    assert "Try again" in handler.client.edit_message_text.call_args.args[2]
    handler.service.update_min_salary.side_effect = None
    await handler.handle_input(message("2500"))
    assert handler.service.update_min_salary.call_args.args == (7, "2500")
    assert await handler.pending.get(123) is None
    await handler.handle(callback("filters:salary:clear"))
    assert handler.service.update_min_salary.call_args.args == (7, None)


@pytest.mark.parametrize(
    "value,currency", [("USD", "USD"), ("EUR", "EUR"), ("UYU", "UYU"), ("Any", None)]
)
async def test_currency_callback(handler, value, currency):
    await handler.handle(callback(f"filters:currency:{value}"))
    handler.service.update_currency.assert_awaited_once_with(7, currency)


async def test_reset_requires_confirm_and_cancel_preserves_settings(handler):
    await handler.handle(callback("filters:reset"))
    handler.service.reset.assert_not_awaited()
    assert (
        "Reset all job filters to defaults?"
        in handler.client.edit_message_text.call_args.args[2]
    )
    await handler.handle(callback("filters:back"))
    handler.service.reset.assert_not_awaited()
    await handler.handle(callback("filters:reset:confirm"))
    handler.service.reset.assert_awaited_once_with(7)


@pytest.mark.parametrize("hours", range(5))
async def test_tolerance_callback(handler, hours):
    await handler.handle(callback(f"filters:tz_tol:{hours}"))
    handler.service.update_timezone_tolerance.assert_awaited_once_with(7, hours)


async def test_source_rejection_keeps_screen(handler):
    handler.service.toggle.side_effect = ValueError(
        "At least one source must be enabled."
    )
    await handler.handle(callback("filters:sources:remoteok"))
    handler.client.answer_callback_query.assert_awaited_once_with(
        "query1", "At least one source must be enabled."
    )
    handler.client.edit_message_text.assert_not_awaited()


async def test_cancel_and_navigation_clear_pending(handler):
    await handler.handle(callback("filters:reqtech:add"))
    await handler.cancel(123)
    handler.client.send_message.assert_awaited_once_with(123, "Input cancelled.")
    assert await handler.pending.get(123) is None
    await handler.handle(callback("filters:reqtech:add"))
    await handler.handle(callback("filters:regions"))
    assert await handler.pending.get(123) is None


@pytest.mark.parametrize(
    "command", ["/filters", "/cancel", "/help", "/unknown", "/filters@OtherBot"]
)
async def test_slash_command_precedence(handler, command):
    commands, callbacks = AsyncMock(), AsyncMock()
    await handler.handle(callback("filters:keywords:add"))
    await route_update(
        {"message": message(command)},
        commands=commands,
        callbacks=callbacks,
        filters=handler,
    )
    commands.handle.assert_awaited_once()
    handler.service.update_list.assert_not_awaited()


async def test_plain_text_routes_to_pending_input(handler):
    await handler.handle(callback("filters:keywords:add"))
    await route_update(
        {"message": message("python")},
        commands=AsyncMock(),
        callbacks=AsyncMock(),
        filters=handler,
    )
    handler.service.update_list.assert_awaited_once_with(7, "keywords", "add", "python")


async def test_filter_callback_namespace_is_separate():
    filters, settings, callbacks = AsyncMock(), AsyncMock(), AsyncMock()
    payload = callback("filters:regions")
    await route_update(
        {"callback_query": payload},
        commands=AsyncMock(),
        callbacks=callbacks,
        settings=settings,
        filters=filters,
    )
    filters.handle.assert_awaited_once_with(payload)
    settings.handle.assert_not_awaited()
    callbacks.handle.assert_not_awaited()


async def test_no_pending_or_expired_state_ignores_plain_text(handler):
    await handler.handle_input(message("python"))
    await handler.pending.set(123, PendingInput("filters:keywords", 42))
    await handler.pending.redis.delete(handler.pending.key(123))
    await handler.handle_input(message("python"))
    handler.service.update_list.assert_not_awaited()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: c["from"].update(id=999),
        lambda c: c["from"].update(is_bot=True),
        lambda c: c["message"]["chat"].update(type="group"),
        lambda c: c["message"].update(message_id=0),
        lambda c: c["from"].update(id=True),
    ],
)
async def test_invalid_callback_identity_does_not_access_filters(handler, mutate):
    payload = callback("filters:reset:confirm")
    mutate(payload)
    await handler.handle(payload)
    handler.service.get_filters.assert_not_awaited()
    handler.service.reset.assert_not_awaited()
    handler.client.answer_callback_query.assert_awaited_once()


@pytest.mark.parametrize(
    "user", [None, UserORM(id=7, telegram_id=123, is_active=False)]
)
async def test_missing_or_inactive_user_no_input_writes(handler, user):
    handler.users.get_by_telegram_id.return_value = user
    await handler.pending.set(123, PendingInput("filters:keywords", 42))
    await handler.handle_input(message("python"))
    await handler.handle(callback("filters:reset:confirm"))
    handler.service.get_filters.assert_not_awaited()
    handler.service.update_list.assert_not_awaited()
    handler.service.reset.assert_not_awaited()


async def test_committed_input_is_not_replayed_after_edit_failure(handler, caplog):
    await handler.pending.set(123, PendingInput("filters:reqtech", 42, "remove"))
    handler.client.edit_message_text.side_effect = TelegramAPIError("private token")
    with caplog.at_level(logging.WARNING):
        await handler.handle_input(message("python"))
        await handler.handle_input(message("python"))
    handler.service.update_list.assert_awaited_once()
    assert await handler.pending.get(123) is None
    assert "private token" not in caplog.text


async def test_callback_failure_does_not_expose_details(handler, caplog):
    handler.service.get_filters.side_effect = RuntimeError("private credentials")
    with caplog.at_level(logging.WARNING):
        await handler.handle(callback("filters:regions"))
    assert "private credentials" not in caplog.text
    assert (
        "private credentials"
        not in handler.client.answer_callback_query.call_args.args[1]
    )


async def test_unavailable_filters_show_friendly_message(handler):
    handler.service.get_filters.side_effect = FiltersUnavailable
    await handler.show(7, 123)
    assert (
        handler.client.send_message.call_args.args[1]
        == "Job filters are not available yet."
    )


def test_menu_size_and_callback_limits():
    row = UserFilterORM(user_id=7, **filter_defaults())
    for field, _ in LIST_EDITORS.values():
        setattr(row, field, ["😀" * 100 for _ in range(50)])
    filters = filters_to_dto(row, "UTC")
    for screen in [key for _, key in ROOT_ITEMS] + list(LIST_EDITORS) + ["currency"]:
        text, markup = render_screen(filters, screen)
        assert (
            len(("✅ Job filters updated.\n\n" + text).encode("utf-16-le")) // 2 < 4096
        )
        assert all(
            len(b["callback_data"].encode()) <= 64
            for row in markup["inline_keyboard"]
            for b in row
        )


@pytest.mark.parametrize("value", ["JPY", "GBP", "BRL"])
async def test_custom_currency_pending_input(handler, value):
    await handler.handle(callback("filters:currency:Other"))
    assert (await handler.pending.get(123)).action == "filters:custom_currency"
    await handler.handle_input(message(value))
    handler.service.update_currency.assert_awaited_once_with(7, value)
    assert await handler.pending.get(123) is None


async def test_countries_editor_pending_and_clear(handler):
    handler.service.update_countries.return_value = await handler.service.get_filters(7)
    await handler.handle(callback("filters:countries:add"))
    assert (await handler.pending.get(123)).action == "filters:countries"
    await handler.handle_input(message("Uruguay, Spain, Canada"))
    handler.service.update_countries.assert_awaited_with(
        7, "add", "Uruguay, Spain, Canada"
    )
    assert await handler.pending.get(123) is None
    await handler.handle(callback("filters:countries:clear"))
    handler.service.update_countries.assert_awaited_with(7, "clear")


async def test_invalid_custom_currency_keeps_pending_for_retry(handler):
    from src.i18n import LocalizedValidationError

    await handler.handle(callback("filters:currency:Other"))
    handler.service.update_currency.side_effect = LocalizedValidationError(
        "error.currency"
    )
    await handler.handle_input(message("DOLLAR"))
    assert (await handler.pending.get(123)).action == "filters:custom_currency"
    assert "Invalid currency" in handler.client.edit_message_text.call_args.args[2]


@pytest.mark.parametrize("language", [Language.EN, Language.ES])
def test_global_region_and_currency_menu_options(handler, language):
    from src.schemas.filters import UserFilterDTO

    _, regions = render_screen(UserFilterDTO(), "regions", language)
    data = {item["callback_data"] for row in regions["inline_keyboard"] for item in row}
    assert "filters:countries" in data
    assert "filters:regions:uruguay" not in data
    _, currency = render_screen(UserFilterDTO(), "currency", language)
    data = {
        item["callback_data"] for row in currency["inline_keyboard"] for item in row
    }
    assert {
        "filters:currency:GBP",
        "filters:currency:BRL",
        "filters:currency:Other",
        "filters:currency:Any",
    } <= data
