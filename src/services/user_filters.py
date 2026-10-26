import re
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.i18n import LocalizedValidationError
from src.models.user import UserORM
from src.models.user_filter import (
    AVAILABLE_SOURCES,
    DEFAULT_REGIONS,
    DEFAULT_SOURCES,
    UserFilterORM,
)
from src.repositories.notification_settings import NotificationSettingsRepository
from src.repositories.user_filters import UserFilterRepository
from src.schemas.filters import UserFilterDTO
from src.services.regions import normalize_country
from src.services.tokens import normalize_technology

REGIONS = (
    "worldwide",
    "americas",
    "north_america",
    "latam",
    "south_america",
    "europe",
    "eu",
    "emea",
    "apac",
    "asia",
    "africa",
    "oceania",
)
EMPLOYMENT_TYPES = ("full_time", "part_time", "contract", "freelance", "internship")
EXPERIENCE_LEVELS = ("junior", "middle", "senior", "lead", "staff", "principal")
CURRENCIES = ("USD", "EUR", "GBP", "CAD", "AUD", "BRL", "MXN", "UYU")
TEXT_LISTS = {
    "keywords",
    "required_technologies",
    "preferred_technologies",
    "excluded_technologies",
    "blacklisted_words",
    "blacklisted_companies",
}
TOGGLE_LISTS = {
    "allowed_regions": REGIONS,
    "employment_types": EMPLOYMENT_TYPES,
    "experience_levels": EXPERIENCE_LEVELS,
    "sources": AVAILABLE_SOURCES,
}
LIST_FIELDS = (*sorted(TEXT_LISTS), *TOGGLE_LISTS)


class FiltersUnavailable(Exception):
    pass


def filter_defaults() -> dict:
    return {
        **{field: [] for field in LIST_FIELDS},
        "allowed_regions": list(DEFAULT_REGIONS),
        "sources": list(DEFAULT_SOURCES),
        "remote_only": True,
        "exclude_us_only": False,
        "min_salary": None,
        "currency": None,
        "timezone_tolerance_hours": 2,
    }


def filters_to_dto(row: UserFilterORM, timezone: str) -> UserFilterDTO:
    """Read saved preferences without rewriting them; use notification timezone."""
    values = {field: list(getattr(row, field)) for field in LIST_FIELDS}
    values.update(
        {
            field: getattr(row, field)
            for field in (
                "remote_only",
                "exclude_us_only",
                "min_salary",
                "currency",
                "timezone_tolerance_hours",
            )
        }
    )
    return UserFilterDTO(
        **values,
        timezone=timezone,
    )


def normalize_list(field: str, text: str) -> list[str]:
    if field not in TEXT_LISTS or not isinstance(text, str) or len(text) > 4000:
        raise LocalizedValidationError("error.invalid_list")
    normalize = normalize_technology if field.endswith("technologies") else str.lower
    values = list(
        dict.fromkeys(
            value for item in text.split(",") if (value := normalize(item.strip()))
        )
    )
    if not values:
        raise LocalizedValidationError("error.empty_list")
    if len(values) > 50 or any(len(value) > 100 for value in values):
        raise LocalizedValidationError("error.list_size")
    return values


