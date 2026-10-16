import copy
import gzip
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from src.collectors.base import CollectionError, CollectorConfigurationError
from src.collectors.usajobs import SEARCH_URL, USAJobsCollector, parse_job, parse_page
from src.config import Settings, settings
from src.services.normalization import NormalizationService

NOW = datetime(2026, 10, 16, 12, tzinfo=UTC)


@pytest.fixture
def rows():
    return json.loads(
        (Path(__file__).parents[1] / "fixtures/usajobs/search.json").read_text()
    )["SearchResult"]["SearchResultItems"]


def page(items, total=None):
    return {
        "SearchResult": {
            "SearchResultCount": len(items),
            "SearchResultCountAll": len(items) if total is None else total,
            "SearchResultItems": items,
        }
    }


def test_full_remote_federal_mapping(rows):
    raw = rows[0]
    before = copy.deepcopy(raw)
    job = parse_job(raw, collected_at=NOW)
    assert raw == before
    assert (job.source, job.external_id, job.title, job.company) == (
        "usajobs",
        "800000001",
        "Information Technology Specialist",
        "Example Federal Agency",
    )
    assert job.url == "https://www.usajobs.gov/job/800000001"
    assert "Build reliable public services & tools." in job.description
    assert (
        "You must be a U.S. citizen" in job.description and "<p>" not in job.description
    )
    assert job.remote and job.remote_regions == ["us_only"]
    assert job.location == "Anywhere in the U.S. (remote job)"
    assert job.employment_type == "full_time"
    assert (job.salary_min, job.salary_max, job.currency, job.salary_period) == (
        80000,
        120000,
        "USD",
        "yearly",
    )
    assert job.published_at == datetime(2026, 10, 15, 12, tzinfo=UTC)
    assert job.collected_at == NOW
    assert job.technologies == []
    assert (
        job.experience_level
        is job.timezone_text
        is job.timezone_min_utc_offset
        is job.timezone_max_utc_offset
        is None
    )
    assert NormalizationService().normalize(job).remote_regions == ["us_only"]


def test_eligibility_uses_existing_filters_and_no_source_scoring_bonus(rows):
    from src.schemas.filters import UserFilterDTO
    from src.services.filters import FilterService
    from src.services.scoring import ScoringService

    job = parse_job(rows[0], collected_at=NOW)
    filters = UserFilterDTO(sources=["usajobs"], allowed_regions=["us_only"])
    result = FilterService().evaluate(job, filters)
    assert not result.accepted and "US-only vacancy" in result.reasons
    filters.exclude_us_only = False
    assert FilterService().evaluate(job, filters).accepted
    assert ScoringService().calculate(job, filters) == ScoringService().calculate(
        job.model_copy(update={"source": "remoteok"}), filters
    )


def test_office_hourly_multiple_locations_and_telework_regression(rows):
    office, telework = [parse_job(row, collected_at=NOW) for row in rows[1:3]]
    assert not office.remote and office.remote_regions == []
    assert office.location == "Washington, DC; New York, NY"
    assert office.employment_type == "part_time"
    assert (
        office.salary_min,
        office.salary_max,
        office.currency,
        office.salary_period,
    ) == (40, 60, "USD", "hourly")
    assert not telework.remote and telework.remote_regions == []
    assert telework.employment_type is None
    assert "Telework eligible: Yes" in telework.description


def test_missing_optionals_and_closed_fixture(rows):
    assert parse_job(rows[3], collected_at=NOW) is None
    job = parse_job(rows[4], collected_at=NOW)
    assert not job.remote and job.remote_regions == [] and job.technologies == []
    for field in (
        "company",
        "description",
        "location",
        "employment_type",
        "salary_min",
        "salary_max",
        "currency",
        "salary_period",
        "published_at",
        "experience_level",
        "timezone_text",
        "timezone_min_utc_offset",
        "timezone_max_utc_offset",
    ):
        assert getattr(job, field) is None


