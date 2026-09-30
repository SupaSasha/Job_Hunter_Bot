from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from src.repositories.statistics import StatisticsRepository

NOW = datetime(2026, 9, 30, tzinfo=UTC)


@pytest.mark.parametrize(
    "method,timestamp,fields",
    [
        (
            "get_collector_stats",
            "collector_runs.started_at",
            ["cross_source_duplicate_count", "skipped", "running", "GROUP BY"],
        ),
        (
            "get_digest_stats",
            "digest_runs.started_at",
            ["metrics_recorded IS true", "FILTER", "selected", "sent", "failed"],
        ),
        ("get_feedback_stats", "feedback.updated_at", ["saved", "rejected"]),
        (
            "get_notification_stats",
            "notifications.created_at",
            ["sent", "failed", "pending"],
        ),
        (
            "get_data_quality",
            "jobs.created_at",
            [
                "cardinality",
                "salary_min > 0",
                "timezone_min_utc_offset",
                "technologies",
            ],
        ),
    ],
)
async def test_read_only_sql_aggregates_and_bounded_period(method, timestamp, fields):
    session = AsyncMock(spec=AsyncSession)
    result = Mock()
    result.mappings.return_value = [] if method == "get_collector_stats" else Mock()
    if method != "get_collector_stats":
        result.mappings.return_value.one.return_value = {}
    session.execute.return_value = result
    await getattr(StatisticsRepository(session), method)(NOW - timedelta(days=7), NOW)
    statement = session.execute.call_args.args[0]
    assert statement.is_select
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert f"{timestamp} >= " in sql
    assert f"{timestamp} < " in sql
    for field in fields:
        assert field in sql
    session.commit.assert_not_awaited()
    session.flush.assert_not_awaited()
