import asyncio
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from src.bot.client import TelegramClient
from src.bot.commands import CommandHandler
from src.bot.dispatch import CommandDispatcher
from src.bot.filters import FiltersHandler
from src.bot.pending_input import PendingInputStore
from src.bot.updates import route_update
from src.models import (
    DigestRunORM,
    NotificationORM,
    UserFilterORM,
    UserNotificationSettingsORM,
    UserORM,
    UserSubscriptionORM,
)
from src.repositories.bot_queries import BotQueryRepository
from src.repositories.feedback import FeedbackRepository
from src.repositories.user_filters import UserFilterRepository
from src.repositories.users import UserRepository
from src.schemas.job import JobDTO
from src.services.digests import DailyDigestService
from src.services.entitlements import EntitlementService
from src.services.jobs import job_to_orm
from src.services.scoring import ScoringService
from src.services.user_filters import UserFilterService, filter_defaults

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 5, 12, tzinfo=UTC)


async def test_migration_preserves_existing_rows_and_matches_metadata(pg):
    from src.db.base import Base

    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    async with pg() as session:
        connection = await session.connection()

        def downgrade(sync_connection):
            config.attributes["connection"] = sync_connection
            command.downgrade(config, "49f75b591334")

        await connection.run_sync(downgrade)
        await session.commit()
    # Use SQL for the old schema: the current ORM also includes users.language.
    async with pg() as session:
        a = await session.scalar(
            text("INSERT INTO users (telegram_id) VALUES (1001) RETURNING id")
        )
        await session.execute(text("INSERT INTO users (telegram_id) VALUES (1002)"))
        await session.execute(
            text(
                "INSERT INTO user_notification_settings "
                "(user_id, timezone, digest_time, min_score, max_jobs_per_digest) "
                "VALUES (:id, 'UTC', '09:00', 0, 10)"
            ),
            {"id": a},
        )
        await session.commit()
    async with pg() as session:
        connection = await session.connection()

        def upgrade(sync_connection):
            config.attributes["connection"] = sync_connection
            command.upgrade(config, "head")
            command.check(config)

        await connection.run_sync(upgrade)
        await session.commit()
        assert await session.scalar(select(func.count()).select_from(UserORM)) == 2
        preferences = await session.scalar(
            select(UserNotificationSettingsORM).where(
                UserNotificationSettingsORM.user_id == a
            )
        )
        assert preferences.timezone == "UTC" and preferences.digest_time == time(9)
        assert preferences.min_score == 0
        assert (
            await session.scalar(select(func.count()).select_from(UserFilterORM)) == 0
        )
        assert "timezone" not in Base.metadata.tables["user_filters"].columns


async def test_saved_preferences_change_scoring_without_changing_weights(pg):
    a, _ = await seed(pg)
    job = JobDTO(
        source="remoteok",
        external_id="score",
        title="Backend developer",
        url="https://example.com/score",
        remote=True,
        remote_regions=["worldwide"],
        technologies=["redis"],
    )
    async with pg() as session:
        service = UserFilterService(session, owner_telegram_id=None)
        before = ScoringService().calculate(job, await service.get_filters(a)).score
        await service.update_list(a, "preferred_technologies", "add", "redis")
        await service.update_list(a, "keywords", "add", "backend")
    async with pg() as session:
        after = ScoringService().calculate(
            job, await UserFilterService(session).get_filters(a)
        )
        assert after.score == before + 7
        assert "Preferred technology Redis: +4" in after.matched_rules
        assert "Keyword: backend: +3" in after.matched_rules


async def seed(pg):
    async with pg() as session:
        users = [UserORM(telegram_id=1001), UserORM(telegram_id=1002)]
        session.add_all(users)
        await session.flush()
        session.add_all(
            [
                UserNotificationSettingsORM(
                    user_id=user.id, timezone="UTC", digest_time=time(9), min_score=0
                )
                for user in users
            ]
        )
        await session.commit()
        return [user.id for user in users]


async def test_filters_bootstrap_and_persist_across_sessions(pg):
    a, b = await seed(pg)
    async with pg() as session:
        service = UserFilterService(session, owner_telegram_id=1001)
        assert (await service.get_filters(a)).required_technologies == ["python"]
        assert (await service.get_filters(b)).required_technologies == []
        await service.update_list(a, "required_technologies", "clear")
        await service.update_list(a, "required_technologies", "add", "JS, javascript")
        await service.update_list(b, "keywords", "add", " Backend, backend, API ")
    async with pg() as session:
        service = UserFilterService(session, owner_telegram_id=1001)
        assert (await service.get_filters(a)).required_technologies == ["javascript"]
        assert (await service.get_filters(b)).keywords == ["backend", "api"]
        assert (
            await session.scalar(select(func.count()).select_from(UserFilterORM)) == 2
        )


