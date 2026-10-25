import logging

from src.bot.client import TelegramAPIError, TelegramClient
from src.bot.formatter import _truncate
from src.bot.pending_input import PendingInput, PendingInputStore
from src.bot.settings import button
from src.i18n import (
    DEFAULT_LANGUAGE,
    Language,
    LocalizedValidationError,
    display_label,
    t,
    user_language,
    validation_message,
)
from src.models.user_filter import AVAILABLE_SOURCES
from src.repositories.users import UserRepository
from src.schemas.filters import UserFilterDTO
from src.services.collector_policy import COLLECTOR_POLICIES, source_display_name
from src.services.regions import country_label, normalize_country
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
    "keywords": ("keywords", "label.keywords"),
    "reqtech": ("required_technologies", "label.required_technologies"),
    "preftech": ("preferred_technologies", "label.preferred_technologies"),
    "extech": ("excluded_technologies", "label.excluded_technologies"),
    "blacklist_words": ("blacklisted_words", "label.blacklisted_words"),
    "blacklist_companies": ("blacklisted_companies", "label.blacklisted_companies"),
}
TOGGLE_EDITORS = {
    "regions": ("allowed_regions", "label.allowed_regions", REGIONS),
    "employment": ("employment_types", "label.employment_types", EMPLOYMENT_TYPES),
    "experience": ("experience_levels", "label.experience_levels", EXPERIENCE_LEVELS),
    "sources": (
        "sources",
        "label.sources",
        AVAILABLE_SOURCES,
    ),
}
ROOT_ITEMS = tuple(
    (f"filters.button_{key}", key)
    for key in (
        "keywords",
        "reqtech",
        "preftech",
        "extech",
        "regions",
        "employment",
        "experience",
        "salary",
        "sources",
        "blacklist",
        "tz_tol",
        "reset",
    )
)


def label(value: str, language: Language = DEFAULT_LANGUAGE) -> str:
    if value in COLLECTOR_POLICIES:
        return source_display_name(value)
    return (
        display_label(country_label(value), language)
        if normalize_country(value)
        else display_label(value, language)
    )


def keyboard(rows: list[list[dict]]) -> dict:
    return {"inline_keyboard": rows}


def back(screen: str = "back", language: Language = DEFAULT_LANGUAGE) -> list[dict]:
    return [button(t("common.back", language), f"filters:{screen}")]


def list_text(values: list[str], empty: str) -> str:
    return _truncate("\n".join(values) or empty, 240)


def salary_text(filters: UserFilterDTO, language: Language = DEFAULT_LANGUAGE) -> str:
    amount = (
        str(filters.min_salary)
        if filters.min_salary is not None
        else t("filters.any_amount", language)
    )
    return f"{filters.currency or t('filters.any_currency', language)} {amount}"


def format_filters(
    filters: UserFilterDTO, language: Language = DEFAULT_LANGUAGE
) -> str:
    sections = [t("filters.title", language)]
    for field, title in LIST_EDITORS.values():
        values = list_text(getattr(filters, field), t("common.none", language))
        sections.append(f"{t(title, language)}:\n{values}")
    for field in (
        "allowed_regions",
        "employment_types",
        "experience_levels",
        "sources",
    ):
        empty = t("common.any", language)
        values = list_text(
            [label(value, language) for value in getattr(filters, field)], empty
        )
        sections.append(f"{t('label.' + field, language)}:\n{values}")
    for field in ("remote_only", "exclude_us_only"):
        value = getattr(filters, field)
        answer = t("common.yes" if value else "common.no", language)
        sections.append(
            f"{t('label.' + field, language)}: {'✅' if value else '❌'} {answer}"
        )
    sections.extend(
        [
            t("filters.minimum_salary", language)
            + ":\n"
            + salary_text(filters, language),
            t("filters.tolerance", language, hours=filters.timezone_tolerance_hours),
        ]
    )
    return "\n\n".join(sections)