@pytest.mark.parametrize(
    "flag,expected",
    [
        (True, True),
        ("True", True),
        ("Yes", True),
        (False, False),
        ("No", False),
        (None, False),
        ("ambiguous", False),
    ],
)
def test_remote_never_inferred_from_title_summary_telework_or_city(
    rows, flag, expected
):
    raw = rows[2]
    d = raw["MatchedObjectDescriptor"]
    d["PositionTitle"] = "Remote Senior Python Engineer"
    d["UserArea"]["Details"].update(
        RemoteIndicator=flag, JobSummary="Worldwide remote Python UTC-3"
    )
    job = parse_job(raw, collected_at=NOW)
    assert job.remote is expected and job.remote_regions == []
    assert job.technologies == [] and job.experience_level is job.timezone_text is None


@pytest.mark.parametrize(
    "location",
    [
        "Anywhere in the U.S. (remote job)",
        "Anywhere in the U.S. (remote job), United States",
    ],
)
def test_official_remote_location_confirms_remote_and_us_geography_without_flag(
    rows, location
):
    d = rows[0]["MatchedObjectDescriptor"]
    d["PositionLocation"][0]["LocationName"] = location
    d["PositionLocationDisplay"] = location
    d["UserArea"] = {}
    job = parse_job(rows[0], collected_at=NOW)
    assert job.remote and job.remote_regions == ["us_only"]
    d.pop("PositionLocation")
    assert parse_job(rows[0], collected_at=NOW).remote


def test_live_us_location_still_excluded_when_user_opts_in(rows):
    from src.schemas.filters import UserFilterDTO
    from src.services.filters import FilterService

    raw = rows[0]
    d = raw["MatchedObjectDescriptor"]
    d["PositionLocation"] = [
        {"LocationName": "Anywhere in the U.S. (remote job), United States"}
    ]
    d["UserArea"]["Details"].update(WhoMayApply={}, KeyRequirements=[])
    job = parse_job(raw, collected_at=NOW)
    assert job.remote and job.remote_regions == ["us_only"]
    result = FilterService().evaluate(job, UserFilterDTO(sources=["usajobs"]))
    assert not result.accepted and "US-only vacancy" in result.reasons


@pytest.mark.parametrize(
    "statement,expected",
    [
        ("U.S. citizens only", True),
        ("You must be a U.S. citizen to apply for this job.", True),
        ("United States citizens only", True),
        ("U.S. citizenship is required.", True),
        ("U.S. citizens and nationals", False),
        ("Non-citizens may apply", False),
        ("U.S. citizenship is not required", False),
        ("U.S. citizens only, except where authorized", False),
        ("Open to the public", False),
        ("", False),
    ],
)
def test_only_explicit_unconditional_citizenship_is_us_only(rows, statement, expected):
    raw = rows[2]
    details = raw["MatchedObjectDescriptor"]["UserArea"]["Details"]
    details.update(
        WhoMayApply={"Name": statement}, HiringPath=["public"], LowGrade="14"
    )
    job = parse_job(raw, collected_at=NOW)
    assert job.remote_regions == (["us_only"] if expected else [])


@pytest.mark.parametrize(
    "close,now,closed",
    [
        ("2026-10-16", "2026-10-17T03:59:59Z", False),
        ("2026-10-16T00:00:00", "2026-10-17T04:00:00Z", True),
        ("2026-12-16", "2026-12-17T04:59:59Z", False),
        ("2026-12-16", "2026-12-17T05:00:00Z", True),
        ("2026-10-16T11:00:00Z", "2026-10-16T12:00:00Z", True),
        ("2026-10-16T12:00:00Z", "2026-10-16T12:00:00Z", False),
        ("2026-10-15T11:30:00", "2026-10-16T12:00:00Z", False),
        ("bad", "2026-10-16T12:00:00Z", False),
        (None, "2026-10-16T12:00:00Z", False),
    ],
)
def test_closing_date_et_end_of_day_and_aware_instants(rows, close, now, closed):
    rows[0]["MatchedObjectDescriptor"]["ApplicationCloseDate"] = close
    assert (
        parse_job(rows[0], collected_at=datetime.fromisoformat(now)) is None
    ) is closed


