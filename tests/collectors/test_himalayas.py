import copy
import gzip
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest

from src.collectors.base import CollectionError
from src.collectors.himalayas import HimalayasCollector, parse_job, parse_page
from src.services.normalization import NormalizationService


@pytest.fixture
def raw():
    return json.loads(
        (Path(__file__).parents[1] / "fixtures/himalayas/jobs.json").read_text()
    )[0]


def test_explicit_fields_and_shared_normalization(raw):
    before = copy.deepcopy(raw)
    job = parse_job(raw)
    assert raw == before
    assert job.source == "himalayas" and job.external_id == raw["guid"]
    assert job.title == "Backend Engineer" and job.company == "Example Labs"
    assert job.description == "Build APIs & services."
    assert job.url == raw["applicationLink"] and job.remote
    assert job.remote_regions == ["Worldwide"]
    assert (job.salary_min, job.salary_max, job.currency, job.salary_period) == (
        90000,
        120000,
        "USD",
        "annual",
    )
    assert job.employment_type == "Full Time" and job.experience_level == "Mid-level"
    assert job.published_at == datetime.fromtimestamp(1792151413, UTC)
    assert job.collected_at.utcoffset() == timedelta(0)
    assert (
        job.timezone_text
        is job.timezone_min_utc_offset
        is job.timezone_max_utc_offset
        is None
    )
    normalized = NormalizationService().normalize(job)
    assert normalized.technologies == ["python", "fastapi", "postgresql"]
    assert (
        normalized.experience_level == "middle"
        and normalized.employment_type == "full_time"
    )
    assert normalized.remote_regions == ["worldwide"]


@pytest.mark.parametrize(
    "restriction,expected",
    [
        ([], ["Worldwide"]),
        (None, []),
        (["LATAM"], ["LATAM"]),
        (["South America"], ["South America"]),
        (["Uruguay"], ["Uruguay"]),
        (["United States"], ["United States"]),
        ([{"name": "Uruguay", "alpha2": "UY", "slug": "uruguay"}], ["Uruguay"]),
        ([{}], []),
    ],
)
def test_explicit_eligibility_no_country_hierarchy(raw, restriction, expected):
    raw["locationRestrictions"] = restriction
    raw["companyLocation"] = "United States"
    job = parse_job(raw)
    assert job.remote and job.remote_regions == expected
    assert job.timezone_text is None


def test_live_shaped_restrictions_and_fractional_offsets():
    fixtures = json.loads(
        (Path(__file__).parents[1] / "fixtures/himalayas/jobs.json").read_text()
    )
    restricted = NormalizationService().normalize(parse_job(fixtures[1]))
    assert restricted.remote_regions == ["bolivia", "uruguay"]
    assert (restricted.timezone_min_utc_offset, restricted.timezone_max_utc_offset) == (
        -4,
        -3,
    )
    fractional = NormalizationService().normalize(parse_job(fixtures[2]))
    assert "UTC-3:30" in fractional.timezone_text
    assert (
        fractional.timezone_min_utc_offset is fractional.timezone_max_utc_offset is None
    )


@pytest.mark.parametrize(
    "offsets,expected",
    [
        ([-5, -4, -3], (-5, -3)),
        ([0], (0, 0)),
        (["UTC-5", "UTC-4"], (-5, -4)),
        ([5.5], (None, None)),
        (["UTC+5:30"], (None, None)),
        ([-10, -9, -8, -7, -6, -5, 14], (None, None)),
        (["bad", "UTC-3"], (None, None)),
        ([], (None, None)),
    ],
)
def test_offset_sets_do_not_gain_unknown_hours_or_round(raw, offsets, expected):
    raw["timezoneRestrictions"] = offsets
    normalized = NormalizationService().normalize(parse_job(raw))
    assert (
        normalized.timezone_min_utc_offset,
        normalized.timezone_max_utc_offset,
    ) == expected


def test_no_description_inference_and_explicit_category_skills(raw):
    raw["description"] = (
        "Senior Python Django PostgreSQL Engineer, 10 years experience, UTC-3"
    )
    raw["categories"] = [
        "Python-Developer",
        "FastAPI",
        "Go-To-Market",
        "C-Level-Executive",
        "Leadership",
    ]
    raw.pop("seniority")
    job = NormalizationService().normalize(parse_job(raw))
    assert set(job.technologies) == {"python", "fastapi"}
    assert job.experience_level is job.timezone_text is None