async def test_parallel_bootstrap_and_list_updates_do_not_lose_changes(pg):
    a, _ = await seed(pg)

    async def get():
        async with pg() as session:
            return await UserFilterService(session, owner_telegram_id=None).get_filters(
                a
            )

    results = await asyncio.gather(get(), get(), get())
    assert all(result.required_technologies == [] for result in results)

    async def add(value):
        async with pg() as session:
            await UserFilterService(session).update_list(a, "keywords", "add", value)

    await asyncio.gather(add("python"), add("backend"), add("api"))
    async with pg() as session:
        result = await UserFilterService(session).get_filters(a)
        assert set(result.keywords) == {"python", "backend", "api"}
        assert (
            await session.scalar(select(func.count()).select_from(UserFilterORM)) == 1
        )


async def test_repository_flushes_without_commit(pg):
    a, _ = await seed(pg)
    async with pg() as session:
        row = await UserFilterRepository(session).add(UserFilterORM(user_id=a))
        assert row.id and set(row.sources) == {
            "remoteok",
            "weworkremotely",
            "getonboard",
            "himalayas",
            "jobicy",
            "the_muse",
        }
        await session.rollback()
    async with pg() as session:
        assert await UserFilterRepository(session).get_by_user_id(a) is None


@pytest.mark.parametrize(
    "values", [{"min_salary": -1}, {"timezone_tolerance_hours": 5}, {"sources": []}]
)
async def test_database_rejects_invalid_scalar_and_source_values(pg, values):
    a, _ = await seed(pg)
    async with pg() as session:
        session.add(UserFilterORM(user_id=a, **values))
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_user_filter_unique_and_foreign_key_constraints(pg):
    a, _ = await seed(pg)
    async with pg() as session:
        session.add(UserFilterORM(user_id=a))
        await session.commit()
    for user_id in (a, 999999):
        async with pg() as session:
            session.add(UserFilterORM(user_id=user_id))
            with pytest.raises(IntegrityError):
                await session.commit()


async def test_failed_update_rolls_back_and_reset_preserves_notification_and_plan(pg):
    a, _ = await seed(pg)
    async with pg() as session:
        subscription = UserSubscriptionORM(
            user_id=a, status="trial", trial_ends_at=NOW + timedelta(days=7)
        )
        session.add(subscription)
        preferences = await session.scalar(
            select(UserNotificationSettingsORM).where(
                UserNotificationSettingsORM.user_id == a
            )
        )
        preferences.digest_time, preferences.min_score = time(11, 30), 82
        await session.commit()
        service = UserFilterService(session, owner_telegram_id=None)
        await service.update_list(a, "required_technologies", "add", "python")
        await service.update_list(a, "excluded_technologies", "add", "PYTHON")
        with pytest.raises(ValueError):
            await service.update_list(a, "required_technologies", "add", "python")
        assert (await service.get_filters(a)).required_technologies == []
        await service.toggle(a, "sources", "remoteok")
        await service.toggle(a, "sources", "getonboard")
        await service.toggle(a, "sources", "himalayas")
        await service.toggle(a, "sources", "jobicy")
        await service.toggle(a, "sources", "the_muse")
        with pytest.raises(ValueError):
            await service.toggle(a, "sources", "weworkremotely")
        assert (await service.get_filters(a)).sources == ["weworkremotely"]
        result = await service.reset(a)
        for field, expected in filter_defaults().items():
            assert getattr(result, field) == expected
        preferences = await session.scalar(
            select(UserNotificationSettingsORM).where(
                UserNotificationSettingsORM.user_id == a
            )
        )
        subscription = await session.scalar(
            select(UserSubscriptionORM).where(UserSubscriptionORM.user_id == a)
        )
        assert preferences.timezone == "UTC" and preferences.digest_time == time(11, 30)
        assert preferences.min_score == 82 and subscription.status == "trial"
        assert subscription.trial_ends_at == NOW + timedelta(days=7)


async def test_digest_two_users_different_saved_filters_and_no_repeat(pg):
    a, b = await seed(pg)
    async with pg() as session:
        service = UserFilterService(session, owner_telegram_id=None)
        await service.update_list(a, "required_technologies", "add", "python")
        await service.update_list(b, "required_technologies", "add", "javascript")
        row = job_to_orm(
            JobDTO(
                source="remoteok",
                external_id="1",
                title="Python developer",
                url="https://example.com/python",
                collected_at=NOW,
                remote=True,
                remote_regions=["worldwide"],
                technologies=["python"],
            ),
            "python-fingerprint",
        )
        session.add(row)
        await session.commit()
        job_id = row.id
    client = AsyncMock(spec=TelegramClient)
    client.send_message.return_value = 42
    digest = DailyDigestService(
        pg, client, EntitlementService(free_min_score=0), clock=lambda: NOW
    )
    result_a, result_b = await digest.send(a, run_now=True), await digest.send(
        b, run_now=True
    )
    assert result_a["status"] == "sent" and result_a["sent"] == 1
    assert result_b == {"status": "empty", "selected": 0, "sent": 0}
    assert [call.args[0] for call in client.send_message.call_args_list] == [
        1001,
        1001,
        1002,
    ]
    async with pg() as session:
        runs = {run.user_id: run for run in await session.scalars(select(DigestRunORM))}
        assert runs[a].accepted_count == 1 and runs[a].filter_rejected_count == 0
        assert runs[b].accepted_count == 0 and runs[b].filter_rejected_count == 1
        notifications = list(await session.scalars(select(NotificationORM)))
        assert len(notifications) == 1
        assert notifications[0].user_id == a and notifications[0].job_id == job_id
        assert notifications[0].status == "sent"
    # A new service on the next day must still exclude previously sent jobs.
    restarted = DailyDigestService(
        pg,
        client,
        EntitlementService(free_min_score=0),
        clock=lambda: NOW + timedelta(days=1),
    )
    assert (await restarted.send(a, run_now=True))["status"] == "empty"
    assert (await digest.send(a, run_now=True))["status"] == "empty"
    assert client.send_message.await_count == 5


