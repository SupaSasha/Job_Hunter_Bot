from datetime import UTC, datetime, time
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
from src.bot.settings import SettingsHandler
from src.bot.updates import route_update
from src.i18n import Language, LocalizedValidationError
from src.models import (
    DigestRunORM,
    NotificationORM,
    UserNotificationSettingsORM,
    UserORM,
    UserSubscriptionORM,
)
from src.repositories.bot_queries import BotQueryRepository
from src.repositories.feedback import FeedbackRepository
from src.repositories.users import UserRepository
from src.schemas.job import JobDTO
from src.services.digests import DailyDigestService
from src.services.entitlements import EntitlementService
from src.services.jobs import job_to_orm
from src.services.notification_settings import NotificationSettingsService
from src.services.user_filters import UserFilterService
from src.services.user_language import UserLanguageService
from src.services.users import OwnerService

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 5, 12, tzinfo=UTC)


async def test_new_user_default_telegram_language_and_persistent_manual_choice(pg):
    async with pg() as session:
        default = await OwnerService(session).get_or_create(1001)
        assert default.language == Language.EN
        service = UserLanguageService(session)
        spanish = await service.register(1002, "es-UY")
        assert spanish.language == Language.ES
        user_id = spanish.id
        await service.update_language(user_id, Language.EN)
    async with pg() as session:
        service = UserLanguageService(session)
        existing = await service.register(1002, "es")
        assert existing.id == user_id and existing.language == Language.EN
        await service.update_language(user_id, Language.ES)
    async with pg() as session:
        assert (
            await UserRepository(session).get_by_id(user_id)
        ).language == Language.ES
        assert await session.scalar(select(func.count()).select_from(UserORM)) == 2


async def test_language_validation_and_registration_do_not_reset_preferences_or_trial(
    pg,
):
    async with pg() as session:
        user = await UserLanguageService(session).register(1001, "es")
        user_id = user.id
        preferences = await session.scalar(
            select(UserNotificationSettingsORM).where(
                UserNotificationSettingsORM.user_id == user_id
            )
        )
        preferences.timezone, preferences.digest_time, preferences.min_score = (
            "UTC",
            time(11),
            85,
        )
        subscription = await session.scalar(
            select(UserSubscriptionORM).where(UserSubscriptionORM.user_id == user_id)
        )
        subscription.status = "expired"
        trial_end = subscription.trial_ends_at
        await session.commit()
        with pytest.raises(LocalizedValidationError):
            await UserLanguageService(session).update_language(user_id, "pt")
        await UserLanguageService(session).register(1001, "en")
        await UserLanguageService(session).update_language(user_id, Language.EN)
    async with pg() as session:
        preferences = await session.scalar(
            select(UserNotificationSettingsORM).where(
                UserNotificationSettingsORM.user_id == user_id
            )
        )
        subscription = await session.scalar(
            select(UserSubscriptionORM).where(UserSubscriptionORM.user_id == user_id)
        )
        assert (
            preferences.timezone,
            preferences.digest_time,
            preferences.min_score,
        ) == ("UTC", time(11), 85)
        assert (
            subscription.status == "expired" and subscription.trial_ends_at == trial_end
        )
        user = await session.get(UserORM, user_id)
        user.language = "pt"
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_language_migration_backfills_existing_user_and_preserves_data(pg):
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    async with pg() as session:
        connection = await session.connection()

        def downgrade(connection):
            config.attributes["connection"] = connection
            command.downgrade(config, "c41a9e327b60")

        await connection.run_sync(downgrade)
        await session.execute(
            text(
                "INSERT INTO users (telegram_id, username, is_active) "
                "VALUES (1001, 'example', false)"
            )
        )
        await session.commit()
    async with pg() as session:
        connection = await session.connection()

        def upgrade(connection):
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            command.check(config)

        await connection.run_sync(upgrade)
        await session.commit()
        user = await UserRepository(session).get_by_telegram_id(1001)
        assert (
            user.language == Language.EN
            and user.username == "example"
            and not user.is_active
        )
        assert await session.scalar(select(func.count()).select_from(UserORM)) == 1