@pytest.mark.parametrize(
    "date,expected",
    [
        ("2026-10-16T12:00:00-04:00", datetime(2026, 10, 16, 16, tzinfo=UTC)),
        ("2026-10-16T12:00:00Z", NOW),
        ("2026-10-16T12:00:00", None),
        ("2026-10-16", None),
        ("bad", None),
        (None, None),
    ],
)
def test_publication_never_uses_server_timezone(rows, date, expected):
    rows[0]["MatchedObjectDescriptor"]["PublicationStartDate"] = date
    assert parse_job(rows[0], collected_at=NOW).published_at == expected


@pytest.mark.parametrize(
    "low,high,code,expected",
    [
        ("80000", "120000", "PA", (80000, 120000, "USD", "yearly")),
        ("40.00", "60.00", "PH", (40, 60, "USD", "hourly")),
        ("1000", "2000", "PM", (1000, 2000, "USD", None)),
        ("40.50", "60.50", "PH", (None, None, None, None)),
        ("NaN", "100", "PA", (None, None, None, None)),
        ("Infinity", "Infinity", "PA", (None, None, None, None)),
        ("120000", "80000", "PA", (None, None, None, None)),
        ("-1", "1", "PA", (None, None, None, None)),
        ("0", "2147483648", "PA", (None, None, None, None)),
        (True, 100, "PA", (None, None, None, None)),
        (None, "100", "PA", (None, None, None, None)),
    ],
)
def test_salary_no_rounding_conversion_or_period_guess(rows, low, high, code, expected):
    rows[0]["MatchedObjectDescriptor"]["PositionRemuneration"] = [
        {"MinimumRange": low, "MaximumRange": high, "RateIntervalCode": code}
    ]
    job = parse_job(rows[0], collected_at=NOW)
    assert (job.salary_min, job.salary_max, job.currency, job.salary_period) == expected


def test_many_locations_capped_salary_multiple_ranges_and_missing_agency(rows):
    raw = rows[0]
    d = raw["MatchedObjectDescriptor"]
    d["PositionLocation"] = [{"LocationName": f"City {n}"} for n in range(12)]
    d["PositionLocationDisplay"] = "United States"
    d["PositionRemuneration"] *= 2
    d.pop("OrganizationName")
    assert parse_job(raw, collected_at=NOW).company == "Example Department"
    d.pop("DepartmentName")
    job = parse_job(raw, collected_at=NOW)
    assert job.location == "City 0; City 1; City 2; City 3; City 4; +7 more"
    assert job.company is job.salary_min is None


@pytest.mark.parametrize("identity", [None, True, False, 1.2, "slug", {}, []])
def test_invalid_identity_never_falls_back_to_announcement_hash_or_uuid(rows, identity):
    rows[0]["MatchedObjectId"] = identity
    with pytest.raises(ValueError, match="control number"):
        parse_job(rows[0])


@pytest.mark.parametrize(
    "url",
    [
        None,
        "https://data.usajobs.gov/api/Search",
        "https://evil.example/job/1",
        "http://www.usajobs.gov/job/1",
        "https://user:pass@www.usajobs.gov/job/1",
    ],
)
def test_only_official_position_url(rows, url):
    rows[0]["MatchedObjectDescriptor"]["PositionURI"] = url
    with pytest.raises(ValueError):
        parse_job(rows[0])


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"SearchResult": {}},
        {"SearchResult": {"SearchResultItems": {}}},
        {
            "SearchResult": {
                "SearchResultItems": [],
                "SearchResultCount": 0,
                "SearchResultCountAll": -1,
            }
        },
        {
            "SearchResult": {
                "SearchResultItems": [],
                "SearchResultCount": True,
                "SearchResultCountAll": 0,
            }
        },
    ],
)
def test_unexpected_schema_is_failure(payload):
    with pytest.raises(CollectionError):
        parse_page(payload)


