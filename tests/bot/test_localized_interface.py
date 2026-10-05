from datetime import UTC, datetime, time
from unittest.mock import AsyncMock

import pytest

from src.bot.callbacks import CallbackHandler
from src.bot.client import TelegramClient
from src.bot.commands import CommandHandler
from src.bot.dispatch import CommandDispatcher
from src.bot.filters import ROOT_ITEMS, FiltersHandler, render_screen
from src.bot.formatter import build_job_keyboard, format_job_message
from src.bot.pending_input import PendingInputStore
from src.bot.settings import (
    SettingsHandler,
    build_language_keyboard,
    build_settings_keyboard,
)
from src.i18n import Language, LocalizedValidationError, t
from src.models import JobORM, UserFilterORM, UserNotificationSettingsORM, UserORM
from src.repositories.bot_queries import BotQueryRepository
from src.repositories.feedback import FeedbackRepository
from src.repositories.jobs import JobRepository
from src.repositories.users import UserRepository
from src.schemas.job import JobDTO
from src.schemas.scoring import ScoreResult
from src.services.entitlements import EffectiveNotificationSettings, EntitlementService
from src.services.feedback import FeedbackService
from src.services.notification_settings import (
    NotificationSettingsService,
    NotificationSettingsView,
)
from src.services.user_filters import UserFilterService, filter_defaults, filters_to_dto
from src.services.user_language import UserLanguageService

NOW = datetime(2026, 10, 5, 12, tzinfo=UTC)


def message(text, code="es-UY"):
    return {
        "text": text,
        "from": {"id": 123, "language_code": code},
        "chat": {"id": 123, "type": "private"},
    }


def callback(data):
    return {
        "id": "query",
        "from": {"id": 123, "language_code": "es-UY"},
        "data": data,
        "message": {"message_id": 42, "chat": {"id": 123, "type": "private"}},
    }


@pytest.fixture
def localized(fake_redis):
    user = UserORM(id=7, telegram_id=123, is_active=True, language=Language.EN)
    users = AsyncMock(spec=UserRepository)
    users.get_by_telegram_id.return_value = user
    queries = AsyncMock(spec=BotQueryRepository)
    queries.preferences.return_value = UserNotificationSettingsORM(
        timezone="UTC",
        digest_time=time(9),
        min_score=0,
        max_jobs_per_digest=10,
        digest_enabled=True,
    )
    queries.subscription.return_value = None
    queries.collector_states.return_value = []
    queries.last_digest.return_value = None
    queries.job_count.return_value = 5
    feedback = AsyncMock(spec=FeedbackRepository)
    feedback.get_saved_jobs_for_user.return_value = []
    client = AsyncMock(spec=TelegramClient)
    languages = AsyncMock(spec=UserLanguageService)
    languages.register.return_value = user

    async def update(user_id, language):
        user.language = language
        return language

    languages.update_language.side_effect = update
    preferences = AsyncMock(spec=NotificationSettingsService)
    preferences.get.return_value = NotificationSettingsView(
        EffectiveNotificationSettings("UTC", time(9), 0, 10, True, False), "Free", None
    )
    settings = SettingsHandler(
        users, preferences, client, help_text=t("help.public"), languages=languages
    )
    service = AsyncMock(spec=UserFilterService)
    service.get_filters.return_value = filters_to_dto(
        UserFilterORM(user_id=7, **filter_defaults()), "UTC"
    )
    filters = FiltersHandler(users, service, client, PendingInputStore(fake_redis))
    commands = CommandHandler(
        users,
        queries,
        feedback,
        client,
        AsyncMock(spec=CommandDispatcher),
        EntitlementService(),
        owner_telegram_id=123,
        bot_username="ExampleBot",
        settings_handler=settings,
        filters_handler=filters,
        languages=languages,
        clock=lambda: NOW,
    )
    return user, commands, settings, filters, client


@pytest.mark.parametrize("language", list(Language))
@pytest.mark.parametrize(
    "command,key",
    [
        ("start", "start.welcome"),
        ("help", "help.public"),
        ("settings", "settings.title"),
        ("filters", "filters.title"),
        ("saved", "saved.empty"),
        ("digest", "digest.queued"),
        ("cancel", "input.cancelled"),
    ],
)
async def test_commands_use_saved_locale_not_telegram_locale(
    localized, language, command, key
):
    user, commands, _, _, client = localized
    user.language = language
    await commands.handle(message("/" + command))
    assert t(key, language) in client.send_message.call_args.args[1]
    assert commands.users.get_by_telegram_id.await_count == 1


@pytest.mark.parametrize(
    "language,expected",
    [
        (Language.EN, "Jobs in database: 5"),
        (Language.ES, "Vacantes en la base de datos: 5"),
    ],
)
async def test_status_localized_without_changing_data(localized, language, expected):
    user, commands, _, _, client = localized
    user.language = language
    await commands.handle(message("/status"))
    text = client.send_message.call_args.args[1]
    assert expected in text and "09:00" in text and "UTC" in text
    assert "Remote OK" in text and "Get on Board" in text


