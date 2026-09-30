import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, time
from unittest.mock import AsyncMock

import pytest

from src.bot.client import TelegramAPIError
from src.models.scheduling import UserNotificationSettingsORM
from src.models.user import UserORM
from src.schemas.job import JobDTO
from src.schemas.notifications import NotificationResult
from src.services.default_filters import default_user_filters
from src.services.digests import DailyDigestService, select_digest_jobs
from src.services.entitlements import EntitlementService


def job(number, **changes):
    return JobDTO(
        source="remoteok",
        external_id=str(number),
        title="Python developer",
        url=f"https://example.com/{number}",
        remote=True,
        remote_regions=["worldwide"],
        technologies=["python"],
        **changes,
    )


def test_selection_real_filters_scoring_threshold_order_and_cap():
    high = job(1).model_copy(
        update={"technologies": ["python", "fastapi", "docker", "postgresql"]}
    )
    low = job(2)
    rejected = job(3).model_copy(update={"technologies": ["java"]})
    items = [(2, low), (3, rejected), (1, high)]
    selected = select_digest_jobs(items, default_user_filters(), 0, 10)
    assert [item[0] for item in selected] == [1, 2]
    assert selected[0][2].score > selected[1][2].score
    threshold = selected[0][2].score
    assert [
        i[0] for i in select_digest_jobs(items, default_user_filters(), threshold, 10)
    ] == [1]
    assert len(select_digest_jobs(items, default_user_filters(), 0, 1)) == 1
    assert select_digest_jobs(items, default_user_filters(), 0, 0) == []


class FakeRepository:
    def __init__(self):
        self.reserved = False
        self.rows = [
            (
                UserORM(id=2, telegram_id=123, is_active=True),
                UserNotificationSettingsORM(
                    timezone="America/Montevideo",
                    digest_time=time(9),
                    min_score=0,
                    max_jobs_per_digest=10,
                    digest_enabled=True,
                ),
                None,
            )
        ]
        self.items = [(1, job(1)), (2, job(2))]
        self.state = {}

    async def users(self, user_id):
        return self.rows

    async def reserve(self, user_id, local_date, now):
        if self.reserved:
            return None
        self.reserved = True
        self.state["status"] = "pending"
        return 1

    async def candidates(self, user_id):
        return self.items

    async def update(self, run_id, **values):
        self.state.update(values)


@pytest.fixture
def setup(monkeypatch):
    @asynccontextmanager
    async def sessions():
        yield None

    client = AsyncMock()
    client.send_message.return_value = 99
    service = DailyDigestService(
        sessions,
        client,
        EntitlementService(free_min_score=0),
        clock=lambda: datetime(2026, 9, 27, 12, 2, tzinfo=UTC),
    )
    service.repository = FakeRepository()
    notify = AsyncMock(return_value=NotificationResult(sent=True, skipped=False))

    class Notifications:
        def __init__(self, *args):
            self.notify = notify

    monkeypatch.setattr("src.services.digests.NotificationService", Notifications)
    return service, client, notify


async def test_digest_summary_then_jobs_and_no_second_attempt(setup):
    service, client, notify = setup

    async def send_summary(*args):
        assert service.repository.state["status"] == "pending"
        notify.assert_not_awaited()
        return 99

    client.send_message.side_effect = send_summary
    result = await service.send(2)
    assert result["status"] == "sent" and result["sent"] == 2
    assert [call.kwargs["job_id"] for call in notify.call_args_list] == [1, 2]
    assert "2 new job matches" in client.send_message.call_args.args[1]
    assert (await service.send(2))["reason"] == "already_attempted_today"
    client.send_message.assert_awaited_once()
    assert service.repository.state["summary_message_id"] == 99


async def test_concurrent_duplicate_tasks_only_one_summary(setup):
    service, client, notify = setup
    results = await asyncio.gather(service.send(2), service.send(2))
    assert sorted(r["status"] for r in results) == ["sent", "skipped"]
    client.send_message.assert_awaited_once()
    assert notify.await_count == 2


async def test_empty_digest_is_done_without_telegram(setup):
    service, client, notify = setup
    service.repository.items = []
    assert (await service.send(2))["status"] == "empty"
    assert (await service.send(2))["status"] == "skipped"
    assert service.repository.state["status"] == "empty"
    client.send_message.assert_not_awaited()
    notify.assert_not_awaited()


async def test_summary_failure_no_job_sends_and_no_retry(setup):
    service, client, notify = setup
    client.send_message.side_effect = TelegramAPIError("timeout")
    assert (await service.send(2))["status"] == "failed"
    assert service.repository.state["last_error"] == "TelegramAPIError"
    assert (await service.send(2))["status"] == "skipped"
    notify.assert_not_awaited()
    client.send_message.assert_awaited_once()


