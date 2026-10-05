import logging

from src.bot.client import TelegramAPIError, TelegramClient
from src.bot.formatter import _truncate
from src.bot.pending_input import PendingInput, PendingInputStore
from src.bot.settings import button
from src.repositories.users import UserRepository
from src.schemas.filters import UserFilterDTO
from src.services.collector_policy import source_display_name
from src.services.user_filters import (
    CURRENCIES,
    EMPLOYMENT_TYPES,
    EXPERIENCE_LEVELS,
    REGIONS,
    FiltersUnavailable,
    UserFilterService,
)

logger = logging.getLogger(__name__)

LIST_EDITORS = {
    "keywords": ("keywords", "Keywords"),
    "reqtech": ("required_technologies", "Required technologies"),
    "preftech": ("preferred_technologies", "Preferred technologies"),
    "extech": ("excluded_technologies", "Excluded technologies"),
    "blacklist_words": ("blacklisted_words", "Blacklisted words"),
    "blacklist_companies": ("blacklisted_companies", "Blacklisted companies"),
}
TOGGLE_EDITORS = {
    "regions": ("allowed_regions", "Regions", REGIONS),
    "employment": ("employment_types", "Employment", EMPLOYMENT_TYPES),
    "experience": ("experience_levels", "Experience", EXPERIENCE_LEVELS),
    "sources": ("sources", "Sources", ("remoteok", "weworkremotely", "getonboard")),
}
ROOT_ITEMS = (
    ("🔎 Keywords", "keywords"),
    ("🧰 Required tech", "reqtech"),
    ("⭐ Preferred tech", "preftech"),
    ("🚫 Excluded tech", "extech"),
    ("🌎 Regions", "regions"),
    ("💼 Employment", "employment"),
    ("📈 Experience", "experience"),
    ("💰 Salary", "salary"),
    ("📡 Sources", "sources"),
    ("🚫 Blacklist", "blacklist"),
    ("🕐 Timezone tolerance", "tz_tol"),
    ("Reset filters", "reset"),
)


def label(value: str) -> str:
    special = {
        "worldwide": "Worldwide",
        "latam": "LATAM",
        "eu": "EU",
        "emea": "EMEA",
        "apac": "APAC",
        "full_time": "Full-time",
        "part_time": "Part-time",
    }
    if value in {"remoteok", "weworkremotely", "getonboard"}:
        return source_display_name(value)
    return special.get(value, value.replace("_", " ").title())


def keyboard(rows: list[list[dict]]) -> dict:
    return {"inline_keyboard": rows}


def back(screen: str = "back") -> list[dict]:
    return [button("← Back", f"filters:{screen}")]


def list_text(values: list[str], empty: str = "Any") -> str:
    return _truncate("\n".join(values) or empty, 240)


def salary_text(filters: UserFilterDTO) -> str:
    amount = str(filters.min_salary) if filters.min_salary is not None else "Any amount"
    return f"{filters.currency or 'Any currency'} {amount}"


def format_filters(filters: UserFilterDTO) -> str:
    sections = ["🔎 Job filters"]
    for field, title in LIST_EDITORS.values():
        sections.append(f"{title}:\n{list_text(getattr(filters, field), 'None')}")
    sections.extend(
        [
            "Regions:\n"
            + list_text([label(value) for value in filters.allowed_regions], "None"),
            f"Remote only: {'✅ Yes' if filters.remote_only else '❌ No'}",
            f"Exclude US-only: {'✅ Yes' if filters.exclude_us_only else '❌ No'}",
            "Employment:\n"
            + list_text([label(value) for value in filters.employment_types]),
            "Experience:\n"
            + list_text([label(value) for value in filters.experience_levels]),
            f"Minimum salary:\n{salary_text(filters)}",
            f"Sources:\n{list_text([label(value) for value in filters.sources])}",
            f"Timezone tolerance: ±{filters.timezone_tolerance_hours}h",
        ]
    )
    return "\n\n".join(sections)


