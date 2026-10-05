from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user_filter import UserFilterORM


class UserFilterRepository:
    """Flush writes; transaction ownership belongs to the service."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_user_id(self, user_id: int) -> UserFilterORM | None:
        return await self.session.scalar(
            select(UserFilterORM)
            .where(UserFilterORM.user_id == user_id)
            .execution_options(populate_existing=True)
        )

    async def add(self, filters: UserFilterORM) -> UserFilterORM:
        self.session.add(filters)
        await self.session.flush()
        return filters
