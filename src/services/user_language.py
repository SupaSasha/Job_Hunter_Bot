from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.i18n import Language, LocalizedValidationError
from src.models.user import UserORM
from src.repositories.scheduling import delivery_defaults
from src.repositories.users import UserRepository
from src.services.notification_settings import SettingsUnavailable
from src.services.users import OwnerService


class UserLanguageService:
    """Persist language without changing preferences, trials or access rules."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repository = UserRepository(session)

    async def register(self, telegram_id: int, language_code: object = None) -> UserORM:
        user = await OwnerService(self.session).get_or_create(
            telegram_id, language_code=language_code
        )
        if not user.is_active:
            return user
        user_id = user.id
        try:
            # Reuse delivery bootstrap defaults; retries never overwrite preferences
            # or renew an existing/expired subscription.
            for model, values in delivery_defaults(settings, datetime.now(UTC)):
                await self.session.execute(
                    insert(model)
                    .values(user_id=user_id, **values)
                    .on_conflict_do_nothing(index_elements=["user_id"])
                )
            await self.session.commit()
            return user
        except Exception:
            await self.session.rollback()
            raise

    async def update_language(self, user_id: int, language: Language) -> Language:
        try:
            locale = Language(language)
        except (ValueError, TypeError):
            raise LocalizedValidationError("error.language") from None
        try:
            user = await self.repository.get_by_id(user_id)
            if user is None or not user.is_active:
                raise SettingsUnavailable
            await self.repository.update_language(user_id, locale.value)
            await self.session.commit()
            return locale
        except Exception:
            await self.session.rollback()
            raise
