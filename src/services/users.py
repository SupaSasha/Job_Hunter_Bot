from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user import UserORM
from src.repositories.users import UserRepository


class OwnerService:
    """Bootstrap the owner in a dedicated session with expire_on_commit=False."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = UserRepository(session)

    async def get_or_create(self, telegram_id: int) -> UserORM:
        try:
            user = await self.repository.get_by_telegram_id(telegram_id)
            if user is None:
                user = await self.repository.add(UserORM(telegram_id=telegram_id))
            await self.session.commit()
            return user
        except IntegrityError as exc:
            await self.session.rollback()
            original = exc.orig
            if (
                getattr(original, "sqlstate", None) != "23505"
                or getattr(original.__cause__, "constraint_name", None)
                != "uq_users_telegram_id"
            ):
                raise
            try:
                user = await self.repository.get_by_telegram_id(telegram_id)
                if user is None:
                    raise exc
                await self.session.commit()
                return user
            except Exception:
                await self.session.rollback()
                raise
        except Exception:
            await self.session.rollback()
            raise
