import logging
from unittest.mock import AsyncMock

import pytest

from src.bot.callbacks import CallbackHandler, parse_callback_data
from src.bot.client import TelegramAPIError, TelegramClient
from src.models.job import JobORM
from src.models.user import UserORM
from src.repositories.jobs import JobRepository
from src.repositories.users import UserRepository
from src.services.feedback import FeedbackService


@pytest.mark.parametrize(
    ("data", "feedback_type"), [("save:42", "saved"), ("reject:42", "rejected")]
)
def test_parse_callback_data(data, feedback_type) -> None:
    parsed = parse_callback_data(data)
    assert parsed.job_id == 42
    assert parsed.feedback_type == feedback_type


@pytest.mark.parametrize(
    "data",
    [
        "foo:42",
        "save:",
        "save:abc",
        ":",
        "",
        "random-text",
        "save:0",
        "save:-1",
        "save:+1",
        "save:01",
        "save: 42",
        "save:42\n",
        "save:42:1",
        "save:٤٢",
        "save:2147483648",
        "save:" + "9" * 10000,
        None,
        42,
        {},
    ],
)
def test_invalid_callback_data_returns_none(data) -> None:
    assert parse_callback_data(data) is None


def test_max_postgres_job_id() -> None:
    assert parse_callback_data("save:2147483647").job_id == 2147483647


@pytest.fixture
def handler():
    users = AsyncMock(spec=UserRepository)
    users.get_by_telegram_id.return_value = UserORM(
        id=2, telegram_id=123, is_active=True
    )
    jobs = AsyncMock(spec=JobRepository)
    jobs.get_by_id.return_value = JobORM(id=42)
    return CallbackHandler(
        users, jobs, AsyncMock(spec=FeedbackService), AsyncMock(spec=TelegramClient)
    )


def callback(data="save:42"):
    return {
        "id": "query-1",
        "from": {"id": 123, "first_name": "PRIVATE_NAME"},
        "message": {"chat": {"id": -999}},
        "data": data,
    }


@pytest.mark.parametrize(
    ("data", "feedback_type", "text"),
    [
        ("save:42", "saved", "Вакансия сохранена"),
        ("reject:42", "rejected", "Отмечено как не подходящее"),
    ],
)
async def test_successful_callback(handler, data, feedback_type, text, caplog):
    events = []

    async def save(*args):
        events.append("save")

    async def answer(*args, **kwargs):
        events.append("answer")

    handler.feedback.set_feedback.side_effect = save
    handler.client.answer_callback_query.side_effect = answer
    with caplog.at_level(logging.INFO):
        await handler.handle(callback(data))
    handler.users.get_by_telegram_id.assert_awaited_once_with(123)
    handler.jobs.get_by_id.assert_awaited_once_with(42)
    handler.feedback.set_feedback.assert_awaited_once_with(2, 42, feedback_type)
    handler.client.answer_callback_query.assert_awaited_once_with("query-1", text=text)
    handler.client.send_message.assert_not_awaited()
    assert events == ["save", "answer"]
    assert "PRIVATE_NAME" not in caplog.text
    assert "query-1" not in caplog.text
    assert "Feedback saved" in caplog.text


async def test_unknown_user_is_not_created(handler) -> None:
    handler.users.get_by_telegram_id.return_value = None
    await handler.handle(callback())
    handler.users.add.assert_not_awaited()
    handler.jobs.get_by_id.assert_not_awaited()
    handler.feedback.set_feedback.assert_not_awaited()
    handler.client.answer_callback_query.assert_awaited_once_with(
        "query-1", text="User is not registered"
    )


async def test_inactive_user(handler) -> None:
    handler.users.get_by_telegram_id.return_value.is_active = False
    await handler.handle(callback())
    handler.feedback.set_feedback.assert_not_awaited()
    handler.client.answer_callback_query.assert_awaited_once_with(
        "query-1", text="User is inactive"
    )


async def test_missing_job(handler) -> None:
    handler.jobs.get_by_id.return_value = None
    await handler.handle(callback())
    handler.feedback.set_feedback.assert_not_awaited()
    handler.client.answer_callback_query.assert_awaited_once_with(
        "query-1", text="Vacancy not found"
    )


@pytest.mark.parametrize("data", ["foo:42", "save:", "save:abc", "", None])
async def test_invalid_action_is_answered(handler, data) -> None:
    await handler.handle(callback(data))
    handler.users.get_by_telegram_id.assert_not_awaited()
    handler.feedback.set_feedback.assert_not_awaited()
    handler.client.answer_callback_query.assert_awaited_once_with(
        "query-1", text="Invalid callback"
    )


@pytest.mark.parametrize("sender", [None, {}, {"id": True}, {"id": "123"}, {"id": -1}])
async def test_invalid_sender_is_answered(handler, sender) -> None:
    query = callback()
    query["from"] = sender
    await handler.handle(query)
    handler.feedback.set_feedback.assert_not_awaited()
    handler.client.answer_callback_query.assert_awaited_once()


@pytest.mark.parametrize("query", [None, [], {}, {"id": ""}, {"id": 123}])
async def test_missing_callback_id_does_not_raise(handler, query) -> None:
    await handler.handle(query)
    handler.client.answer_callback_query.assert_not_awaited()
    handler.feedback.set_feedback.assert_not_awaited()


async def test_expired_acknowledgement_does_not_replay_saved_feedback(handler) -> None:
    handler.client.answer_callback_query.side_effect = TelegramAPIError(
        "HTTP error: 400"
    )
    await handler.handle(callback())
    handler.feedback.set_feedback.assert_awaited_once_with(2, 42, "saved")


async def test_database_failure_propagates_without_success_popup(handler) -> None:
    handler.feedback.set_feedback.side_effect = RuntimeError("database unavailable")
    with pytest.raises(RuntimeError):
        await handler.handle(callback())
    handler.client.answer_callback_query.assert_not_awaited()
