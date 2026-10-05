from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user import UserORM


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_telegram_id(self, telegram_id: int) -> UserORM | None:
        return await self.session.scalar(
            select(UserORM)
            .where(UserORM.telegram_id == telegram_id)
            .execution_options(populate_existing=True)
        )

    async def get_by_id(self, user_id: int) -> UserORM | None:
        return await self.session.scalar(
            select(UserORM)
            .where(UserORM.id == user_id)
            .execution_options(populate_existing=True)
        )

    async def update_language(self, user_id: int, language: str) -> None:
        await self.session.execute(
            update(UserORM).where(UserORM.id == user_id).values(language=language)
        )

    async def add(self, user: UserORM) -> UserORM:
        self.session.add(user)
        await self.session.flush()
        return user