async def test_local_telegram_scenario_persists_after_polling_restart(pg, fake_redis):
    a, _ = await seed(pg)
    client = AsyncMock(spec=TelegramClient)
    client.send_message.return_value = 42
    pending = PendingInputStore(fake_redis)
    dispatcher = AsyncMock(spec=CommandDispatcher)

    async def update(*, text=None, data=None):
        # Each update constructs fresh handlers/session, just like polling.
        async with pg() as session:
            users = UserRepository(session)
            handler = FiltersHandler(
                users,
                UserFilterService(session, owner_telegram_id=1001),
                client,
                pending,
            )
            commands = CommandHandler(
                users,
                BotQueryRepository(session),
                FeedbackRepository(session),
                client,
                dispatcher,
                EntitlementService(free_min_score=0),
                owner_telegram_id=1001,
                bot_username="ExampleBot",
                filters_handler=handler,
                clock=lambda: NOW,
            )
            sender, chat = {"id": 1001}, {"id": 1001, "type": "private"}
            payload = (
                {"message": {"from": sender, "chat": chat, "text": text}}
                if text is not None
                else {
                    "callback_query": {
                        "id": "query",
                        "from": sender,
                        "data": data,
                        "message": {"message_id": 42, "chat": chat},
                    }
                }
            )
            await route_update(
                payload, commands=commands, callbacks=AsyncMock(), filters=handler
            )

    await update(text="/filters")
    for screen, value in (("keywords", "python"), ("reqtech", "python")):
        await update(data=f"filters:{screen}:add")
        await update(text=value)
    await update(data="filters:preftech:clear")
    await update(data="filters:preftech:add")
    await update(text="fastapi, postgres, redis")
    for data in (
        "filters:experience:junior",
        "filters:experience:middle",
        "filters:employment:full_time",
        "filters:employment:contract",
        "filters:currency:USD",
        "filters:tz_tol:2",
    ):
        await update(data=data)
    await update(data="filters:min_salary")
    await update(text="$2500")
    assert await pending.get(1001) is not None
    await update(text="2500")
    await update(data="filters:keywords:add")
    await update(text="/cancel")
    assert await pending.get(1001) is None
    # A new Redis store and session emulate restarting polling.
    pending = PendingInputStore(fake_redis)
    await update(text="/filters")
    summary = client.send_message.call_args.args[1]
    for value in (
        "python",
        "fastapi",
        "postgresql",
        "redis",
        "Junior",
        "Middle",
        "Full-time",
        "Contract",
        "USD 2500",
        "Worldwide",
        "LATAM",
        "South America",
        "Uruguay",
        "±2h",
        "Get on Board",
    ):
        assert value in summary
    async with pg() as session:
        saved = await UserFilterService(session).get_filters(a)
        assert saved.required_technologies == saved.keywords == ["python"]
        assert saved.preferred_technologies == ["fastapi", "postgresql", "redis"]
        assert saved.remote_only and saved.exclude_us_only
        assert saved.timezone_tolerance_hours == 2
        assert saved.employment_types == ["full_time", "contract"]
        assert saved.experience_levels == ["junior", "middle"]
        assert saved.min_salary == 2500 and saved.currency == "USD"
        session.add(
            job_to_orm(
                JobDTO(
                    source="remoteok",
                    external_id="manual",
                    title="Python developer",
                    url="https://example.com/manual",
                    collected_at=NOW,
                    remote=True,
                    remote_regions=["worldwide"],
                    technologies=["python", "fastapi", "postgresql", "redis"],
                    salary_min=3000,
                    currency="USD",
                    employment_type="full_time",
                    experience_level="junior",
                ),
                "manual-fingerprint",
            )
        )
        await session.commit()
    await update(text="/digest")
    dispatcher.digest.assert_awaited_once_with(a)
    digest = DailyDigestService(
        pg, client, EntitlementService(free_min_score=0), clock=lambda: NOW
    )
    assert (await digest.send(a, run_now=True))["sent"] == 1
    count = client.send_message.await_count
    await update(text="/digest")
    assert client.send_message.call_args.args[1] == "Digest queued."
    assert dispatcher.digest.await_count == 2
    assert client.send_message.await_count == count + 1
    assert (await digest.send(a, run_now=True))["status"] == "empty"
    assert client.send_message.call_args.args[1] == "No new jobs match your filters."
