from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.scheduling import UserNotificationSettingsORM
from src.models.user import UserORM
from src.models.user_filter import DEFAULT_REGIONS, DEFAULT_SOURCES, UserFilterORM
from src.repositories.user_filters import UserFilterRepository
from src.schemas.job import JobDTO
from src.services.filters import FilterService
from src.services.user_filters import (
    LIST_FIELDS,
    TEXT_LISTS,
    TOGGLE_LISTS,
    FiltersUnavailable,
    UserFilterService,
    filter_defaults,
    filters_to_dto,
    normalize_list,
)


@pytest.fixture
def service():
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = UserORM(id=7, telegram_id=123, is_active=True)
    service = UserFilterService(session, owner_telegram_id=None)
    service.repository = AsyncMock(spec=UserFilterRepository)
    service.repository.get_by_user_id.return_value = UserFilterORM(
        user_id=7, **filter_defaults()
    )
    service.repository.add.side_effect = lambda row: row
    service.preferences.get_by_user_id = AsyncMock(
        return_value=UserNotificationSettingsORM(timezone="UTC")
    )
    return service


async def test_new_user_defaults_and_commit(service):
    service.repository.get_by_user_id.return_value = None
    filters = await service.get_or_create_filters(7)
    assert filters.required_technologies == filters.preferred_technologies == []
    assert filters.excluded_technologies == filters.keywords == []
    assert filters.allowed_regions == list(DEFAULT_REGIONS)
    assert filters.sources == list(DEFAULT_SOURCES)
    assert filters.remote_only and filters.exclude_us_only
    assert filters.timezone_tolerance_hours == 2
    assert filters.currency is filters.min_salary is None
    assert filters.timezone == "UTC"
    service.repository.add.assert_awaited_once()
    service.session.commit.assert_awaited_once()


async def test_owner_bootstrap_preserves_legacy_only_when_missing(service):
    service.owner_telegram_id = 123
    service.repository.get_by_user_id.return_value = None
    filters = await service.get_filters(7)
    assert filters.required_technologies == ["python"]
    assert filters.preferred_technologies == [
        "fastapi",
        "postgresql",
        "redis",
        "celery",
        "docker",
    ]
    saved = UserFilterORM(user_id=7, **filter_defaults())
    saved.required_technologies = ["javascript"]
    service.repository.get_by_user_id.return_value = saved
    assert (await service.get_filters(7)).required_technologies == ["javascript"]
    assert service.repository.add.await_count == 1


@pytest.mark.parametrize(
    "user", [None, UserORM(id=7, telegram_id=123, is_active=False)]
)
async def test_missing_or_inactive_user_does_not_create(service, user):
    service.session.scalar.return_value = user
    with pytest.raises(FiltersUnavailable):
        await service.get_filters(7)
    service.repository.add.assert_not_awaited()
    service.session.rollback.assert_awaited_once()


async def test_commit_failure_rolls_back(service):
    service.session.commit.side_effect = RuntimeError("database unavailable")
    with pytest.raises(RuntimeError):
        await service.update_list(7, "keywords", "add", "python")
    service.session.rollback.assert_awaited_once()


@pytest.mark.parametrize("field", sorted(TEXT_LISTS))
async def test_all_text_lists_add_remove_clear(service, field):
    filters = await service.update_list(
        7, field, "add", " Python, redis, python, , REDIS "
    )
    assert getattr(filters, field) == ["python", "redis"]
    filters = await service.update_list(7, field, "remove", "PYTHON")
    assert getattr(filters, field) == ["redis"]
    assert getattr(await service.update_list(7, field, "clear"), field) == []


async def test_technology_aliases_dedupe_and_preserve_order(service):
    filters = await service.update_list(
        7,
        "preferred_technologies",
        "add",
        "Postgres, Postgre SQL, Fast API, fastapi, JS, node.js, C++, C#",
    )
    assert filters.preferred_technologies == [
        "postgresql",
        "fastapi",
        "javascript",
        "nodejs",
        "c++",
        "c#",
    ]
    filters = await service.update_list(
        7, "preferred_technologies", "remove", "postgres, js"
    )
    assert filters.preferred_technologies == ["fastapi", "nodejs", "c++", "c#"]


async def test_excluding_removes_required_and_preferred(service):
    await service.update_list(7, "required_technologies", "add", "python, postgres")
    await service.update_list(7, "preferred_technologies", "add", "python, redis")
    result = await service.update_list(7, "excluded_technologies", "add", "PYTHON")
    assert result.required_technologies == ["postgresql"]
    assert result.preferred_technologies == ["redis"]
    assert result.excluded_technologies == ["python"]
    for field in ("required_technologies", "preferred_technologies"):
        with pytest.raises(ValueError, match="excluded"):
            await service.update_list(7, field, "add", "python")


@pytest.mark.parametrize(
    "field,value",
    [(field, value) for field, values in TOGGLE_LISTS.items() for value in values],
)
async def test_toggle_lists(service, field, value):
    before = getattr(await service.get_filters(7), field)
    after = getattr(await service.toggle(7, field, value), field)
    assert (value in after) != (value in before)
    assert getattr(await service.toggle(7, field, value), field) == before


