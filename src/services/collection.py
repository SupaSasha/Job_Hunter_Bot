import asyncio
import logging
from datetime import UTC, datetime
from typing import Callable

from redis.asyncio import Redis

from src.collectors.remoteok import RemoteOKCollector
from src.repositories.scheduling import CollectorStateRepository
from src.services.collector_policy import COLLECTOR_POLICIES, next_collection
from src.services.jobs import JobSaveService
from src.services.locks import collector_lock
from src.services.pipeline import JobPipeline

logger = logging.getLogger(__name__)


class CollectionService:
    def __init__(
        self,
        sessions,
        redis: Redis,
        timezone: str,
        *,
        clock: Callable = lambda: datetime.now(UTC),
    ):
        self.sessions = sessions
        self.redis = redis
        self.timezone = timezone
        self.clock = clock
        self.states = CollectorStateRepository(sessions)

    async def collect_remoteok(self, expected_next_run: str | None = None) -> dict:
        source = "remoteok"
        policy = COLLECTOR_POLICIES[source]
        async with (
            asyncio.timeout(600),
            collector_lock(self.redis, source) as acquired,
        ):
            if not acquired:
                return {"status": "skipped", "reason": "already_running"}
            now = self.clock()
            await self.states.ensure(source, now, self.timezone)
            state = await self.states.get(source)
            if expected_next_run is not None and (
                state.next_run_at != datetime.fromisoformat(expected_next_run)
                or state.next_run_at > now
            ):
                return {"status": "skipped", "reason": "stale_schedule"}
            await self.states.update(
                source, last_started_at=now, last_status="running", last_error=None
            )
            try:
                async with asyncio.timeout(510):
                    jobs = await RemoteOKCollector().collect()
                    async with self.sessions() as session:
                        result = await JobPipeline(JobSaveService(session)).run(jobs)
                finished = self.clock()
                if result.failed:
                    await self.states.update(
                        source,
                        last_finished_at=finished,
                        last_status="partial",
                        last_error=f"Invalid jobs: {result.failed}",
                        next_run_at=finished + policy.retry_delay,
                    )
                else:
                    await self.states.update(
                        source,
                        last_finished_at=finished,
                        last_success_at=finished,
                        last_status="success",
                        last_error=None,
                        next_run_at=next_collection(finished, policy, self.timezone),
                    )
                logger.info("Collection %s: %s", source, result.model_dump())
                return result.model_dump()
            except Exception as exc:
                finished = self.clock()
                await self.states.update(
                    source,
                    last_finished_at=finished,
                    last_status="failed",
                    last_error=type(exc).__name__,
                    next_run_at=finished + policy.retry_delay,
                )
                # Keep raw exception text out of broker results/logs.
                logger.error("Collection %s failed: %s", source, type(exc).__name__)
                return {"status": "failed", "error": type(exc).__name__}