def test_page_closed_and_invalid_counts_empty_is_success(rows):
    jobs, total, audit = parse_page(page([*rows, {}]), collected_at=NOW)
    assert len(jobs) == 4 and total == 6
    assert audit == {"received": 6, "closed": 1, "invalid": 1, "telework_only": 1}
    assert parse_page(page([]), collected_at=NOW)[0] == []
    assert parse_page(page([rows[3]]), collected_at=NOW)[1] == 1
    with pytest.raises(CollectionError, match="no valid"):
        parse_page(page([{}]))


@pytest.fixture
def transport(monkeypatch):
    monkeypatch.setattr(settings, "USAJOBS_API_KEY", "usa-private-test-key")
    monkeypatch.setattr(settings, "USAJOBS_EMAIL", "private-test@example.com")
    real = httpx.AsyncClient

    def configure(handler):
        monkeypatch.setattr(
            "src.collectors.usajobs.httpx.AsyncClient",
            lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs),
        )

    return configure


@pytest.mark.parametrize("missing", ["USAJOBS_API_KEY", "USAJOBS_EMAIL"])
async def test_missing_credentials_fail_before_http(monkeypatch, missing):
    monkeypatch.setattr(settings, "USAJOBS_API_KEY", "test-private-key")
    monkeypatch.setattr(settings, "USAJOBS_EMAIL", "test@example.com")
    monkeypatch.setattr(settings, missing, None)
    client = Mock()
    monkeypatch.setattr("src.collectors.usajobs.httpx.AsyncClient", client)
    with pytest.raises(CollectorConfigurationError, match=missing):
        await USAJobsCollector().collect()
    client.assert_not_called()


async def test_headers_official_filters_bounded_request_and_secret_logs(
    rows, transport, caplog
):
    def handler(request):
        assert str(request.url).split("?")[0] == SEARCH_URL and request.method == "GET"
        assert request.headers["Host"] == "data.usajobs.gov"
        assert request.headers["User-Agent"] == "private-test@example.com"
        assert request.headers["Authorization-Key"] == "usa-private-test-key"
        assert dict(request.url.params) == {
            "JobCategoryCode": "2210",
            "RemoteIndicator": "True",
            "DatePosted": "30",
            "SortField": "opendate",
            "SortDirection": "Desc",
            "ResultsPerPage": "50",
            "Page": "1",
            "Fields": "Full",
        }
        logging.getLogger("httpcore.http11").debug(
            "headers=%s", list(request.headers.raw)
        )
        return httpx.Response(200, json=page([rows[0]]))

    transport(handler)
    with caplog.at_level(logging.DEBUG):
        collector = USAJobsCollector()
        jobs = await collector.collect()
    assert len(jobs) == 1
    assert collector.last_report["remote_jobs"] == 1
    assert (
        "private-test@example.com" not in caplog.text
        and "usa-private-test-key" not in caplog.text
    )
    assert settings.USAJOBS_API_KEY not in repr(
        settings
    ) and settings.USAJOBS_EMAIL not in repr(settings)


async def test_pagination_repeat_ids_multi_category_dedup_and_limits(
    rows, transport, monkeypatch
):
    calls = []

    def handler(request):
        calls.append(
            (request.url.params["JobCategoryCode"], request.url.params["Page"])
        )
        row = copy.deepcopy(rows[0])
        row["MatchedObjectId"] = "1" if request.url.params["Page"] == "1" else "2"
        return httpx.Response(200, json=page([row], total=10))

    transport(handler)
    sleep = AsyncMock()
    monkeypatch.setattr("src.collectors.usajobs.asyncio.sleep", sleep)
    collector = USAJobsCollector(max_pages=5, max_jobs=2)
    collector.page_size = 1
    collector.categories = ("2210", "1550")
    jobs = await collector.collect()
    assert [job.external_id for job in jobs] == ["1", "2"]
    assert calls == [("2210", "1"), ("1550", "1"), ("2210", "2")]
    assert sleep.await_count == 2
    assert collector.last_report["api_results_received"] == 3


