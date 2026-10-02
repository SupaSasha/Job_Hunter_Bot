from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, Mock

from sqlalchemy.dialects import postgresql

from src.repositories.digests import DigestRepository
from src.repositories.scheduling import CollectorStateRepository, DeliveryBootstrap


def sessions():
    session = AsyncMock()
    factory = Mock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return factory, session


async def test_existing_collector_schedule_is_not_resampled(monkeypatch):
    factory, session = sessions()
    session.scalar.return_value = 1
    jitter = Mock(side_effect=AssertionError("Must not resample persisted schedule"))
    monkeypatch.setattr("src.repositories.scheduling.next_collection", jitter)
    repo = CollectorStateRepository(factory)
    for _ in range(3):
        await repo.ensure(
            "remoteok", datetime(2026, 9, 27, tzinfo=UTC), "America/Montevideo"
        )
    jitter.assert_not_called()
    session.execute.assert_not_awaited()


async def test_reservation_uses_unique_date_and_commits_before_return():
    factory, session = sessions()
    session.scalar.return_value = 7
    assert (
        await DigestRepository(factory).reserve(
            2, date(2026, 9, 27), datetime(2026, 9, 27, tzinfo=UTC)
        )
        == 7
    )
    sql = str(session.scalar.call_args.args[0].compile(dialect=postgresql.dialect()))
    assert (
        "ON CONFLICT (user_id, local_date) WHERE status <> 'abandoned' DO NOTHING"
        in sql
    )
    session.commit.assert_awaited_once()


async def test_candidates_allow_only_retryable_notifications():
    factory, session = sessions()
    session.scalars.return_value = []
    assert await DigestRepository(factory).candidates(2) == []
    sql = str(session.scalars.call_args.args[0].compile(dialect=postgresql.dialect()))
    assert "NOT (EXISTS" in sql
    assert "notifications.user_id" in sql and "notifications.job_id = jobs.id" in sql
    assert "notifications.status" in sql
    assert "retryable" in str(
        session.scalars.call_args.args[0].compile(
            compile_kwargs={"literal_binds": True}
        )
    )
    assert "created_at >" not in sql


async def test_bootstrap_defaults_and_trial_do_not_overwrite_existing_user():
    from datetime import time, timedelta
    from types import SimpleNamespace

    factory, session = sessions()
    session.scalars.return_value = [17]
    config = SimpleNamespace(
        SCHEDULER_TIMEZONE="America/Montevideo",
        FREE_DIGEST_TIME=time(9),
        FREE_MIN_SCORE=70,
        FREE_MAX_JOBS_PER_DIGEST=10,
        TRIAL_DAYS=7,
    )
    now = datetime(2026, 9, 27, tzinfo=UTC)
    await DeliveryBootstrap(factory, config).ensure_users(now)
    statements = [
        c.args[0].compile(dialect=postgresql.dialect())
        for c in session.execute.call_args_list
    ]
    assert len(statements) == 2
    assert all("ON CONFLICT (user_id) DO NOTHING" in str(s) for s in statements)
    assert statements[1].params["trial_ends_at_m0"] == now + timedelta(days=7)
    assert statements[1].params["status_m0"] == "trial"


async def test_candidates_use_collected_age_order_cooldown_and_sql_limit(monkeypatch):
    from src.config import settings

    monkeypatch.setattr(settings, "DIGEST_JOB_MAX_AGE_DAYS", 7)
    monkeypatch.setattr(settings, "DIGEST_CANDIDATE_LIMIT", 1000)
    factory, session = sessions()
    session.scalars.return_value = []
    await DigestRepository(factory).candidates(2, now=datetime(2026, 10, 2, tzinfo=UTC))
    sql = str(
        session.scalars.call_args.args[0].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "2026-09-25" in sql
    assert "jobs.collected_at >=" in sql
    assert "ORDER BY jobs.collected_at DESC, jobs.id DESC" in sql
    assert "LIMIT 1000" in sql
    assert "notifications.status != 'retryable'" in sql
    assert "notifications.retry_after_until >" in sql


async def test_bootstrap_does_not_write_initialized_users():
    from src.config import settings

    factory, session = sessions()
    session.scalars.return_value = []
    await DeliveryBootstrap(factory, settings).ensure_users()
    session.execute.assert_not_awaited()
    session.commit.assert_not_awaited()
    assert session.scalars.await_count == 2


async def test_bootstrap_uses_configured_timezone(monkeypatch):
    from src.config import settings

    monkeypatch.setattr(settings, "SCHEDULER_TIMEZONE", "Europe/London")
    factory, session = sessions()
    session.scalars.side_effect = [[17], []]
    await DeliveryBootstrap(factory, settings).ensure_users()
    sql = session.execute.call_args.args[0].compile(dialect=postgresql.dialect())
    assert sql.params["timezone_m0"] == "Europe/London"
