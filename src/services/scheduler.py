import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from src.repositories.digests import DigestRepository
from src.repositories.scheduling import CollectorStateRepository
from src.services.collector_policy import COLLECTOR_POLICIES
from src.services.entitlements import EntitlementService, digest_due

logger = logging.getLogger(__name__)


class SchedulerService:
    def __init__(
        self, sessions, publish, timezone: str, entitlements: EntitlementService
    ):
        self.collectors = CollectorStateRepository(sessions)
        self.digests = DigestRepository(sessions)
        self.publish = publish
        self.timezone = timezone
        self.entitlements = entitlements

    async def dispatch_collectors(self, now: datetime | None = None) -> int:
        now = now or datetime.now(UTC)
        for source in COLLECTOR_POLICIES:
            await self.collectors.ensure(source, now, self.timezone)
        dispatched = 0
        for state in await self.collectors.due(now):
            policy = COLLECTOR_POLICIES.get(state.source)
            if policy is None:
                continue
            self.publish(policy.task_name, args=[state.next_run_at.isoformat()])
            dispatched += 1
        return dispatched

    async def dispatch_digests(self, now: datetime | None = None) -> int:
        now = now or datetime.now(UTC)
        await self.digests.recover_stale(now)
        dispatched = 0
        for user, preferences, subscription in await self.digests.users():
            try:
                effective = self.entitlements.effective(preferences, subscription, now)
                local_date = now.astimezone(ZoneInfo(effective.timezone)).date()
                if not digest_due(effective, now):
                    continue
                if await self.digests.attempted(user.id, local_date):
                    continue
            except (ValueError, KeyError):
                logger.error("Invalid digest settings for user=%s", user.id)
                continue
            self.publish(
                "notifications.send_daily_digest",
                args=[user.id, local_date.isoformat()],
            )
            dispatched += 1
        return dispatched
