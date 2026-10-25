import logging
from datetime import time
from zoneinfo import ZoneInfo

from src.bot.client import TelegramAPIError, TelegramClient
from src.bot.pending_input import PendingInput, PendingInputStore
from src.i18n import (
    DEFAULT_LANGUAGE,
    LANGUAGE_NAMES,
    SUPPORTED_LANGUAGES,
    Language,
    display_label,
    initial_language,
    t,
    user_language,
    validation_message,
)
from src.repositories.users import UserRepository
from src.services.notification_settings import (
    NotificationSettingsService,
    NotificationSettingsView,
    PremiumRequired,
    SettingsUnavailable,
)
from src.services.user_language import UserLanguageService

logger = logging.getLogger(__name__)
TIMEZONES = (
    "UTC",
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "America/Mexico_City",
    "America/Sao_Paulo",
    "America/Montevideo",
    "America/Argentina/Buenos_Aires",
    "Europe/London",
    "Europe/Madrid",
    "Europe/Berlin",
    "Asia/Dubai",
    "Asia/Kolkata",
    "Asia/Singapore",
    "Asia/Tokyo",
    "Africa/Johannesburg",
    "Africa/Cairo",
    "Australia/Sydney",
    "Pacific/Auckland",
)
TIMES = {f"{hour:02d}00": time(hour) for hour in (7, 8, 9, 10, 12, 18, 20)}
SCORES = (50, 60, 70, 75, 80, 85, 90)


def button(text: str, data: str) -> dict:
    return {"text": text, "callback_data": data}


def settings_back(language: Language) -> list[dict]:
    return [button(t("common.back", language), "settings:back")]


def build_settings_keyboard(language: Language = DEFAULT_LANGUAGE) -> dict:
    return {
        "inline_keyboard": [
            [button(t("language.title", language), "settings:language")],
            [button(t("settings.timezone_button", language), "settings:timezone")],
            [button(t("settings.time_button", language), "settings:time")],
            [button(t("settings.score_button", language), "settings:score")],
            [button(t("common.back", language), "settings:close")],
        ]
    }


def build_language_keyboard(
    language: Language = DEFAULT_LANGUAGE, *, onboarding: bool = False
) -> dict:
    flags = {Language.EN: "🇬🇧", Language.ES: "🇪🇸"}
    rows = [
        [
            button(
                f"{flags[locale]} {LANGUAGE_NAMES[locale]}"
                + (" ✅" if locale == language and not onboarding else ""),
                f"settings:language:{locale.value}",
            )
        ]
        for locale in SUPPORTED_LANGUAGES
    ]
    if not onboarding:
        rows.append(settings_back(language))
    return {"inline_keyboard": rows}


BACK = settings_back(DEFAULT_LANGUAGE)
ROOT = build_settings_keyboard()


def format_settings(
    view: NotificationSettingsView, language: Language = DEFAULT_LANGUAGE
) -> str:
    effective = view.effective
    enabled = t(
        "common.enabled" if effective.digest_enabled else "common.disabled", language
    )
    sections = [
        t("settings.title", language),
        f"{t('language.title', language)}:\n{LANGUAGE_NAMES[language]}",
        f"{t('settings.timezone', language)}:\n{effective.timezone}",
        f"{t('settings.digest_time', language)}:\n{effective.digest_time:%H:%M}",
        f"{t('settings.min_score', language)}:\n{effective.min_score}%",
        f"{t('settings.plan', language)}:\n{display_label(view.plan, language)}",
        f"🔔 {t('settings.digest_time', language)}: {enabled}",
    ]
    if view.trial_ends_at is not None:
        end = view.trial_ends_at.astimezone(ZoneInfo(effective.timezone))
        sections.append(f"{t('settings.trial_ends', language)}:\n{end:%Y-%m-%d}")
    if not effective.premium:
        sections.extend(
            (t("settings.custom_time", language), t("settings.custom_score", language))
        )
    return "\n\n".join(sections)


def locked_text(
    view: NotificationSettingsView, kind: str, language: Language = DEFAULT_LANGUAGE
) -> str:
    value = (
        f"{view.effective.digest_time:%H:%M}"
        if kind == "time"
        else view.effective.min_score
    )
    return t(f"settings.locked_{kind}", language, value=value)


