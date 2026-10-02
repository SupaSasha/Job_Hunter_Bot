from dataclasses import dataclass
from datetime import datetime, time
from zoneinfo import ZoneInfo

from src.models.scheduling import UserNotificationSettingsORM, UserSubscriptionORM


@dataclass(frozen=True)
class EffectiveNotificationSettings:
    timezone: str
    digest_time: time
    min_score: int
    max_jobs_per_digest: int
    digest_enabled: bool
    premium: bool


class EntitlementService:
    def __init__(self, *, free_digest_time: time = time(9), free_min_score: int = 70):
        self.free_digest_time = free_digest_time
        self.free_min_score = free_min_score

    @staticmethod
    def is_premium(subscription: UserSubscriptionORM | None, now: datetime) -> bool:
        if subscription is None:
            return False
        if subscription.status == "trial":
            return (
                subscription.trial_ends_at is not None
                and now < subscription.trial_ends_at
            )
        if subscription.status == "active":
            return (
                subscription.subscription_ends_at is None
                or now < subscription.subscription_ends_at
            )
        return False

    def plan(
        self, subscription: UserSubscriptionORM | None, now: datetime
    ) -> tuple[str, datetime | None]:
        if not self.is_premium(subscription, now):
            return "Free", None
        if subscription.status == "trial":
            return "Trial", subscription.trial_ends_at
        return "Premium", None

    def effective(
        self,
        preferences: UserNotificationSettingsORM,
        subscription: UserSubscriptionORM | None,
        now: datetime,
    ) -> EffectiveNotificationSettings:
        premium = self.is_premium(subscription, now)
        return EffectiveNotificationSettings(
            timezone=preferences.timezone,
            digest_time=preferences.digest_time if premium else self.free_digest_time,
            min_score=preferences.min_score if premium else self.free_min_score,
            max_jobs_per_digest=preferences.max_jobs_per_digest,
            digest_enabled=preferences.digest_enabled,
            premium=premium,
        )


def digest_due(
    settings: EffectiveNotificationSettings,
    now: datetime,
) -> bool:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    local = now.astimezone(ZoneInfo(settings.timezone))
    return settings.digest_enabled and local.time() >= settings.digest_time