async def test_language_changes_immediately_and_acknowledges_before_edit(localized):
    user, commands, settings, _, client = localized
    events = []

    async def answer(*args, **kwargs):
        assert user.language == Language.ES
        events.append("answer")

    async def edit(*args, **kwargs):
        events.append("edit")

    client.answer_callback_query.side_effect = answer
    client.edit_message_text.side_effect = edit
    await settings.handle(callback("settings:language:es"))
    assert events == ["answer", "edit"]
    assert "Configuración" in client.edit_message_text.call_args.args[2]
    assert "Idioma" in client.edit_message_text.call_args.args[2]
    for command in ("help", "filters", "status", "digest"):
        await commands.handle(message("/" + command, code="en"))
        assert client.send_message.call_args.args[1] != t(
            {
                "help": "help.public",
                "filters": "filters.title",
                "status": "settings.title",
                "digest": "digest.queued",
            }[command],
            Language.EN,
        )
    client.answer_callback_query.side_effect = None
    await settings.handle(callback("settings:language:en"))
    assert user.language == Language.EN
    assert "⚙️ Settings" in client.edit_message_text.call_args.args[2]


@pytest.mark.parametrize("language", list(Language))
async def test_new_start_language_picker(localized, language):
    _, commands, _, _, client = localized
    commands.users.get_by_telegram_id.return_value = None
    commands.languages.register.return_value = UserORM(
        id=8, telegram_id=123, is_active=True, language=language
    )
    await commands.handle(message("/start", language.value))
    commands.languages.register.assert_awaited_once_with(123, language.value)
    assert client.send_message.call_args.args[1] == t("language.choose", language)
    assert client.send_message.call_args.args[2] == build_language_keyboard(
        language, onboarding=True
    )


def callback_values(keyboard):
    return [
        button.get("callback_data", button.get("url"))
        for row in keyboard["inline_keyboard"]
        for button in row
    ]


def test_all_filter_and_settings_callback_data_language_independent():
    filters = filters_to_dto(UserFilterORM(user_id=7, **filter_defaults()), "UTC")
    for _, screen in ROOT_ITEMS:
        en, es = render_screen(filters, screen, Language.EN), render_screen(
            filters, screen, Language.ES
        )
        assert callback_values(en[1]) == callback_values(es[1])
        assert len(es[0].encode("utf-16-le")) // 2 < 4096
    assert callback_values(build_settings_keyboard(Language.EN)) == callback_values(
        build_settings_keyboard(Language.ES)
    )
    assert callback_values(build_language_keyboard(Language.EN)) == callback_values(
        build_language_keyboard(Language.ES)
    )


async def test_spanish_pending_prompt_validation_and_cancel(localized):
    user, commands, _, filters, client = localized
    user.language = Language.ES
    await filters.handle(callback("filters:keywords:add"))
    assert "Enviá las palabras clave" in client.edit_message_text.call_args.args[2]
    filters.service.update_list.side_effect = LocalizedValidationError(
        "error.empty_list"
    )
    await filters.handle_input(message(" , "))
    assert "Enviá al menos un valor" in client.edit_message_text.call_args.args[2]
    assert await filters.pending.get(123) is not None
    await commands.handle(message("/cancel"))
    assert client.send_message.call_args.args[1] == "Entrada cancelada."
    assert await filters.pending.get(123) is None


@pytest.mark.parametrize("language", list(Language))
async def test_feedback_localized_with_original_callback(localized, language):
    user, commands, _, _, client = localized
    user.language = language
    jobs = AsyncMock(spec=JobRepository)
    jobs.get_by_id.return_value = JobORM(id=42)
    feedback = AsyncMock(spec=FeedbackService)
    await CallbackHandler(commands.users, jobs, feedback, client).handle(
        callback("save:42")
    )
    assert client.answer_callback_query.call_args.kwargs["text"] == t(
        "feedback.saved", language
    )
    feedback.set_feedback.assert_awaited_once_with(7, 42, "saved")


def test_notification_labels_and_content_are_preserved_in_both_languages():
    job = JobDTO(
        source="remoteok",
        external_id="1",
        title="Python {Backend} <Engineer>",
        company="Original Company",
        description="Untranslated description",
        url="https://example.com/original",
        remote=True,
        remote_regions=["worldwide"],
        technologies=["python", "redis"],
        employment_type="full_time",
        experience_level="middle",
        salary_min=2500,
        currency="USD",
    )
    before = job.model_dump()
    for language in Language:
        text = format_job_message(
            job, ScoreResult(score=82, matched_rules=["Remote: +10"]), language
        )
        for key in ("job.company", "job.salary", "job.experience"):
            assert t(key, language) in text
        assert job.title in text and job.company in text and "USD" in text
        assert "Python" in text and "Redis" in text and "Remote OK" in text
        keyboard = build_job_keyboard(42, job.url, language)
        assert keyboard["inline_keyboard"][0][0] == {
            "text": t("job.open", language),
            "url": job.url,
        }
        assert keyboard["inline_keyboard"][1][0]["text"] == t("job.save", language)
        assert callback_values(keyboard) == [job.url, "save:42", "reject:42"]
    assert job.model_dump() == before
