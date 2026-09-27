from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.client import TelegramAPIError
from src.models.notification import NotificationORM
from src.models.user import UserORM
from src.repositories.notifications import NotificationRepository
from src.schemas.job import JobDTO
from src.schemas.scoring import ScoreResult
from src.services.notifications import NotificationService


class FakeTelegramClient:
    def __init__(self, events: list) -> None:
        self.events = events
        self.calls = []
        self.error = None

    async def send_message(self, chat_id, text, reply_markup=None):
        self.events.append("send")
        self.calls.append((chat_id, text, reply_markup))
        if self.error:
            raise self.error
        return 1234


@pytest.fixture
def setup():
    events = []
    session = AsyncMock(spec=AsyncSession)
    session.commit.side_effect = lambda: events.append("commit")
    client = FakeTelegramClient(events)
    service = NotificationService(session, client)
    repository = AsyncMock(spec=NotificationRepository)
    repository.get_by_user_job.return_value = None

    async def add(notification):
        notification.id = 5
        events.append(("add", notification.status))
        return notification

    repository.add.side_effect = add
    service.repository = repository
    user = UserORM(id=2, telegram_id=1234567890123, is_active=True)
    job = JobDTO(
        source="remoteok",
        external_id="1",
        title="Python Developer",
        company="Acme",
        url="https://example.com/jobs/1",
    )
    kwargs = dict(user=user, job_id=7, job=job, score=ScoreResult(score=87))
    return service, client, events, kwargs


def integrity_error(constraint="uq_notifications_user_job", sqlstate="23505"):
    class DatabaseError(Exception):
        pass

    cause = DatabaseError()
    cause.constraint_name = constraint
    original = DatabaseError()
    original.sqlstate = sqlstate
    original.__cause__ = cause
    return IntegrityError("INSERT", {}, original)


async def test_pending_is_committed_before_send_and_sent_persisted(setup) -> None:
    service, client, events, kwargs = setup
    result = await service.notify(**kwargs)
    assert events == [("add", "pending"), "commit", "send", "commit"]
    assert result.sent is True
    assert result.skipped is False
    assert result.telegram_message_id == 1234
    row = service.repository.add.call_args.args[0]
    assert (row.user_id, row.job_id, row.score) == (2, 7, 87)
    assert client.calls[0][0] == 1234567890123
    assert "Python Developer" in client.calls[0][1]
    assert client.calls[0][2]["inline_keyboard"][1][0]["callback_data"] == "save:7"
    service.repository.mark_sent.assert_awaited_once_with(5, 1234)
    service.repository.mark_failed.assert_not_awaited()


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        ("sent", "already_sent"),
        ("pending", "already_pending"),
        ("failed", "previous_failed"),
    ],
)
async def test_existing_attempt_is_never_resent(setup, status, reason) -> None:
    service, client, events, kwargs = setup
    service.repository.get_by_user_job.return_value = NotificationORM(
        id=5, status=status, telegram_message_id=1234 if status == "sent" else None
    )
    result = await service.notify(**kwargs)
    assert result.sent is False
    assert result.skipped is True
    assert result.reason == reason
    assert client.calls == []
    service.repository.add.assert_not_awaited()
    service.session.rollback.assert_awaited_once()


async def test_telegram_failure_is_recorded(setup) -> None:
    service, client, events, kwargs = setup
    client.error = TelegramAPIError("Telegram request timed out")
    result = await service.notify(**kwargs)
    assert not result.sent and not result.skipped
    assert result.reason == "Telegram request timed out"
    assert events == [("add", "pending"), "commit", "send", "commit"]
    service.repository.mark_failed.assert_awaited_once_with(5)
    service.repository.mark_sent.assert_not_awaited()


async def test_unexpected_client_failure_is_recorded_and_reraised(setup) -> None:
    service, client, events, kwargs = setup
    client.error = RuntimeError("unexpected client error")
    with pytest.raises(RuntimeError, match="unexpected client"):
        await service.notify(**kwargs)
    service.repository.mark_failed.assert_awaited_once_with(5)
    service.repository.mark_sent.assert_not_awaited()


@pytest.mark.parametrize("boundary", ["add", "commit"])
@pytest.mark.parametrize("status", ["pending", "sent", "failed"])
async def test_duplicate_race_does_not_send(setup, boundary, status) -> None:
    service, client, events, kwargs = setup
    service.repository.get_by_user_job.side_effect = [
        None,
        NotificationORM(id=6, status=status),
    ]
    target = service.repository.add if boundary == "add" else service.session.commit
    target.side_effect = integrity_error()
    result = await service.notify(**kwargs)
    assert result.skipped and not result.sent
    assert client.calls == []
    assert service.session.rollback.await_count == 2


@pytest.mark.parametrize(
    ("constraint", "sqlstate"),
    [("other_unique", "23505"), ("uq_notifications_user_job", "23503")],
)
async def test_unrelated_integrity_error_propagates(
    setup, constraint, sqlstate
) -> None:
    service, client, events, kwargs = setup
    error = integrity_error(constraint, sqlstate)
    service.repository.add.side_effect = error
    with pytest.raises(IntegrityError) as caught:
        await service.notify(**kwargs)
    assert caught.value is error
    assert client.calls == []
    service.session.rollback.assert_awaited_once()


async def test_pending_commit_failure_prevents_send(setup) -> None:
    service, client, events, kwargs = setup
    service.session.commit.side_effect = RuntimeError("database unavailable")
    with pytest.raises(RuntimeError, match="database unavailable"):
        await service.notify(**kwargs)
    assert client.calls == []
    service.session.rollback.assert_awaited_once()


async def test_final_commit_failure_preserves_pending_reservation(setup) -> None:
    service, client, events, kwargs = setup
    service.session.commit.side_effect = [None, RuntimeError("database unavailable")]
    with pytest.raises(RuntimeError, match="database unavailable"):
        await service.notify(**kwargs)
    assert len(client.calls) == 1
    service.repository.mark_failed.assert_not_awaited()
    service.session.rollback.assert_awaited_once()


async def test_inactive_owner_is_skipped(setup) -> None:
    service, client, events, kwargs = setup
    kwargs["user"].is_active = False
    result = await service.notify(**kwargs)
    assert result.reason == "inactive_user"
    assert result.skipped
    assert client.calls == []
    service.repository.add.assert_not_awaited()