def render_screen(filters: UserFilterDTO, screen: str = "back") -> tuple[str, dict]:
    if screen == "back":
        return format_filters(filters), keyboard(
            [[button(title, f"filters:{key}")] for title, key in ROOT_ITEMS]
        )
    if screen in LIST_EDITORS:
        field, title = LIST_EDITORS[screen]
        values = _truncate("\n".join(getattr(filters, field)) or "None", 3000)
        text = f"{title}:\n\n{values}"
        return text, keyboard(
            [
                [
                    button(action.title(), f"filters:{screen}:{action}")
                    for action in ("add", "remove", "clear")
                ],
                back("blacklist" if screen.startswith("blacklist_") else "back"),
            ]
        )
    if screen in TOGGLE_EDITORS:
        field, title, values = TOGGLE_EDITORS[screen]
        chosen = getattr(filters, field)
        text = f"{title}\n\n" + (
            "No selections means Any."
            if field != "sources"
            else "At least one source must stay enabled."
        )
        if screen == "regions":
            text = (
                "Regions\n\nSelect allowed regions. With no selections, "
                "jobs with a known region are excluded."
            )
        rows = [
            [
                button(
                    f"{'✅' if value in chosen else '❌'} {label(value)}",
                    f"filters:{screen}:{value}",
                )
            ]
            for value in values
        ]
        if screen == "regions":
            rows.extend(
                [
                    [
                        button(
                            f"{'✅' if getattr(filters, field) else '❌'} {title}",
                            f"filters:{field}",
                        )
                    ]
                    for field, title in (
                        ("remote_only", "Remote only"),
                        ("exclude_us_only", "Exclude US-only"),
                    )
                ]
            )
        return text, keyboard([*rows, back()])
    if screen == "salary":
        return (
            f"Minimum salary\n\nCurrent:\n{salary_text(filters)}\n\n"
            "No currency conversion is applied.",
            keyboard(
                [
                    [button("Set amount", "filters:min_salary")],
                    [button("Currency", "filters:currency")],
                    [button("Clear", "filters:salary:clear")],
                    back(),
                ]
            ),
        )
    if screen == "currency":
        return "Choose a salary currency.", keyboard(
            [
                *[
                    [button(value, f"filters:currency:{value}")]
                    for value in (*CURRENCIES, "Any")
                ],
                back("salary"),
            ]
        )
    if screen == "blacklist":
        return "🚫 Blacklist", keyboard(
            [
                [button("Words", "filters:blacklist_words")],
                [button("Companies", "filters:blacklist_companies")],
                back(),
            ]
        )
    if screen == "tz_tol":
        return (
            f"Timezone tolerance: ±{filters.timezone_tolerance_hours}h\n\n"
            "Timezone is configured in /settings.",
            keyboard(
                [
                    *[
                        [button(f"±{hours}h", f"filters:tz_tol:{hours}")]
                        for hours in range(5)
                    ],
                    back(),
                ]
            ),
        )
    if screen == "reset":
        return "Reset all job filters to defaults?", keyboard(
            [
                [button("Yes, reset", "filters:reset:confirm")],
                [button("Cancel", "filters:back")],
            ]
        )
    raise ValueError("Invalid filter screen.")