@pytest.mark.parametrize(
    "second,expected",
    [
        (NotificationResult(sent=False, skipped=False, reason="timeout"), "partial"),
        (
            NotificationResult(sent=False, skipped=True, reason="already_sent"),
            "partial",
        ),
    ],
)
async def test_partial_delivery_persists_counts(setup, second, expected):
    service, client, notify = setup
    notify.side_effect = [NotificationResult(sent=True, skipped=False), second]
    assert (await service.send(2))["status"] == expected
    state = service.repository.state
    assert state["sent"] == 1
    assert state["failed"] == int(not second.skipped)
    assert state["skipped"] == int(second.skipped)
    assert (await service.send(2))["status"] == "skipped"
    assert notify.await_count == 2


async def test_unexpected_job_failure_after_success_is_partial(setup):
    service, _, notify = setup
    notify.side_effect = [
        NotificationResult(sent=True, skipped=False),
        RuntimeError("db"),
    ]
    assert (await service.send(2))["status"] == "partial"
    assert service.repository.state["sent"] == 1
    assert service.repository.state["failed"] == 1


async def test_stale_date_disabled_user_and_missing_token_do_not_reserve(setup):
    service, client, _ = setup
    assert (await service.send(2, "2026-09-26"))["reason"] == "stale_date"
    service.client = None
    assert (await service.send(2))["reason"] == "telegram_not_configured"
    service.repository.rows = []
    assert (await service.send(2))["reason"] == "inactive_or_disabled"
    assert not service.repository.reserved
    client.send_message.assert_not_awaited()


async def test_run_now_bypasses_time_but_not_daily_reservation(setup):
    service, client, _ = setup
    service.clock = lambda: datetime(2026, 9, 27, 10, tzinfo=UTC)
    assert (await service.send(2))["reason"] == "not_due"
    assert not service.repository.reserved
    assert (await service.send(2, run_now=True))["status"] == "sent"
    assert (await service.send(2, run_now=True))["reason"] == "already_attempted_today"
    client.send_message.assert_awaited_once()


async def test_run_now_does_not_enable_disabled_delivery(setup):
    service, client, _ = setup
    service.repository.rows[0][1].digest_enabled = False
    assert (await service.send(2, run_now=True))["reason"] == "inactive_or_disabled"
    assert not service.repository.reserved
    client.send_message.assert_not_awaited()


async def test_digest_persists_pipeline_and_delivery_metrics(setup):
    service, _, notify = setup
    rejected = job(3).model_copy(update={"technologies": ["java"]})
    service.repository.items.append((3, rejected))
    notify.side_effect = [
        NotificationResult(sent=True, skipped=False),
        NotificationResult(sent=False, skipped=False, reason="timeout"),
    ]
    await service.send(2)
    state = service.repository.state
    assert state["metrics_recorded"] is True
    assert state["candidate_count"] == 3
    assert state["filter_rejected_count"] == 1
    assert state["accepted_count"] == 2
    assert sum(value for name, value in state.items() if name.startswith("score_")) == 2
    assert state["selected"] == 2
    assert state["sent"] == state["failed"] == 1


@pytest.mark.parametrize(
    "score,bucket",
    [
        (0, "0_49"),
        (49, "0_49"),
        (50, "50_59"),
        (59, "50_59"),
        (60, "60_69"),
        (69, "60_69"),
        (70, "70_79"),
        (79, "70_79"),
        (80, "80_89"),
        (89, "80_89"),
        (90, "90_100"),
        (100, "90_100"),
    ],
)
def test_score_bucket_boundaries_and_threshold(monkeypatch, score, bucket):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from src.schemas.digest_metrics import DigestMetrics

    calculate = Mock(return_value=SimpleNamespace(score=score))
    monkeypatch.setattr("src.services.digests.ScoringService.calculate", calculate)
    metrics = DigestMetrics()
    selected = select_digest_jobs(
        [(1, job(1))], default_user_filters(), 70, 1, metrics=metrics
    )
    assert getattr(metrics, f"score_{bucket}_count") == 1
    assert metrics.accepted_count == metrics.candidate_count == 1
    assert metrics.below_threshold_count == int(score < 70)
    assert len(selected) == int(score >= 70)
    calculate.assert_called_once()


async def test_empty_digest_records_measured_zeroes(setup):
    service, _, _ = setup
    service.repository.items = []
    await service.send(2)
    assert service.repository.state["metrics_recorded"] is True
    assert service.repository.state["candidate_count"] == 0