async def test_two_language_digest_same_selection_different_presentation(pg):
    ids = []
    async with pg() as session:
        for telegram_id, language in ((1001, Language.EN), (1002, Language.ES)):
            user = await UserLanguageService(session).register(
                telegram_id, language.value
            )
            ids.append(user.id)
            service = UserFilterService(session, owner_telegram_id=None)
            await service.update_list(user.id, "required_technologies", "add", "python")
            await service.update_list(
                user.id, "preferred_technologies", "add", "python"
            )
        job = JobDTO(
            source="remoteok",
            external_id="locale",
            title="Original Python Title",
            company="Original Company",
            url="https://example.com/localization",
            description="Original description",
            collected_at=NOW,
            remote=True,
            remote_regions=["worldwide"],
            technologies=["python"],
            salary_min=2500,
            currency="USD",
            experience_level="middle",
        )
        session.add(job_to_orm(job, "locale-fingerprint"))
        await session.commit()
    client = AsyncMock(spec=TelegramClient)
    client.send_message.return_value = 42
    digest = DailyDigestService(
        pg, client, EntitlementService(free_min_score=0), clock=lambda: NOW
    )
    results = [await digest.send(user_id, run_now=True) for user_id in ids]
    assert all(result["status"] == "sent" and result["sent"] == 1 for result in results)
    english, spanish = [call.args[1] for call in client.send_message.call_args_list][
        1::2
    ]
    assert "Company:" in english and "Empresa:" in spanish
    assert "Experience:" in english and "Experiencia:" in spanish
    assert "new job matches" in client.send_message.call_args_list[0].args[1]
    assert (
        "nuevas vacantes compatibles" in client.send_message.call_args_list[2].args[1]
    )
    for body in (english, spanish):
        assert job.title in body and job.company in body and "Remote OK" in body
    for call, language_label in zip(
        client.send_message.call_args_list[1::2], ("Save", "Guardar")
    ):
        keyboard = call.kwargs["reply_markup"]["inline_keyboard"]
        assert keyboard[0][0]["url"] == job.url
        assert keyboard[1][0]["text"] == language_label
    async with pg() as session:
        runs = list(await session.scalars(select(DigestRunORM)))
        notifications = list(await session.scalars(select(NotificationORM)))
        assert len(notifications) == len(runs) == 2
        assert notifications[0].score == notifications[1].score
        assert runs[0].accepted_count == runs[1].accepted_count == 1
        assert runs[0].filter_rejected_count == runs[1].filter_rejected_count == 0


async def test_manual_language_switch_restart_and_all_commands(pg, fake_redis):
    client = AsyncMock(spec=TelegramClient)
    client.send_message.return_value = 42
    dispatcher = AsyncMock(spec=CommandDispatcher)
    pending = PendingInputStore(fake_redis)
    user_id = None

    async def update(text_value=None, data=None, code="en"):
        async with pg() as session:
            users = UserRepository(session)
            languages = UserLanguageService(session)
            entitlements = EntitlementService()
            settings = SettingsHandler(
                users,
                NotificationSettingsService(session, entitlements),
                client,
                help_text="",
                languages=languages,
            )
            filters = FiltersHandler(
                users,
                UserFilterService(session, owner_telegram_id=None),
                client,
                pending,
            )
            commands = CommandHandler(
                users,
                BotQueryRepository(session),
                FeedbackRepository(session),
                client,
                dispatcher,
                entitlements,
                owner_telegram_id=1001,
                bot_username="ExampleBot",
                settings_handler=settings,
                filters_handler=filters,
                languages=languages,
                clock=lambda: NOW,
            )
            sender, chat = {"id": 1001, "language_code": code}, {
                "id": 1001,
                "type": "private",
            }
            payload = (
                {"message": {"from": sender, "chat": chat, "text": text_value}}
                if text_value is not None
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
                payload,
                commands=commands,
                callbacks=AsyncMock(),
                settings=settings,
                filters=filters,
            )

    await update("/start", code="es-UY")
    assert "Elegí tu idioma" in client.send_message.call_args.args[1]
    await update(data="settings:language:en")
    assert "⚙️ Settings" in client.edit_message_text.call_args.args[2]
    await update("/settings")
    await update(data="settings:language")
    await update(data="settings:language:es")
    assert "⚙️ Configuración" in client.edit_message_text.call_args.args[2]
    for cmd, phrase in (
        ("filters", "Filtros de empleo"),
        ("help", "Comandos disponibles"),
        ("status", "Estado"),
        ("saved", "Todavía no guardaste"),
        ("digest", "Preparando tu resumen"),
    ):
        await update("/" + cmd)
        assert phrase in client.send_message.call_args.args[1]
    await update(data="filters:keywords:add")
    assert "Enviá las palabras clave" in client.edit_message_text.call_args.args[2]
    await update(" , ")
    assert "Enviá al menos un valor" in client.edit_message_text.call_args.args[2]
    await update("python")
    assert (
        "Filtros de empleo actualizados" in client.edit_message_text.call_args.args[2]
    )
    await update(data="settings:language:en")
    pending = PendingInputStore(fake_redis)
    await update("/start", code="es-UY")
    assert "I search for remote jobs" in client.send_message.call_args.args[1]
    await update("/filters", code="es")
    assert "🔎 Job filters" in client.send_message.call_args.args[1]
    async with pg() as session:
        user = await UserRepository(session).get_by_telegram_id(1001)
        user_id = user.id
        assert user.language == Language.EN
        assert (await UserFilterService(session).get_filters(user_id)).keywords == [
            "python"
        ]