@pytest.mark.parametrize("field", ["remote_only", "exclude_us_only"])
async def test_toggle_booleans(service, field):
    assert getattr(await service.toggle(7, field), field) is False
    assert getattr(await service.toggle(7, field), field) is True


async def test_cannot_disable_last_source(service):
    await service.toggle(7, "sources", "remoteok")
    await service.toggle(7, "sources", "getonboard")
    await service.toggle(7, "sources", "himalayas")
    await service.toggle(7, "sources", "jobicy")
    await service.toggle(7, "sources", "the_muse")
    await service.toggle(7, "sources", "hacker_news")
    await service.toggle(7, "sources", "jooble")
    with pytest.raises(ValueError, match="At least one source must be enabled"):
        await service.toggle(7, "sources", "weworkremotely")
    assert (await service.get_filters(7)).sources == ["weworkremotely"]


@pytest.mark.parametrize(
    "amount,expected",
    [
        ("2500", 2500),
        ("0", 0),
        (" 2500 ", 2500),
        ("2147483647", 2147483647),
        (None, None),
    ],
)
async def test_salary(service, amount, expected):
    assert (await service.update_min_salary(7, amount)).min_salary == expected


@pytest.mark.parametrize(
    "amount",
    [
        "$2500",
        "2500 USD",
        "2.5k",
        "-1",
        "1.0",
        "",
        "NaN",
        "2147483648",
        "９",
        2500,
        True,
    ],
)
async def test_invalid_salary_does_not_write(service, amount):
    with pytest.raises(ValueError):
        await service.update_min_salary(7, amount)
    service.session.commit.assert_not_awaited()


@pytest.mark.parametrize("currency", ["USD", "EUR", "UYU", None])
async def test_currency(service, currency):
    assert (await service.update_currency(7, currency)).currency == currency


@pytest.mark.parametrize("hours", [-1, 5, True, 2.5, "2"])
async def test_invalid_tolerance(service, hours):
    with pytest.raises(ValueError):
        await service.update_timezone_tolerance(7, hours)
    service.session.commit.assert_not_awaited()


@pytest.mark.parametrize("hours", range(5))
async def test_tolerance(service, hours):
    assert (
        await service.update_timezone_tolerance(7, hours)
    ).timezone_tolerance_hours == hours


async def test_reset_restores_generic_defaults_without_notification_changes(service):
    await service.update_list(7, "required_technologies", "add", "python")
    await service.update_min_salary(7, "2500")
    await service.toggle(7, "remote_only")
    filters = await service.reset(7)
    for field, expected in filter_defaults().items():
        assert getattr(filters, field) == expected
    assert filters.timezone == "UTC"
    assert service.preferences.get_by_user_id.return_value.timezone == "UTC"


async def test_timezone_read_fresh_and_not_duplicated_in_filter_table(service):
    assert (await service.get_filters(7)).timezone == "UTC"
    service.preferences.get_by_user_id.return_value.timezone = "Europe/Madrid"
    assert (await service.get_filters(7)).timezone == "Europe/Madrid"
    assert "timezone" not in UserFilterORM.__table__.columns


def test_mapping_disabled_region_flags_do_not_reenable_regions():
    row = UserFilterORM(user_id=7, **filter_defaults())
    row.allowed_regions = ["europe"]
    filters = filters_to_dto(row, "UTC")
    assert not any(
        (
            filters.worldwide_allowed,
            filters.latam_allowed,
            filters.south_america_allowed,
            filters.uruguay_allowed,
        )
    )
    job = JobDTO(
        source="remoteok",
        external_id="1",
        title="Developer",
        url="https://example.com/job",
        remote=True,
        remote_regions=["worldwide"],
    )
    assert not FilterService().evaluate(job, filters).accepted
    row.allowed_regions = []
    assert not FilterService().evaluate(job, filters_to_dto(row, "UTC")).accepted


@pytest.mark.parametrize(
    "field,action,text",
    [
        ("timezone", "add", "UTC"),
        ("sources", "clear", ""),
        ("keywords", "set", "python"),
        ("keywords", "add", " , "),
        ("keywords", "add", "x" * 101),
        ("keywords", "add", ",".join(str(i) for i in range(51))),
    ],
)
async def test_invalid_list_changes(service, field, action, text):
    with pytest.raises(ValueError):
        await service.update_list(7, field, action, text)
    service.session.commit.assert_not_awaited()


@pytest.mark.parametrize(
    "field,value",
    [
        ("timezone", "UTC"),
        ("sources", "linkedin"),
        ("allowed_regions", "us_only"),
        ("remote_only", "false"),
    ],
)
async def test_invalid_toggles(service, field, value):
    with pytest.raises(ValueError):
        await service.toggle(7, field, value)


def test_company_normalization_is_exact_case_insensitive():
    assert normalize_list("blacklisted_companies", " Acme Inc, ACME INC,Acme ") == [
        "acme inc",
        "acme",
    ]


def test_defaults_are_not_shared_mutable_lists():
    first, second = filter_defaults(), filter_defaults()
    for field in LIST_FIELDS:
        first[field].append("test")
        assert "test" not in second[field]
