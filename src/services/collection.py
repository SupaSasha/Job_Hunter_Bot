import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import Callable

from redis.asyncio import Redis

from src.collectors.base import BaseJobCollector, CollectionError
from src.collectors.registry import COLLECTORS
from src.repositories.collector_runs import CollectorRunRepository
from src.repositories.scheduling import CollectorStateRepository
from src.services.collector_policy import COLLECTOR_POLICIES, next_collection
from src.services.jobs import JobSaveService
from src.services.locks import collector_lock
from src.services.pipeline import CollectionResult, JobPipeline

logger = logging.getLogger(__name__)


class CollectionService:
    def __init__(
        self,
        sessions,
        redis: Redis,
        timezone: str,
        *,
        clock: Callable = lambda: datetime.now(UTC),
        timer: Callable = time.monotonic,
    ):
        self.sessions = sessions
        self.redis = redis
        self.timezone = timezone
        self.clock = clock
        self.timer = timer
        self.runs = CollectorRunRepository(sessions)
        self.states = CollectorStateRepository(sessions)

    async def collect_remoteok(self, expected_next_run: str | None = None) -> dict:
        return await self.collect("remoteok", expected_next_run)

    async def collect(
        self,
        source: str,
        expected_next_run: str | None = None,
        *,
        collector: BaseJobCollector | None = None,
    ) -> dict:
        if source not in COLLECTORS:
            raise ValueError("Unknown collector")
        if collector is not None and collector.source_name != source:
            raise ValueError("Collector source does not match")
        started = self.timer()
        run_id = await self.runs.start(source, self.clock())
        result = CollectionResult()
        status, error = "failed", None
        try:
            outcome = await self._collect(source, expected_next_run, collector, result)
            status = outcome.get("status", "failed" if result.failed else "success")
            error = outcome.get("error") or outcome.get("reason")
            if result.failed and error is None:
                error = "Invalid jobs"
            return outcome
        except BaseException as exc:
            error = type(exc).__name__[:512]
            raise
        finally:
            await self.runs.finish(
                run_id,
                status=status,
                error=error,
                finished_at=self.clock(),
                duration_ms=max(0, round((self.timer() - started) * 1000)),
                received_count=result.received,
                new_count=result.new,
                duplicate_count=result.duplicates,
                cross_source_duplicate_count=result.cross_source_duplicates,
                failed_count=result.failed,
            )

    async def _collect(self, source, expected_next_run, collector, result):
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
            if policy.min_interval:
                if (
                    state.last_started_at is not None
                    and now < state.last_started_at + policy.min_interval
                ):
                    return {"status": "skipped", "reason": "cooldown"}
                if (
                    state.last_status in {"failed", "partial"}
                    and state.next_run_at > now
                ):
                    return {"status": "skipped", "reason": "retry_later"}
            await self.states.update(
                source, last_started_at=now, last_status="running", last_error=None
            )
            try:
                async with asyncio.timeout(510):
                    jobs = await (collector or COLLECTORS[source]()).collect()
                    async with self.sessions() as session:
                        result = await JobPipeline(JobSaveService(session)).run(
                            jobs, result=result
                        )
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
                retry_at = finished + policy.retry_delay
                if isinstance(exc, CollectionError) and exc.retry_at is not None:
                    retry_at = max(retry_at, exc.retry_at)
                await self.states.update(
                    source,
                    last_finished_at=finished,
                    last_status="failed",
                    last_error=type(exc).__name__,
                    next_run_at=retry_at,
                )
                # Keep raw exception text out of broker results/logs.
                logger.error("Collection %s failed: %s", source, type(exc).__name__)
                return {"status": "failed", "error": type(exc).__name__}