class UserFilterService:
    """Own filter transactions, using a session without unrelated pending writes.

    Lock the parent user before bootstrap/read-modify-write so concurrent first
    reads and menu updates cannot create duplicates or lose list changes.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        owner_telegram_id: int | None = settings.TELEGRAM_CHAT_ID,
    ):
        self.session = session
        self.repository = UserFilterRepository(session)
        self.preferences = NotificationSettingsRepository(session)
        self.owner_telegram_id = owner_telegram_id

    async def _run(self, user_id: int, change: Callable | None = None) -> UserFilterDTO:
        try:
            user = await self.session.scalar(
                select(UserORM)
                .where(UserORM.id == user_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if user is None or not user.is_active:
                raise FiltersUnavailable
            preferences = await self.preferences.get_by_user_id(user_id)
            row = await self.repository.get_by_user_id(user_id)
            if row is None:
                values = filter_defaults()
                row = await self.repository.add(
                    UserFilterORM(user_id=user_id, **values)
                )
            if change is not None:
                change(row)
            dto = filters_to_dto(
                row,
                preferences.timezone if preferences else settings.SCHEDULER_TIMEZONE,
            )
            await self.session.commit()
            return dto
        except Exception:
            await self.session.rollback()
            raise

    async def get_filters(self, user_id: int) -> UserFilterDTO:
        return await self._run(user_id)

    async def get_or_create_filters(self, user_id: int) -> UserFilterDTO:
        return await self.get_filters(user_id)

    async def update_list(
        self, user_id: int, field: str, action: str, text: str = ""
    ) -> UserFilterDTO:
        if field not in TEXT_LISTS or action not in {"add", "remove", "clear"}:
            raise LocalizedValidationError("error.list_action")
        values = [] if action == "clear" else normalize_list(field, text)

        def change(row):
            canonicalize = (
                normalize_technology if field.endswith("technologies") else str.lower
            )
            current = getattr(row, field)
            if action == "add":
                updated = list(current)
                seen = {canonicalize(item) for item in current}
                for value in values:
                    if value not in seen:
                        updated.append(value)
                        seen.add(value)
            elif action == "remove":
                updated = [item for item in current if canonicalize(item) not in values]
            else:
                updated = []
            if len(updated) > 50:
                raise LocalizedValidationError("error.list_limit")
            if field in {"required_technologies", "preferred_technologies"} and {
                canonicalize(item) for item in updated
            } & {canonicalize(item) for item in row.excluded_technologies}:
                raise LocalizedValidationError("error.tech_conflict")
            setattr(row, field, updated)
            if field == "excluded_technologies":
                excluded = {canonicalize(item) for item in updated}
                for target in ("required_technologies", "preferred_technologies"):
                    setattr(
                        row,
                        target,
                        [
                            item
                            for item in getattr(row, target)
                            if canonicalize(item) not in excluded
                        ],
                    )

        return await self._run(user_id, change)

    async def toggle(
        self, user_id: int, field: str, value: str | None = None
    ) -> UserFilterDTO:
        if field in {"remote_only", "exclude_us_only"} and value is None:
            return await self._run(
                user_id, lambda row: setattr(row, field, not getattr(row, field))
            )
        if field not in TOGGLE_LISTS or value not in TOGGLE_LISTS[field]:
            raise LocalizedValidationError("error.filter_option")

        def change(row):
            current = getattr(row, field)
            if field == "allowed_regions" and value not in current:
                current = (
                    []
                    if value == "worldwide"
                    else [item for item in current if item != "worldwide"]
                )
            updated = (
                [item for item in current if item != value]
                if value in current
                else [*current, value]
            )
            if field == "sources" and not updated:
                raise LocalizedValidationError("filters.source_minimum")
            ordered = [item for item in TOGGLE_LISTS[field] if item in updated]
            extras = [item for item in updated if item not in TOGGLE_LISTS[field]]
            setattr(row, field, [*ordered, *extras])

        return await self._run(user_id, change)

    async def update_min_salary(
        self, user_id: int, amount: str | None
    ) -> UserFilterDTO:
        if amount is not None and (
            not isinstance(amount, str)
            or not re.fullmatch(r"[0-9]{1,10}", amount.strip())
            or int(amount) > 2**31 - 1
        ):
            raise LocalizedValidationError("error.salary")
        return await self._run(
            user_id,
            lambda row: setattr(
                row, "min_salary", int(amount) if amount is not None else None
            ),
        )

    async def update_currency(
        self, user_id: int, currency: str | None
    ) -> UserFilterDTO:
        if currency is not None:
            if not isinstance(currency, str) or not re.fullmatch(
                r"[A-Za-z]{3}", currency.strip()
            ):
                raise LocalizedValidationError("error.currency")
            currency = currency.strip().upper()
        return await self._run(user_id, lambda row: setattr(row, "currency", currency))

    async def update_countries(
        self, user_id: int, action: str, text: str = ""
    ) -> UserFilterDTO:
        if action not in {"add", "remove", "clear"}:
            raise LocalizedValidationError("error.list_action")
        if not isinstance(text, str) or len(text) > 4000:
            raise LocalizedValidationError("error.invalid_list")
        values = (
            []
            if action == "clear"
            else [normalize_country(part.strip()) for part in text.split(",")]
        )
        if action != "clear" and (not values or any(value is None for value in values)):
            raise LocalizedValidationError("error.country")

        def change(row):
            current = row.allowed_regions
            if action == "add":
                updated = [value for value in current if value != "worldwide"]
                seen = {normalize_country(value) or value for value in current}
                for value in values:
                    if value not in seen:
                        updated.append(value)
                        seen.add(value)
            else:
                updated = [
                    value
                    for value in current
                    if not (
                        normalize_country(value)
                        and (action == "clear" or normalize_country(value) in values)
                    )
                ]
            if len(updated) > 50:
                raise LocalizedValidationError("error.list_limit")
            row.allowed_regions = updated

        return await self._run(user_id, change)

    async def update_timezone_tolerance(
        self, user_id: int, hours: int
    ) -> UserFilterDTO:
        if type(hours) is not int or not 0 <= hours <= 4:
            raise LocalizedValidationError("error.tolerance")
        return await self._run(
            user_id, lambda row: setattr(row, "timezone_tolerance_hours", hours)
        )

    async def reset(self, user_id: int) -> UserFilterDTO:
        def change(row):
            for field, value in filter_defaults().items():
                setattr(row, field, value)

        return await self._run(user_id, change)