@pytest.mark.parametrize(
    "value,expected",
    [
        (90000, 90000),
        (90000.0, 90000),
        (True, None),
        (-1, None),
        (1.5, None),
        ("90000", None),
        (float("inf"), None),
    ],
)
def test_salary_not_converted_or_silently_truncated(raw, value, expected):
    raw["minSalary"] = value
    raw["salaryPeriod"] = "hourly"
    job = parse_job(raw)
    assert job.salary_min == expected and job.salary_period == "hourly"


@pytest.mark.parametrize(
    "value,expected",
    [
        (1792151413, datetime.fromtimestamp(1792151413, UTC)),
        (1792151413000, datetime.fromtimestamp(1792151413, UTC)),
        ("2026-10-16T12:00:00Z", datetime(2026, 10, 16, 12, tzinfo=UTC)),
        ("2026-10-16T12:00:00", None),
        (True, None),
        ("invalid", None),
        (1e100, None),
    ],
)
def test_documented_and_live_publication_formats(raw, value, expected):
    raw["pubDate"] = value
    assert parse_job(raw).published_at == expected


def test_missing_optional_fields_stay_unknown(raw):
    job = parse_job({key: raw[key] for key in ("guid", "title", "applicationLink")})
    assert (
        job.company
        is job.description
        is job.location
        is job.salary_min
        is job.salary_max
        is job.currency
        is job.salary_period
        is None
    )
    assert (
        job.experience_level
        is job.employment_type
        is job.published_at
        is job.timezone_text
        is None
    )
    assert job.remote_regions == job.technologies == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("guid", None),
        ("title", ""),
        ("applicationLink", "https://employer.example/apply"),
        ("applicationLink", "https://himalayas.app/jobs/api"),
        ("applicationLink", "https://himalayas.app.evil/companies/x/jobs/y"),
    ],
)
def test_identity_and_attribution_url_are_required(raw, field, value):
    raw[field] = value
    with pytest.raises(ValueError):
        parse_job(raw)


@pytest.mark.parametrize(
    "payload",
    [None, [], {}, {"jobs": {}}, {"jobs": [{}]}, {"jobs": [], "nextCursor": 7}],
)
def test_invalid_pages_are_not_successful_empty_runs(payload):
    with pytest.raises(CollectionError):
        parse_page(payload)


def test_empty_and_mixed_pages_do_not_log_raw_items(raw, caplog):
    assert parse_page({"jobs": []}) == ([], None)
    jobs, cursor = parse_page(
        {"jobs": [{"secret": "private-value"}, raw], "nextCursor": "next"}
    )
    assert len(jobs) == 1 and cursor == "next"
    assert "private-value" not in caplog.text


@pytest.fixture
def transport(monkeypatch):
    client_type = httpx.AsyncClient

    def install(handler):
        factory = Mock(
            side_effect=lambda **kwargs: client_type(
                transport=httpx.MockTransport(handler), **kwargs
            )
        )
        monkeypatch.setattr("src.collectors.himalayas.httpx.AsyncClient", factory)
        return factory

    return install


async def test_bounded_cursor_pagination_without_query_filters(
    raw, transport, monkeypatch
):
    calls = []

    async def sleep(_):
        pass

    monkeypatch.setattr("src.collectors.himalayas.asyncio.sleep", sleep)

    def respond(request):
        calls.append(request)
        job = dict(raw, guid=f"job-{len(calls)}")
        return httpx.Response(
            200, json={"jobs": [job], "nextCursor": f"cursor-{len(calls)}"}
        )

    factory = transport(respond)
    jobs = await HimalayasCollector(max_pages=3, api_key="", timeout=7).collect()
    assert len(jobs) == len(calls) == 3
    assert dict(calls[0].url.params) == {"limit": "20"}
    assert dict(calls[1].url.params) == {"limit": "20", "cursor": "cursor-1"}
    assert factory.call_args.kwargs["timeout"] == 7
    assert not factory.call_args.kwargs["follow_redirects"]
    assert all("Authorization" not in request.headers for request in calls)


