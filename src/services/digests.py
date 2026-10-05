import asyncio
import logging
from datetime import UTC, date, datetime
from typing import Callable
from zoneinfo import ZoneInfo

from src.repositories.digests import DigestRepository
from src.schemas.digest_metrics import DigestMetrics
from src.schemas.filters import UserFilterDTO
from src.schemas.job import JobDTO
from src.schemas.scoring import ScoreResult
from src.services.entitlements import EntitlementService, digest_due
from src.services.filters import FilterService
from src.services.notifications import NotificationService
from src.services.scoring import ScoringService
from src.services.user_filters import UserFilterService

logger = logging.getLogger(__name__)
DigestItem = tuple[int, JobDTO, ScoreResult]


def select_digest_jobs(
    candidates: list[tuple[int, JobDTO]],
    filters: UserFilterDTO,
    min_score: int,
    max_jobs: int,
    *,
    metrics: DigestMetrics | None = None,
) -> list[DigestItem]:
    metrics = metrics if metrics is not None else DigestMetrics()
    metrics.candidate_count = len(candidates)
    filtering, scoring = FilterService(), ScoringService()
    selected = []
    for job_id, job in candidates:
        if filtering.evaluate(job, filters).accepted:
            metrics.accepted_count += 1
            score = scoring.calculate(job, filters)
            bucket = (
                "0_49"
                if score.score < 50
                else (
                    "90_100"
                    if score.score >= 90
                    else f"{score.score // 10 * 10}_{score.score // 10 * 10 + 9}"
                )
            )
            field = f"score_{bucket}_count"
            setattr(metrics, field, getattr(metrics, field) + 1)
            if score.score >= min_score:
                selected.append((job_id, job, score))
            else:
                metrics.below_threshold_count += 1
        else:
            metrics.filter_rejected_count += 1
    selected.sort(key=lambda item: (-item[2].score, item[0]))
    return selected[:max_jobs]


def format_digest_summary(items: list[DigestItem]) -> str:
    lines = [f"🔥 {len(items)} new job matches", "", "Top matches:"]
    for _, job, score in items[:5]:
        title = " ".join(job.title.split())[:150]
        lines.append(f"• {title} — {score.score}/100")
    return "\n".join(lines)


class DailyDigestService:
    def __init__(
        self,
        sessions,
        client,
        entitlements: EntitlementService,
        *,
        clock: Callable = lambda: datetime.now(UTC),
    ):
        self.sessions = sessions
        self.client = client
        self.entitlements = entitlements
        self.clock = clock
        self.repository = DigestRepository(sessions)

    async def send(
        self, user_id: int, expected_date: str | None = None, *, run_now: bool = False
    ) -> dict:
        # Recovery timeout is always longer than the maximum worker/service lifetime.
        async with asyncio.timeout(600):
            return await self._send(user_id, expected_date, run_now=run_now)

    async def _send(
        self, user_id: int, expected_date: str | None = None, *, run_now: bool = False
    ) -> dict:
        now = self.clock()
        users = await self.repository.users(user_id)
        if not users:
            return {"status": "skipped", "reason": "inactive_or_disabled"}
        user, preferences, subscription = users[0]
        effective = self.entitlements.effective(preferences, subscription, now)
        local_date = now.astimezone(ZoneInfo(effective.timezone)).date()
        if expected_date is not None and local_date != date.fromisoformat(
            expected_date
        ):
            return {"status": "skipped", "reason": "stale_date"}
        if not effective.digest_enabled:
            return {"status": "skipped", "reason": "inactive_or_disabled"}
        if not run_now and not digest_due(effective, now):
            return {"status": "skipped", "reason": "not_due"}
        if self.client is None:
            return {"status": "skipped", "reason": "telegram_not_configured"}
        run_id = await self.repository.reserve(user_id, local_date, now)
        if run_id is None:
            return {"status": "skipped", "reason": "already_attempted_today"}
        selected = sent = failed = skipped = 0
        metrics = DigestMetrics()
        try:
            candidates = await self.repository.candidates(user_id, now=now)
            async with self.sessions() as session:
                filters = await UserFilterService(session).get_filters(user_id)
            items = select_digest_jobs(
                candidates,
                filters,
                effective.min_score,
                effective.max_jobs_per_digest,
                metrics=metrics,
            )
            selected = len(items)
            await self.repository.update(
                run_id, selected=selected, metrics_recorded=True, **metrics.model_dump()
            )
            if not items:
                await self.repository.update(
                    run_id, status="empty", finished_at=self.clock()
                )
                return {"status": "empty", "selected": 0, "sent": 0}
            summary_id = await self.client.send_message(
                user.telegram_id, format_digest_summary(items)
            )
            await self.repository.update(run_id, summary_message_id=summary_id)
            for job_id, job, score in items:
                try:
                    async with self.sessions() as session:
                        result = await NotificationService(session, self.client).notify(
                            user=user, job_id=job_id, job=job, score=score
                        )
                except Exception:
                    failed += 1
                    raise
                sent += int(result.sent)
                skipped += int(result.skipped)
                failed += int(not result.sent and not result.skipped)
                # Persist progress after each attempt; interrupted runs stay pending.
                await self.repository.update(
                    run_id, sent=sent, failed=failed, skipped=skipped
                )
            status = "sent" if sent == selected else ("partial" if sent else "failed")
            await self.repository.update(
                run_id, status=status, finished_at=self.clock()
            )
            return {
                "status": status,
                "selected": selected,
                "sent": sent,
                "failed": failed,
                "skipped": skipped,
            }
        except Exception as exc:
            await self.repository.update(
                run_id,
                status="partial" if sent else "failed",
                selected=selected,
                sent=sent,
                failed=failed,
                skipped=skipped,
                **metrics.model_dump(),
                last_error=type(exc).__name__,
                finished_at=self.clock(),
            )
            logger.error("Digest user=%s failed: %s", user_id, type(exc).__name__)
            return {
                "status": "partial" if sent else "failed",
                "error": type(exc).__name__,
            }