async def test_repeated_page_stops_and_total_exhaustion(rows, transport, monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=page([rows[0]], total=99))

    transport(handler)
    monkeypatch.setattr("src.collectors.usajobs.asyncio.sleep", AsyncMock())
    collector = USAJobsCollector(max_pages=5)
    collector.page_size = 1
    assert len(await collector.collect()) == 1
    assert len(calls) == 2
    calls.clear()
    collector.max_pages = 1
    await collector.collect()
    assert len(calls) == 1


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500])
async def test_http_failures_sanitized_retry_after(transport, status):
    transport(
        lambda request: httpx.Response(
            status,
            text="usa-private-test-key private-test@example.com",
            headers={"Retry-After": "3600"},
        )
    )
    with pytest.raises(CollectionError) as caught:
        await USAJobsCollector().collect()
    assert "usa-private-test-key" not in str(
        caught.value
    ) and "private-test@example.com" not in str(caught.value)
    if status == 429:
        assert caught.value.retry_at > datetime.now(UTC) + timedelta(minutes=59)
    if status in (401, 403):
        assert "USAJOBS_API_KEY" in str(caught.value) and "USAJOBS_EMAIL" in str(
            caught.value
        )


@pytest.mark.parametrize("error", [httpx.ConnectError, httpx.ReadTimeout])
async def test_network_errors_do_not_leak_headers(transport, error):
    def handler(request):
        raise error("usa-private-test-key private-test@example.com", request=request)

    transport(handler)
    with pytest.raises(CollectionError) as caught:
        await USAJobsCollector().collect()
    assert "private-test" not in str(caught.value)


@pytest.mark.parametrize("compressed", [False, True])
async def test_decompressed_size_limit(transport, monkeypatch, compressed):
    transport(
        lambda request: httpx.Response(
            200,
            content=gzip.compress(b"x" * 1000) if compressed else b"x" * 1000,
            headers={"Content-Encoding": "gzip"} if compressed else {},
        )
    )
    monkeypatch.setattr(USAJobsCollector, "max_response_bytes", 100)
    with pytest.raises(CollectionError, match="size limit"):
        await USAJobsCollector().collect()


async def test_invalid_json(transport):
    transport(lambda request: httpx.Response(200, text="not JSON"))
    with pytest.raises(CollectionError, match="invalid JSON"):
        await USAJobsCollector().collect()


def test_escaped_auth_header_values_redacted(caplog):
    from src.logging_filters import install_network_log_filter

    secret = "test-key-with-'single'-and-\"double\"-quotes\\slash"
    install_network_log_filter(secrets=(secret, "private-email@example.com"))
    with caplog.at_level(logging.DEBUG):
        logging.getLogger("httpcore.http11").debug(
            "request headers: %s",
            [
                (b"Authorization-Key", secret.encode()),
                (b"User-Agent", b"private-email@example.com"),
            ],
        )
    assert "test-key-with" not in caplog.text and "private-email" not in caplog.text


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_pages": 0},
        {"max_pages": 6},
        {"max_pages": True},
        {"max_jobs": 0},
        {"max_jobs": 501},
        {"max_jobs": True},
    ],
)
def test_bounded_constructor(kwargs):
    with pytest.raises(ValueError):
        USAJobsCollector(**kwargs)


def test_settings_empty_credentials_and_bounds():
    config = Settings(
        _env_file=None,
        DB_HOST="localhost",
        DB_USER="test",
        DB_PASS="test",
        DB_NAME="test",
        USAJOBS_API_KEY=" ",
        USAJOBS_EMAIL=" ",
    )
    assert config.USAJOBS_API_KEY is config.USAJOBS_EMAIL is None
    assert (
        config.USAJOBS_MAX_PAGES_PER_QUERY == 2
        and config.USAJOBS_MAX_JOBS_PER_RUN == 100
    )
