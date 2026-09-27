from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user import UserORM
from src.repositories.users import UserRepository
from src.services.users import OwnerService


@pytest.fixture
def service():
    service = OwnerService(AsyncMock(spec=AsyncSession))
    service.repository = AsyncMock(spec=UserRepository)
    service.repository.get_by_telegram_id.return_value = None
    service.repository.add.return_value = UserORM(id=1, telegram_id=123, is_active=True)
    return service


async def test_bootstrap_creates_owner(service) -> None:
    owner = await service.get_or_create(123)
    assert owner.telegram_id == 123
    assert service.repository.add.call_args.args[0].telegram_id == 123
    service.session.commit.assert_awaited_once()


async def test_bootstrap_reuses_existing_inactive_owner(service) -> None:
    service.repository.get_by_telegram_id.return_value = UserORM(
        id=1, telegram_id=123, is_active=False
    )
    owner = await service.get_or_create(123)
    assert owner.is_active is False
    service.repository.add.assert_not_awaited()


async def test_bootstrap_recovers_concurrent_creation(service) -> None:
    class DatabaseError(Exception):
        pass

    cause = DatabaseError()
    cause.constraint_name = "uq_users_telegram_id"
    original = DatabaseError()
    original.sqlstate = "23505"
    original.__cause__ = cause
    service.repository.add.side_effect = IntegrityError("INSERT", {}, original)
    service.repository.get_by_telegram_id.side_effect = [
        None,
        UserORM(id=2, telegram_id=123),
    ]
    owner = await service.get_or_create(123)
    assert owner.id == 2
    service.session.rollback.assert_awaited_once()
    service.session.commit.assert_awaited_once()
