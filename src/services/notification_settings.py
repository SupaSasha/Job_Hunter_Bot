from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.ext.asyncio import AsyncSession

from src.repositories.bot_queries import BotQueryRepository
from src.repositories.notification_settings import NotificationSettingsRepository
from src.services.entitlements import EffectiveNotificationSettings, EntitlementService


class SettingsUnavailable(Exception):
    pass


class PremiumRequired(Exception):
    pass


@dataclass(frozen=True)
class NotificationSettingsView:
    effective: EffectiveNotificationSettings
    plan: str
    trial_ends_at: datetime | None


class NotificationSettingsService:
    """Own settings transactions; use a session without unrelated pending writes."""

    def __init__(
        self,
        session: AsyncSession,
        entitlements: EntitlementService,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self.session = session
        self.repository = NotificationSettingsRepository(session)
        self.queries = BotQueryRepository(session)
        self.entitlements = entitlements
        self.clock = clock

    async def get(self, user_id: int) -> NotificationSettingsView:
        preferences = await self.repository.get_by_user_id(user_id)
        if preferences is None:
            raise SettingsUnavailable
        subscription = await self.queries.subscription(user_id)
        now = self.clock()
        plan, trial_end = self.entitlements.plan(subscription, now)
        return NotificationSettingsView(
            self.entitlements.effective(preferences, subscription, now), plan, trial_end
        )

    async def update_timezone(self, user_id: int, timezone: str) -> None:
        if not isinstance(timezone, str):
            raise ValueError("Invalid timezone")
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Invalid timezone") from None
        await self._update(user_id, "timezone", timezone, premium=False)

    async def update_digest_time(self, user_id: int, digest_time: time) -> None:
        if (
            not isinstance(digest_time, time)
            or digest_time.tzinfo is not None
            or digest_time.second
            or digest_time.microsecond
        ):
            raise ValueError("Digest time must be a local time with minute precision")
        await self._update(user_id, "digest_time", digest_time, premium=True)

    async def update_min_score(self, user_id: int, min_score: int) -> None:
        if type(min_score) is not int or not 0 <= min_score <= 100:
            raise ValueError("Minimum score must be an integer from 0 to 100")
        await self._update(user_id, "min_score", min_score, premium=True)

    async def _update(self, user_id: int, field: str, value, *, premium: bool) -> None:
        try:
            # Resolve entitlement again on every write, including stale menu selections.
            view = await self.get(user_id)
            if premium and not view.effective.premium:
                raise PremiumRequired
            await getattr(self.repository, f"update_{field}")(user_id, value)
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
