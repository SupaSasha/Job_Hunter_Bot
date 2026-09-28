from unittest.mock import AsyncMock

from sqlalchemy.dialects import postgresql

from src.repositories.bot_queries import BotQueryRepository
from src.repositories.feedback import FeedbackRepository


async def test_saved_query_is_scoped_ordered_limited_and_read_only():
    session = AsyncMock()
    session.scalars.return_value = []
    assert await FeedbackRepository(session).get_saved_jobs_for_user(17) == []
    statement = session.scalars.call_args.args[0].compile(dialect=postgresql.dialect())
    query = str(statement)
    assert "feedback.user_id =" in query and 17 in statement.params.values()
    assert "feedback.feedback_type =" in query and "saved" in statement.params.values()
    assert "feedback.updated_at DESC" in query
    assert "LIMIT" in query and 10 in statement.params.values()
    session.commit.assert_not_awaited()
    session.execute.assert_not_awaited()


async def test_last_digest_is_scoped_to_user_and_latest_first():
    session = AsyncMock()
    session.scalar.return_value = None
    assert await BotQueryRepository(session).last_digest(17) is None
    statement = session.scalar.call_args.args[0].compile(dialect=postgresql.dialect())
    query = str(statement)
    assert "digest_runs.user_id =" in query and 17 in statement.params.values()
    assert "digest_runs.started_at DESC" in query
    assert "LIMIT" in query
    session.commit.assert_not_awaited()