@pytest.mark.parametrize(
    "mode", ["empty", "no_cursor", "duplicate_jobs", "repeated_cursor"]
)
async def test_pagination_stops_safely(raw, transport, monkeypatch, mode):
    calls = []

    async def sleep(_):
        pass

    monkeypatch.setattr("src.collectors.himalayas.asyncio.sleep", sleep)

    def respond(request):
        calls.append(request)
        item = dict(
            raw, guid=raw["guid"] if mode == "duplicate_jobs" else str(len(calls))
        )
        return httpx.Response(
            200,
            json={
                "jobs": [] if mode == "empty" else [item],
                "nextCursor": None if mode == "no_cursor" else "repeated",
            },
        )

    transport(respond)
    await HimalayasCollector(max_pages=5, api_key="").collect()
    assert len(calls) == (1 if mode in {"empty", "no_cursor"} else 2)


@pytest.mark.parametrize("status", [401, 403, 404, 500, 503])
async def test_http_errors_are_sanitized(raw, transport, status):
    transport(lambda request: httpx.Response(status, text="secret response body"))
    with pytest.raises(CollectionError, match=f"Himalayas HTTP {status}") as error:
        await HimalayasCollector(api_key="private-key").collect()
    assert "secret" not in str(error.value) and "private-key" not in str(error.value)


@pytest.mark.parametrize("value", ["120", "Fri, 16 Oct 2099 12:00:00 GMT", "invalid"])
async def test_rate_limit_retry_after_without_retry_loop(transport, value):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": value})

    transport(respond)
    with pytest.raises(CollectionError) as error:
        await HimalayasCollector(api_key="").collect()
    assert len(calls) == 1
    assert (error.value.retry_at is None) == (value == "invalid")


@pytest.mark.parametrize("error_type", [httpx.ReadTimeout, httpx.ConnectError])
async def test_network_errors_hide_exception_details(transport, error_type):
    def respond(request):
        raise error_type("private query or key", request=request)

    transport(respond)
    with pytest.raises(CollectionError) as error:
        await HimalayasCollector(api_key="").collect()
    assert "private" not in str(error.value)


@pytest.mark.parametrize("compressed", [False, True])
async def test_size_limit_is_applied_after_decompression(
    transport, monkeypatch, compressed
):
    content = b"x" * 500
    transport(
        lambda request: httpx.Response(
            200,
            content=gzip.compress(content) if compressed else content,
            headers={"Content-Encoding": "gzip"} if compressed else {},
        )
    )
    monkeypatch.setattr(HimalayasCollector, "max_response_bytes", 100)
    with pytest.raises(CollectionError, match="size limit"):
        await HimalayasCollector(api_key="").collect()


async def test_invalid_json_fails(transport):
    transport(lambda request: httpx.Response(200, content=b"not json"))
    with pytest.raises(CollectionError, match="invalid JSON"):
        await HimalayasCollector(api_key="").collect()


async def test_optional_key_uses_authorization_header(raw, transport):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"jobs": [raw]})

    transport(respond)
    await HimalayasCollector(api_key="test-key").collect()
    assert calls[0].headers["Authorization"] == "Bearer test-key"
    assert "test-key" not in str(calls[0].url)


@pytest.mark.parametrize("value", [0, 6, -1, True, 1.5, "2"])
def test_invalid_page_limit(value):
    with pytest.raises(ValueError):
        HimalayasCollector(max_pages=value)


@pytest.mark.parametrize("language", ["en", "es"])
def test_source_brand_callback_and_attribution_in_both_languages(raw, language):
    from src.bot.filters import render_screen
    from src.bot.formatter import build_job_keyboard, format_job_message
    from src.i18n import Language
    from src.schemas.filters import UserFilterDTO
    from src.schemas.scoring import ScoreResult

    locale = Language(language)
    _, keyboard = render_screen(UserFilterDTO(sources=["himalayas"]), "sources", locale)
    buttons = [button for row in keyboard["inline_keyboard"] for button in row]
    selected = next(
        button
        for button in buttons
        if button["callback_data"] == "filters:sources:himalayas"
    )
    assert selected["text"] == "✅ Himalayas"
    job = parse_job(raw)
    assert "Himalayas" in format_job_message(job, ScoreResult(score=82), locale)
    assert (
        build_job_keyboard(42, job.url, locale)["inline_keyboard"][0][0]["url"]
        == raw["applicationLink"]
    )


def test_source_has_no_scoring_bonus(raw):
    from src.schemas.filters import UserFilterDTO
    from src.services.scoring import ScoringService

    job = NormalizationService().normalize(parse_job(raw))
    scoring, filters = ScoringService(), UserFilterDTO()
    assert scoring.calculate(job, filters) == scoring.calculate(
        job.model_copy(update={"source": "remoteok"}), filters
    )