class FiltersHandler:
    def __init__(
        self,
        users: UserRepository,
        service: UserFilterService,
        client: TelegramClient,
        pending: PendingInputStore,
    ):
        self.users, self.service, self.client, self.pending = (
            users,
            service,
            client,
            pending,
        )

    async def show(self, user_id: int, chat_id: int) -> None:
        await self.pending.clear(chat_id)
        try:
            try:
                text, markup = render_screen(await self.service.get_filters(user_id))
            except FiltersUnavailable:
                await self.client.send_message(
                    chat_id, "Job filters are not available yet."
                )
            else:
                await self.client.send_message(chat_id, text, markup)
        except TelegramAPIError:
            logger.warning("Filters reply failed")

    async def cancel(self, chat_id: int) -> None:
        await self.pending.clear(chat_id)
        try:
            await self.client.send_message(chat_id, "Input cancelled.")
        except TelegramAPIError:
            logger.warning("Input cancellation reply failed")

    async def _user(self, payload: dict):
        sender, chat = payload.get("from"), payload.get("chat")
        if not isinstance(sender, dict) or not isinstance(chat, dict):
            return None
        sender_id = sender.get("id")
        if (
            type(sender_id) is not int
            or not 0 < sender_id < 2**63
            or sender.get("is_bot") is True
            or chat.get("type") != "private"
            or type(chat.get("id")) is not int
            or chat["id"] != sender_id
        ):
            return None
        user = await self.users.get_by_telegram_id(sender_id)
        return (user.id, sender_id) if user is not None and user.is_active else None

    async def _prompt(self, chat_id: int, message_id: int, screen: str, operation: str):
        state = PendingInput(f"filters:{screen}", message_id, operation)
        await self.pending.set(chat_id, state)
        if screen == "min_salary":
            text = "Send a whole number without currency symbols.\n\nExample:\n2500"
            target = "salary"
        else:
            field, _ = LIST_EDITORS[screen]
            noun = (
                "technologies"
                if field.endswith("technologies")
                else label(field).lower()
            )
            suffix = " to remove" if operation == "remove" else ""
            text = f"Send {noun}{suffix} separated by commas."
            if screen == "keywords":
                text += "\n\nExample:\npython, backend, api"
            target = screen
        return (
            text + "\n\nUse /cancel to cancel. Input expires in 10 minutes.",
            keyboard([back(target)]),
        )

    async def handle(self, callback: dict) -> None:
        if (
            not isinstance(callback, dict)
            or not isinstance(callback.get("id"), str)
            or not callback["id"]
        ):
            return
        answer = "This filter is not available."
        try:
            message = callback.get("message")
            if not isinstance(message, dict):
                return
            identity = await self._user(
                {"from": callback.get("from"), "chat": message.get("chat")}
            )
            message_id, data = message.get("message_id"), callback.get("data")
            if (
                identity is None
                or type(message_id) is not int
                or message_id <= 0
                or not isinstance(data, str)
            ):
                return
            parts = data.split(":")
            if len(parts) not in {2, 3} or parts[0] != "filters":
                return
            user_id, chat_id = identity
            screen, value = parts[1], parts[2] if len(parts) == 3 else None
            await self.pending.clear(chat_id)
            filters = await self.service.get_filters(user_id)
            if screen in LIST_EDITORS and value in {"add", "remove"}:
                text, markup = await self._prompt(chat_id, message_id, screen, value)
            elif screen == "min_salary" and value is None:
                text, markup = await self._prompt(chat_id, message_id, screen, "add")
            else:
                updated = False
                if screen in LIST_EDITORS and value == "clear":
                    filters = await self.service.update_list(
                        user_id, LIST_EDITORS[screen][0], "clear"
                    )
                    updated = True
                elif screen in TOGGLE_EDITORS and value is not None:
                    filters = await self.service.toggle(
                        user_id, TOGGLE_EDITORS[screen][0], value
                    )
                    updated = True
                elif screen in {"remote_only", "exclude_us_only"} and value is None:
                    filters = await self.service.toggle(user_id, screen)
                    screen, updated = "regions", True
                elif screen == "salary" and value == "clear":
                    filters = await self.service.update_min_salary(user_id, None)
                    updated = True
                elif screen == "currency" and value is not None:
                    filters = await self.service.update_currency(
                        user_id, None if value == "Any" else value
                    )
                    screen, updated = "salary", True
                elif screen == "tz_tol" and value in {str(i) for i in range(5)}:
                    filters = await self.service.update_timezone_tolerance(
                        user_id, int(value)
                    )
                    updated = True
                elif screen == "reset" and value == "confirm":
                    filters = await self.service.reset(user_id)
                    screen, updated = "back", True
                elif value is not None:
                    raise ValueError("Invalid filter option.")
                text, markup = render_screen(filters, screen)
                if updated:
                    text = "✅ Job filters updated.\n\n" + text
            await self.client.edit_message_text(chat_id, message_id, text, markup)
            answer = None
        except FiltersUnavailable:
            answer = "Job filters are not available yet."
        except ValueError as exc:
            answer = str(exc)
        except Exception:
            logger.warning("Filters callback failed")
            answer = "Could not update the menu. Open /filters to check your filters."
        finally:
            try:
                await self.client.answer_callback_query(callback["id"], answer)
            except TelegramAPIError:
                logger.warning("Filters callback acknowledgment failed")

    async def handle_input(self, message: dict) -> None:
        text = message.get("text")
        if not isinstance(text, str) or text.startswith("/"):
            return
        identity = await self._user(message)
        if identity is None:
            return
        user_id, chat_id = identity
        state = await self.pending.get(chat_id)
        if state is None:
            return
        screen = state.action.split(":")[1]
        try:
            if screen == "min_salary":
                filters = await self.service.update_min_salary(user_id, text)
                screen = "salary"
            else:
                filters = await self.service.update_list(
                    user_id, LIST_EDITORS[screen][0], state.operation, text
                )
        except ValueError as exc:
            try:
                await self.client.edit_message_text(
                    chat_id,
                    state.message_id,
                    f"{exc}\n\nTry again, or use /cancel.",
                    keyboard([back("salary" if screen == "min_salary" else screen)]),
                )
            except TelegramAPIError:
                logger.warning("Filter validation reply failed")
            return
        except FiltersUnavailable:
            await self.pending.clear(chat_id)
            return
        await self.pending.clear(chat_id)
        body, markup = render_screen(filters, screen)
        try:
            await self.client.edit_message_text(
                chat_id, state.message_id, "✅ Job filters updated.\n\n" + body, markup
            )
        except TelegramAPIError:
            # The update is committed; a lost edit must not replay Remove/Add.
            logger.warning("Filter input menu edit failed")
