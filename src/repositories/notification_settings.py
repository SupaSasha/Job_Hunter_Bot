from datetime import time

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.scheduling import UserNotificationSettingsORM


class NotificationSettingsRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_user_id(self, user_id: int) -> UserNotificationSettingsORM | None:
        return await self.session.scalar(
            select(UserNotificationSettingsORM)
            .where(UserNotificationSettingsORM.user_id == user_id)
            .execution_options(populate_existing=True)
        )

    async def _update(self, user_id: int, **values) -> None:
        await self.session.execute(
            update(UserNotificationSettingsORM)
            .where(UserNotificationSettingsORM.user_id == user_id)
            .values(**values)
        )

    async def update_timezone(self, user_id: int, timezone: str) -> None:
        await self._update(user_id, timezone=timezone)

    async def update_digest_time(self, user_id: int, digest_time: time) -> None:
        await self._update(user_id, digest_time=digest_time)

    async def update_min_score(self, user_id: int, min_score: int) -> None:
        await self._update(user_id, min_score=min_score)