class SettingsHandler:
    def __init__(
        self,
        users: UserRepository,
        service: NotificationSettingsService,
        client: TelegramClient,
        *,
        help_text: str,
        languages: UserLanguageService | None = None,
        pending: PendingInputStore | None = None,
    ):
        self.users, self.service, self.client = users, service, client
        self.help_text, self.languages = help_text, languages
        self.pending = pending

    async def show(
        self, user_id: int, chat_id: int, language: Language = DEFAULT_LANGUAGE
    ) -> None:
        if self.pending is not None:
            await self.pending.clear(chat_id)
        try:
            try:
                view = await self.service.get(user_id)
            except SettingsUnavailable:
                await self.client.send_message(
                    chat_id, t("settings.unavailable", language)
                )
            else:
                await self.client.send_message(
                    chat_id,
                    format_settings(view, language),
                    build_settings_keyboard(language),
                )
        except TelegramAPIError:
            logger.warning("Settings reply failed")

    async def handle(self, callback: dict) -> None:
        if not isinstance(callback, dict):
            return
        callback_id = callback.get("id")
        if not isinstance(callback_id, str) or not callback_id:
            return
        sender = callback.get("from")
        language = initial_language(
            sender.get("language_code") if isinstance(sender, dict) else None
        )
        answer = t("settings.not_available", language)
        acknowledged = False
        try:
            message = callback.get("message")
            if not isinstance(sender, dict) or not isinstance(message, dict):
                return
            chat = message.get("chat")
            sender_id, message_id = sender.get("id"), message.get("message_id")
            if (
                type(sender_id) is not int
                or not 0 < sender_id < 2**63
                or sender.get("is_bot") is True
                or not isinstance(chat, dict)
                or chat.get("type") != "private"
                or type(chat.get("id")) is not int
                or chat["id"] != sender_id
                or type(message_id) is not int
                or message_id <= 0
            ):
                return
            user = await self.users.get_by_telegram_id(sender_id)
            language = user_language(user, sender.get("language_code"))
            answer = t("settings.not_available", language)
            if user is None or not user.is_active:
                return
            user_id = user.id
            data = callback.get("data")
            if not isinstance(data, str):
                return
            if self.pending is not None:
                await self.pending.clear(sender_id)
            back = settings_back(language)
            if data == "settings:language":
                text = t("language.menu", language, name=LANGUAGE_NAMES[language])
                markup = build_language_keyboard(language)
                answer = None
            elif data.startswith("settings:language:"):
                value = data.removeprefix("settings:language:")
                if (
                    value not in {locale.value for locale in SUPPORTED_LANGUAGES}
                    or self.languages is None
                ):
                    return
                language = await self.languages.update_language(
                    user_id, Language(value)
                )
                answer = t("language.updated", language, name=LANGUAGE_NAMES[language])
                await self.client.answer_callback_query(callback_id, answer)
                acknowledged = True
                # Language choice is free and independent of notification settings.
                try:
                    view = await self.service.get(user_id)
                except SettingsUnavailable:
                    text = t("language.menu", language, name=LANGUAGE_NAMES[language])
                    markup = build_language_keyboard(language)
                else:
                    text, markup = format_settings(
                        view, language
                    ), build_settings_keyboard(language)
            else:
                view = await self.service.get(user_id)
                text, markup = format_settings(view, language), build_settings_keyboard(
                    language
                )
                if data == "settings:close":
                    text, markup = t("help.public", language), {"inline_keyboard": []}
                elif data == "settings:back":
                    pass
                elif data == "settings:timezone":
                    text = t("settings.choose_timezone", language)
                    markup = {
                        "inline_keyboard": [
                            *[[button(zone, f"tz:{zone}")] for zone in TIMEZONES],
                            [
                                button(
                                    t("settings.custom_timezone", language),
                                    "settings:custom_timezone",
                                )
                            ],
                            back,
                        ]
                    }
                elif data == "settings:custom_timezone" and self.pending is not None:
                    await self.pending.set(
                        sender_id, PendingInput("settings:timezone", message_id)
                    )
                    text = t("input.timezone", language) + t("input.expiry", language)
                    markup = {"inline_keyboard": [back]}
                elif data in ("settings:time", "settings:score"):
                    kind = data.split(":")[1]
                    if not view.effective.premium:
                        text, markup = locked_text(view, kind, language), {
                            "inline_keyboard": [back]
                        }
                    else:
                        text = t(f"settings.choose_{kind}", language)
                        buttons = (
                            [
                                button(f"{value:%H:%M}", f"time:{key}")
                                for key, value in TIMES.items()
                            ]
                            if kind == "time"
                            else [
                                button(f"{score}%", f"score:{score}")
                                for score in SCORES
                            ]
                        )
                        markup = {
                            "inline_keyboard": [
                                *[
                                    buttons[i : i + 2]
                                    for i in range(0, len(buttons), 2)
                                ],
                                back,
                            ]
                        }
                else:
                    prefix, _, value = data.partition(":")
                    try:
                        if prefix == "tz" and value in TIMEZONES:
                            await self.service.update_timezone(user_id, value)
                            answer = t(
                                "settings.timezone_updated", language, value=value
                            )
                        elif prefix == "time" and value in TIMES:
                            await self.service.update_digest_time(user_id, TIMES[value])
                            answer = t(
                                "settings.time_updated",
                                language,
                                value=f"{TIMES[value]:%H:%M}",
                            )
                        elif prefix == "score" and value in {str(s) for s in SCORES}:
                            await self.service.update_min_score(user_id, int(value))
                            answer = t("settings.score_updated", language, value=value)
                        else:
                            return
                    except PremiumRequired:
                        view = await self.service.get(user_id)
                        text = locked_text(view, prefix, language)
                        markup = {"inline_keyboard": [back]}
                        answer = t("settings.premium_required", language)
                    else:
                        view = await self.service.get(user_id)
                        text = f"{answer}\n\n{format_settings(view, language)}"
                if answer == t("settings.not_available", language):
                    answer = None
            await self.client.edit_message_text(sender_id, message_id, text, markup)
        except SettingsUnavailable:
            answer = t("settings.unavailable", language)
        except ValueError as exc:
            answer = validation_message(exc, language)
        except Exception:
            logger.warning("Settings callback failed")
            answer = t("settings.edit_failed", language)
        finally:
            if not acknowledged:
                try:
                    await self.client.answer_callback_query(callback_id, answer)
                except TelegramAPIError:
                    logger.warning("Settings callback acknowledgment failed")

    async def handle_input(self, message: dict) -> bool:
        if self.pending is None:
            return False
        sender, chat, text = (
            message.get("from"),
            message.get("chat"),
            message.get("text"),
        )
        if (
            not isinstance(sender, dict)
            or not isinstance(chat, dict)
            or not isinstance(text, str)
            or text.startswith("/")
        ):
            return False
        sender_id = sender.get("id")
        if (
            type(sender_id) is not int
            or not 0 < sender_id < 2**63
            or sender.get("is_bot") is True
            or chat.get("type") != "private"
            or type(chat.get("id")) is not int
            or chat["id"] != sender_id
        ):
            return False
        state = await self.pending.get(sender_id)
        if state is None or state.action != "settings:timezone":
            return False
        user = await self.users.get_by_telegram_id(sender_id)
        if user is None or not user.is_active:
            await self.pending.clear(sender_id)
            return True
        language = user_language(user)
        try:
            await self.service.update_timezone(user.id, text.strip())
        except ValueError as exc:
            body = t("input.retry", language, error=validation_message(exc, language))
            markup = {"inline_keyboard": [settings_back(language)]}
        except SettingsUnavailable:
            await self.pending.clear(sender_id)
            return True
        else:
            # Clear before rendering: a failed Telegram edit must not replay a write.
            await self.pending.clear(sender_id)
            view = await self.service.get(user.id)
            body = (
                t("settings.timezone_updated", language, value=text.strip())
                + "\n\n"
                + format_settings(view, language)
            )
            markup = build_settings_keyboard(language)
        try:
            await self.client.edit_message_text(
                sender_id, state.message_id, body, markup
            )
        except TelegramAPIError:
            logger.warning("Timezone input reply failed")
        return True
