import logging
from datetime import time
from zoneinfo import ZoneInfo

from src.bot.client import TelegramAPIError, TelegramClient
from src.repositories.users import UserRepository
from src.services.notification_settings import (
    NotificationSettingsService,
    NotificationSettingsView,
    PremiumRequired,
    SettingsUnavailable,
)

logger = logging.getLogger(__name__)

TIMEZONES = (
    "America/Montevideo",
    "America/Sao_Paulo",
    "America/Argentina/Buenos_Aires",
    "America/New_York",
    "America/Los_Angeles",
    "Europe/London",
    "Europe/Madrid",
    "UTC",
)
TIMES = {f"{hour:02d}00": time(hour) for hour in (7, 8, 9, 10, 12, 18, 20)}
SCORES = (50, 60, 70, 75, 80, 85, 90)


def button(text: str, data: str) -> dict:
    return {"text": text, "callback_data": data}


BACK = [button("← Back", "settings:back")]
ROOT = {
    "inline_keyboard": [
        [button("🌎 Timezone", "settings:timezone")],
        [button("🕐 Digest time", "settings:time")],
        [button("🎯 Minimum score", "settings:score")],
        [button("← Back", "settings:close")],
    ]
}


def format_settings(view: NotificationSettingsView) -> str:
    effective = view.effective
    text = (
        f"⚙️ Settings\n\nTimezone:\n{effective.timezone}\n\n"
        f"Daily digest:\n{effective.digest_time:%H:%M}\n\n"
        f"Minimum match score:\n{effective.min_score}%\n\nPlan:\n{view.plan}"
    )
    if view.trial_ends_at is not None:
        end = view.trial_ends_at.astimezone(ZoneInfo(effective.timezone))
        text += f"\n\nTrial ends:\n{end:%Y-%m-%d}"
    if not effective.premium:
        text += "\n\nCustom digest time 🔒\nCustom minimum score 🔒"
    return text


def locked_text(view: NotificationSettingsView, kind: str) -> str:
    effective = view.effective
    if kind == "time":
        label, current = (
            "digest time",
            f"delivery time is {effective.digest_time:%H:%M}",
        )
    else:
        label, current = "minimum score", f"minimum score is {effective.min_score}%"
    return (
        f"Custom {label} is available during the trial or with Premium.\n\n"
        f"Your current {current}."
    )


class SettingsHandler:
    def __init__(
        self,
        users: UserRepository,
        service: NotificationSettingsService,
        client: TelegramClient,
        *,
        help_text: str,
    ):
        self.users = users
        self.service = service
        self.client = client
        self.help_text = help_text

    async def show(self, user_id: int, chat_id: int) -> None:
        try:
            try:
                view = await self.service.get(user_id)
            except SettingsUnavailable:
                await self.client.send_message(
                    chat_id, "Notification settings are not available yet."
                )
            else:
                await self.client.send_message(chat_id, format_settings(view), ROOT)
        except TelegramAPIError:
            logger.warning("Settings reply failed")

    async def handle(self, callback: dict) -> None:
        if not isinstance(callback, dict):
            return
        callback_id = callback.get("id")
        if not isinstance(callback_id, str) or not callback_id:
            return
        answer = "This setting is not available."
        try:
            sender = callback.get("from")
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
            if user is None or not user.is_active:
                return
            # Keep scalars before a service rollback can expire ORM attributes.
            user_id = user.id
            data = callback.get("data")
            if not isinstance(data, str):
                return
            view = await self.service.get(user_id)
            text, markup = format_settings(view), ROOT
            if data == "settings:close":
                text, markup = self.help_text, {"inline_keyboard": []}
            elif data == "settings:back":
                pass
            elif data == "settings:timezone":
                text = "Choose your timezone."
                markup = {
                    "inline_keyboard": [
                        *[[button(zone, f"tz:{zone}")] for zone in TIMEZONES],
                        BACK,
                    ]
                }
            elif data in ("settings:time", "settings:score"):
                kind = data.split(":")[1]
                if not view.effective.premium:
                    text, markup = locked_text(view, kind), {"inline_keyboard": [BACK]}
                else:
                    text = (
                        "Choose your daily digest time."
                        if kind == "time"
                        else "Choose your minimum match score."
                    )
                    buttons = (
                        [
                            button(f"{value:%H:%M}", f"time:{key}")
                            for key, value in TIMES.items()
                        ]
                        if kind == "time"
                        else [button(f"{score}%", f"score:{score}") for score in SCORES]
                    )
                    markup = {
                        "inline_keyboard": [
                            *[buttons[i : i + 2] for i in range(0, len(buttons), 2)],
                            BACK,
                        ]
                    }
            else:
                prefix, _, value = data.partition(":")
                try:
                    if prefix == "tz" and value in TIMEZONES:
                        await self.service.update_timezone(user_id, value)
                        answer = f"Timezone updated to {value}."
                    elif prefix == "time" and value in TIMES:
                        await self.service.update_digest_time(user_id, TIMES[value])
                        answer = f"Digest time updated to {TIMES[value]:%H:%M}."
                    elif prefix == "score" and value in {str(s) for s in SCORES}:
                        await self.service.update_min_score(user_id, int(value))
                        answer = f"Minimum score updated to {value}%."
                    else:
                        return
                except PremiumRequired:
                    view = await self.service.get(user_id)
                    text = locked_text(view, prefix)
                    markup = {"inline_keyboard": [BACK]}
                    answer = "This setting requires Trial or Premium."
                else:
                    view = await self.service.get(user_id)
                    text = f"{answer}\n\n{format_settings(view)}"
            if answer == "This setting is not available.":
                answer = None
            await self.client.edit_message_text(sender_id, message_id, text, markup)
        except SettingsUnavailable:
            answer = "Notification settings are not available yet."
        except ValueError:
            answer = "Invalid setting."
        except Exception:
            # Do not retry an already committed update after an edit failure.
            logger.warning("Settings callback failed")
            answer = "Could not update the menu. Open /settings to check your settings."
        finally:
            try:
                await self.client.answer_callback_query(callback_id, answer)
            except TelegramAPIError:
                logger.warning("Settings callback acknowledgment failed")
