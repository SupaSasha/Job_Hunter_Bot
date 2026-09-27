from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.feedback import FeedbackORM
from src.repositories.feedback import FeedbackRepository
from src.services.feedback import FeedbackService


@pytest.fixture
def service():
    service = FeedbackService(AsyncMock(spec=AsyncSession))
    service.repository = AsyncMock(spec=FeedbackRepository)
    rows = {}

    async def get(user_id, job_id):
        return rows.get((user_id, job_id))

    async def add(feedback):
        feedback.id = 1
        rows[(feedback.user_id, feedback.job_id)] = feedback
        return feedback

    async def update(feedback, feedback_type):
        feedback.feedback_type = feedback_type
        return feedback

    service.repository.get_by_user_job.side_effect = get
    service.repository.add.side_effect = add
    service.repository.update_type.side_effect = update
    return service


@pytest.mark.parametrize(
    "actions",
    [
        ["saved"],
        ["rejected"],
        ["saved", "saved"],
        ["saved", "rejected"],
        ["rejected", "saved"],
    ],
)
async def test_feedback_transitions_keep_one_row(service, actions) -> None:
    ids = []
    for feedback_type in actions:
        result = await service.set_feedback(2, 42, feedback_type)
        ids.append(result.id)
        assert result.feedback_type == feedback_type
        assert (result.user_id, result.job_id) == (2, 42)
    assert set(ids) == {1}
    service.repository.add.assert_awaited_once()
    assert service.repository.update_type.await_count == len(actions) - 1
    assert service.session.commit.await_count == len(actions)
    service.session.rollback.assert_not_awaited()


@pytest.mark.parametrize("feedback_type", ["liked", "", "save", "SAVED", None, []])
async def test_invalid_type_does_not_reach_database(service, feedback_type) -> None:
    with pytest.raises(ValueError, match="saved.*rejected"):
        await service.set_feedback(2, 42, feedback_type)
    service.repository.get_by_user_job.assert_not_awaited()
    service.session.commit.assert_not_awaited()


def integrity_error(constraint="uq_feedback_user_job", sqlstate="23505"):
    class DatabaseError(Exception):
        pass

    original = DatabaseError()
    original.sqlstate = sqlstate
    cause = DatabaseError()
    cause.constraint_name = constraint
    original.__cause__ = cause
    return IntegrityError("INSERT", {}, original)


@pytest.mark.parametrize("boundary", ["add", "commit"])
async def test_concurrent_insert_updates_winning_row(service, boundary) -> None:
    service.repository.get_by_user_job.side_effect = [
        None,
        FeedbackORM(id=9, user_id=2, job_id=42, feedback_type="saved"),
    ]
    if boundary == "add":
        service.repository.add.side_effect = integrity_error()
    else:
        service.session.commit.side_effect = [integrity_error(), None]
    result = await service.set_feedback(2, 42, "rejected")
    assert result.id == 9
    assert result.feedback_type == "rejected"
    service.repository.update_type.assert_awaited_once()
    service.session.rollback.assert_awaited_once()


@pytest.mark.parametrize(
    ("constraint", "sqlstate"),
    [("other_unique", "23505"), ("uq_feedback_user_job", "23503")],
)
async def test_unrelated_integrity_error_propagates(service, constraint, sqlstate):
    error = integrity_error(constraint, sqlstate)
    service.repository.add.side_effect = error
    with pytest.raises(IntegrityError) as caught:
        await service.set_feedback(2, 42, "saved")
    assert caught.value is error
    service.repository.update_type.assert_not_awaited()
    service.session.rollback.assert_awaited_once()


async def test_commit_failure_rolls_back(service) -> None:
    service.session.commit.side_effect = RuntimeError("database unavailable")
    with pytest.raises(RuntimeError, match="database unavailable"):
        await service.set_feedback(2, 42, "saved")
    service.session.rollback.assert_awaited_once()


async def test_missing_row_after_conflict_propagates(service) -> None:
    service.repository.get_by_user_job.side_effect = [None, None]
    service.repository.add.side_effect = integrity_error()
    with pytest.raises(IntegrityError):
        await service.set_feedback(2, 42, "saved")
    assert service.session.rollback.await_count == 2