def render_screen(
    filters: UserFilterDTO, screen: str = "back", language: Language = DEFAULT_LANGUAGE
) -> tuple[str, dict]:
    if screen == "back":
        return format_filters(filters, language), keyboard(
            [
                [button(t(title, language), f"filters:{key}")]
                for title, key in ROOT_ITEMS
            ]
        )
    if screen in LIST_EDITORS:
        field, title = LIST_EDITORS[screen]
        values = _truncate(
            "\n".join(getattr(filters, field)) or t("common.none", language), 3000
        )
        return f"{t(title, language)}:\n\n{values}", keyboard(
            [
                [
                    button(
                        t("common." + action, language), f"filters:{screen}:{action}"
                    )
                    for action in ("add", "remove", "clear")
                ],
                back(
                    "blacklist" if screen.startswith("blacklist_") else "back", language
                ),
            ]
        )
    if screen == "countries":
        selected = [
            country_label(value)
            for value in filters.allowed_regions
            if normalize_country(value)
        ]
        return t("filters.countries", language) + ":\n\n" + list_text(
            selected, t("common.none", language)
        ), keyboard(
            [
                [
                    button(
                        t("common." + action, language), f"filters:countries:{action}"
                    )
                    for action in ("add", "remove", "clear")
                ],
                back("regions", language),
            ]
        )
    if screen in TOGGLE_EDITORS:
        field, title, values = TOGGLE_EDITORS[screen]
        key = (
            "filters.regions_help"
            if screen == "regions"
            else (
                "filters.source_minimum"
                if screen == "sources"
                else "filters.any_selections"
            )
        )
        text = f"{t(title, language)}\n\n{t(key, language)}"
        chosen = getattr(filters, field)
        rows = [
            [
                button(
                    f"{'✅' if value in chosen else '❌'} {label(value, language)}",
                    f"filters:{screen}:{value}",
                )
            ]
            for value in values
        ]
        if screen == "regions":
            rows.append([button(t("filters.countries", language), "filters:countries")])
            selected = [
                country_label(value) for value in chosen if normalize_country(value)
            ]
            text += (
                "\n\n" + t("filters.countries", language) + ": " + ", ".join(selected)
            )
            rows.extend(
                [
                    [
                        button(
                            f"{'✅' if getattr(filters, field) else '❌'} "
                            + t("label." + field, language),
                            f"filters:{field}",
                        )
                    ]
                    for field in ("remote_only", "exclude_us_only")
                ]
            )
        return text, keyboard([*rows, back(language=language)])
    if screen == "salary":
        return t(
            "filters.salary_screen", language, salary=salary_text(filters, language)
        ), keyboard(
            [
                [button(t("filters.set_amount", language), "filters:min_salary")],
                [button(t("filters.currency", language), "filters:currency")],
                [button(t("common.clear", language), "filters:salary:clear")],
                back(language=language),
            ]
        )
    if screen == "currency":
        return t("filters.choose_currency", language), keyboard(
            [
                *[
                    [
                        button(
                            value if value != "Any" else t("common.any", language),
                            f"filters:currency:{value}",
                        )
                    ]
                    for value in (*CURRENCIES, "Any")
                ],
                [button(t("common.other", language), "filters:currency:Other")],
                back("salary", language),
            ]
        )
    if screen == "blacklist":
        return t("filters.blacklist_title", language), keyboard(
            [
                [button(t("filters.words", language), "filters:blacklist_words")],
                [
                    button(
                        t("filters.companies", language), "filters:blacklist_companies"
                    )
                ],
                back(language=language),
            ]
        )
    if screen == "tz_tol":
        return t(
            "filters.tolerance", language, hours=filters.timezone_tolerance_hours
        ) + "\n\n" + t("filters.timezone_hint", language), keyboard(
            [
                *[
                    [button(f"±{hours}h", f"filters:tz_tol:{hours}")]
                    for hours in range(5)
                ],
                back(language=language),
            ]
        )
    if screen == "reset":
        return t("filters.reset_confirm", language), keyboard(
            [
                [button(t("filters.reset_yes", language), "filters:reset:confirm")],
                [button(t("common.cancel", language), "filters:back")],
            ]
        )
    raise LocalizedValidationError("error.filter_screen")


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

    async def show(
        self, user_id: int, chat_id: int, language: Language = DEFAULT_LANGUAGE
    ) -> None:
        await self.pending.clear(chat_id)
        try:
            try:
                text, markup = render_screen(
                    await self.service.get_filters(user_id), language=language
                )
            except FiltersUnavailable:
                await self.client.send_message(
                    chat_id, t("filters.unavailable", language)
                )
            else:
                await self.client.send_message(chat_id, text, markup)
        except TelegramAPIError:
            logger.warning("Filters reply failed")

    async def cancel(self, chat_id: int, language: Language = DEFAULT_LANGUAGE) -> None:
        await self.pending.clear(chat_id)
        try:
            await self.client.send_message(chat_id, t("input.cancelled", language))
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
        return (
            (user.id, sender_id, user_language(user))
            if user is not None and user.is_active
            else None
        )

    async def _prompt(
        self,
        chat_id: int,
        message_id: int,
        screen: str,
        operation: str,
        language: Language,
    ):
        await self.pending.set(
            chat_id, PendingInput(f"filters:{screen}", message_id, operation)
        )
        if screen == "min_salary":
            text, target = t("input.salary", language), "salary"
        elif screen == "custom_currency":
            text, target = t("input.currency", language), "currency"
        elif screen == "countries":
            text, target = t("input.countries", language), "countries"
        else:
            noun = (
                "tech"
                if screen in {"reqtech", "preftech", "extech"}
                else (
                    "words"
                    if screen == "blacklist_words"
                    else "companies" if screen == "blacklist_companies" else "keywords"
                )
            )
            text, target = t(f"input.{operation}_{noun}", language), screen
            if screen == "keywords":
                text += t("input.keywords_example", language)
            elif screen in {"reqtech", "preftech", "extech"}:
                text += t("input.skills_example", language)
        return text + t("input.expiry", language), keyboard([back(target, language)])

    async def handle(self, callback: dict) -> None:
        if (
            not isinstance(callback, dict)
            or not isinstance(callback.get("id"), str)
            or not callback["id"]
        ):
            return
        language = DEFAULT_LANGUAGE
        answer = t("filters.not_available", language)
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
            user_id, chat_id, language = identity
            answer = t("filters.not_available", language)
            screen, value = parts[1], parts[2] if len(parts) == 3 else None
            await self.pending.clear(chat_id)
            filters = await self.service.get_filters(user_id)
            if (screen in LIST_EDITORS or screen == "countries") and value in {
                "add",
                "remove",
            }:
                text, markup = await self._prompt(
                    chat_id, message_id, screen, value, language
                )
            elif screen == "min_salary" and value is None:
                text, markup = await self._prompt(
                    chat_id, message_id, screen, "add", language
                )
            elif screen == "currency" and value == "Other":
                text, markup = await self._prompt(
                    chat_id, message_id, "custom_currency", "add", language
                )
            else:
                updated = False
                if screen in LIST_EDITORS and value == "clear":
                    filters = await self.service.update_list(
                        user_id, LIST_EDITORS[screen][0], "clear"
                    )
                    updated = True
                elif screen == "countries" and value == "clear":
                    filters = await self.service.update_countries(user_id, "clear")
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
                    raise LocalizedValidationError("error.filter_option")
                text, markup = render_screen(filters, screen, language)
                if updated:
                    text = t("filters.updated", language) + "\n\n" + text
            await self.client.edit_message_text(chat_id, message_id, text, markup)
            answer = None
        except FiltersUnavailable:
            answer = t("filters.unavailable", language)
        except ValueError as exc:
            answer = validation_message(exc, language)
        except Exception:
            logger.warning("Filters callback failed")
            answer = t("filters.edit_failed", language)
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
        user_id, chat_id, language = identity
        state = await self.pending.get(chat_id)
        if state is None or not state.action.startswith("filters:"):
            return
        screen = state.action.split(":")[1]
        try:
            if screen == "min_salary":
                filters = await self.service.update_min_salary(user_id, text)
                screen = "salary"
            elif screen == "custom_currency":
                filters = await self.service.update_currency(user_id, text)
                screen = "salary"
            elif screen == "countries":
                filters = await self.service.update_countries(
                    user_id, state.operation, text
                )
            else:
                filters = await self.service.update_list(
                    user_id, LIST_EDITORS[screen][0], state.operation, text
                )
        except ValueError as exc:
            try:
                await self.client.edit_message_text(
                    chat_id,
                    state.message_id,
                    t("input.retry", language, error=validation_message(exc, language)),
                    keyboard(
                        [
                            back(
                                {
                                    "min_salary": "salary",
                                    "custom_currency": "currency",
                                }.get(screen, screen),
                                language,
                            )
                        ]
                    ),
                )
            except TelegramAPIError:
                logger.warning("Filter validation reply failed")
            return
        except FiltersUnavailable:
            await self.pending.clear(chat_id)
            return
        await self.pending.clear(chat_id)
        body, markup = render_screen(filters, screen, language)
        try:
            await self.client.edit_message_text(
                chat_id,
                state.message_id,
                t("filters.updated", language) + "\n\n" + body,
                markup,
            )
        except TelegramAPIError:
            # The update is committed; a lost edit must not replay Remove/Add.
            logger.warning("Filter input menu edit failed")
