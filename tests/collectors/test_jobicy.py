import copy
import gzip
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest

from src.collectors.base import CollectionError
from src.collectors.jobicy import JobicyCollector, parse_job, parse_page
from src.services.normalization import NormalizationService


@pytest.fixture
def raw():
    return json.loads(
        (Path(__file__).parents[1] / "fixtures/jobicy/jobs.json").read_text()
    )["jobs"][0]


def page(items, cursor=None):
    return {
        "jobs": items,
        "jobCount": len(items),
        "nextCursor": cursor,
        "hasMore": cursor is not None,
        "success": True,
        "statusCode": 200,
    }


def test_all_explicit_fields_and_no_raw_mutation(raw):
    before = copy.deepcopy(raw)
    job = parse_job(raw)
    assert raw == before
    assert (job.source, job.external_id, job.title, job.company) == (
        "jobicy",
        "147750",
        "Security Software Engineer, IAM",
        "Vercel",
    )
    assert job.url == raw["url"] and job.remote
    assert job.description == "Work with the remote team."
    assert job.location == "USA" and job.remote_regions == ["USA"]
    assert (job.salary_min, job.salary_max, job.currency, job.salary_period) == (
        208000,
        312000,
        "USD",
        "yearly",
    )
    assert job.employment_type == "Full-Time" and job.experience_level == "Senior"
    assert job.published_at == datetime(2026, 10, 16, 3, 50, 3, tzinfo=UTC)
    assert job.collected_at.utcoffset() == timedelta(0)
    assert job.technologies == []
    assert (
        job.timezone_text
        is job.timezone_min_utc_offset
        is job.timezone_max_utc_offset
        is None
    )
    normalized = NormalizationService().normalize(job)
    assert (
        normalized.remote_regions == ["us"]
        and normalized.employment_type == "full_time"
    )


@pytest.mark.parametrize(
    "geo,expected",
    [
        (None, []),
        ("", []),
        ("Anywhere", ["worldwide"]),
        ("Worldwide", ["worldwide"]),
        ("LATAM", ["latam"]),
        ("Europe", ["europe"]),
        ("Canada,  Germany, UK,  USA", ["canada", "germany", "united_kingdom", "us"]),
        ("Uruguay", ["uruguay"]),
    ],
)
def test_explicit_geography_only_no_hierarchy_or_timezone(raw, geo, expected):
    raw["jobGeo"] = geo
    job = NormalizationService().normalize(parse_job(raw))
    assert job.remote_regions == expected
    assert (
        job.timezone_text
        is job.timezone_min_utc_offset
        is job.timezone_max_utc_offset
        is None
    )


def test_real_contract_part_time_worldwide_and_salary_absence():
    raw = json.loads(
        (Path(__file__).parents[1] / "fixtures/jobicy/jobs.json").read_text()
    )["jobs"]
    jobs = [NormalizationService().normalize(parse_job(item)) for item in raw]
    assert jobs[1].remote_regions == ["worldwide"]
    assert (
        jobs[1].salary_min
        is jobs[1].salary_max
        is jobs[1].currency
        is jobs[1].salary_period
        is None
    )
    assert (
        jobs[2].employment_type == "contract" and jobs[3].employment_type == "part_time"
    )


@pytest.mark.parametrize(
    "level,expected",
    [
        ("Senior", "senior"),
        ("Midweight", "middle"),
        ("Entry-Level, Junior", "junior"),
        ("Any", None),
        (None, None),
        ("Director", "director"),
    ],
)
def test_real_experience_values_pass_common_normalization(raw, level, expected):
    raw["jobLevel"] = level
    assert NormalizationService().normalize(parse_job(raw)).experience_level == expected


def test_industry_title_and_description_do_not_become_skills(raw):
    raw.update(
        jobIndustry=["Software Engineering", "Python"],
        jobTitle="Senior Python Developer",
        jobDescription="Python FastAPI Redis PostgreSQL UTC-3",
        jobLevel=None,
    )
    job = parse_job(raw)
    assert (
        job.technologies == []
        and job.experience_level is None
        and job.timezone_text is None
    )


def test_missing_optionals_are_not_invented(raw):
    job = parse_job({key: raw[key] for key in ("id", "jobTitle", "url")})
    assert (
        job.company
        is job.description
        is job.location
        is job.experience_level
        is job.employment_type
        is None
    )
    assert (
        job.salary_min
        is job.salary_max
        is job.currency
        is job.salary_period
        is job.published_at
        is None
    )
    assert job.technologies == job.remote_regions == []


def test_entities_are_decoded_before_fingerprinting_and_display(raw):
    raw.update(jobTitle="Backend &amp; APIs", companyName="Example &amp; Co")
    job = parse_job(raw)
    assert job.title == "Backend & APIs" and job.company == "Example & Co"


@pytest.mark.parametrize(
    "identity", [None, True, False, 0, -1, 1.5, "", {}, [], "no-id"]
)
def test_invalid_identity_never_uses_fingerprint_or_generated_uuid(raw, identity):
    raw["id"] = identity
    with pytest.raises(ValueError):
        parse_job(raw)


@pytest.mark.parametrize(
    "url",
    [
        "https://employer.example/apply",
        "https://jobicy.com/api/v2/remote-jobs",
        "https://jobicy.com.evil/jobs/1",
        "https://jobicy.com/jobs/",
        "http://jobicy.com/jobs/1",
    ],
)
def test_canonical_source_listing_required(raw, url):
    raw["url"] = url
    with pytest.raises(ValueError):
        parse_job(raw)


@pytest.mark.parametrize(
    "value,expected",
    [
        (100, 100),
        (100.0, 100),
        (100.5, None),
        ("100000", None),
        ("USD 100,000", None),
        (-1, None),
        (True, None),
        (float("inf"), None),
    ],
)
def test_salary_values_not_guessed_or_truncated(raw, value, expected):
    raw["salaryMin"] = value
    raw["salaryPeriod"] = "hourly"
    job = parse_job(raw)
    assert job.salary_min == expected and job.salary_period == "hourly"


@pytest.mark.parametrize(
    "value,expected",
    [
        ("2026-10-16T10:00:00+03:00", datetime(2026, 10, 16, 7, tzinfo=UTC)),
        ("2026-10-16T10:00:00Z", datetime(2026, 10, 16, 10, tzinfo=UTC)),
        ("2026-10-16 10:00:00", None),
        (None, None),
        (True, None),
        ("invalid", None),
    ],
)
def test_dates_are_aware_without_invented_publication_time(raw, value, expected):
    raw["pubDate"] = value
    assert parse_job(raw).published_at == expected


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"jobs": {}},
        {"jobs": [{}]},
        {"jobs": [], "success": False},
        {"jobs": [], "statusCode": 500},
        {"jobs": [], "jobCount": True},
        {"jobs": [], "jobCount": 1},
        {"jobs": [], "nextCursor": 7},
        {"jobs": [], "hasMore": True},
        {"jobs": [], "hasMore": False, "nextCursor": "next"},
    ],
)
def test_invalid_pages_not_successful_empty_runs(payload):
    with pytest.raises(CollectionError):
        parse_page(payload)


def test_mixed_page_logging_does_not_expose_items(raw, caplog):
    jobs, cursor = parse_page(page([{"private": "do-not-log"}, raw]))
    assert len(jobs) == 1 and cursor is None
    assert "do-not-log" not in caplog.text
    assert parse_page(page([])) == ([], None)


@pytest.fixture
def transport(monkeypatch):
    client_type = httpx.AsyncClient

    def install(handler):
        factory = Mock(
            side_effect=lambda **kwargs: client_type(
                transport=httpx.MockTransport(handler), **kwargs
            )
        )
        monkeypatch.setattr("src.collectors.jobicy.httpx.AsyncClient", factory)
        return factory

    async def sleep(_):
        pass

    monkeypatch.setattr("src.collectors.pagination.asyncio.sleep", sleep)
    return install


async def test_bounded_global_cursor_requests_no_auth(raw, transport):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(
            200, json=page([dict(raw, id=100 + len(calls))], f"next-{len(calls)}")
        )

    factory = transport(respond)
    jobs = await JobicyCollector(max_pages=2, count=50, timeout=7).collect()
    assert len(jobs) == len(calls) == 2
    assert dict(calls[0].url.params) == {"count": "50"}
    assert dict(calls[1].url.params) == {"count": "50", "cursor": "next-1"}
    assert all("Authorization" not in request.headers for request in calls)
    assert (
        factory.call_args.kwargs["timeout"] == 7
        and not factory.call_args.kwargs["follow_redirects"]
    )


@pytest.mark.parametrize("mode", ["empty", "last", "duplicate", "cursor_loop"])
async def test_stops_on_documented_end_or_nonprogress(raw, transport, mode):
    calls = []

    def respond(request):
        calls.append(request)
        items = (
            []
            if mode == "empty"
            else [dict(raw, id=raw["id"] if mode == "duplicate" else len(calls))]
        )
        return httpx.Response(200, json=page(items, None if mode == "last" else "same"))

    transport(respond)
    await JobicyCollector(max_pages=5).collect()
    assert len(calls) == (1 if mode in {"empty", "last"} else 2)


@pytest.mark.parametrize("status", [400, 401, 403, 404, 500, 503])
async def test_http_errors_hide_body_and_details(transport, status):
    transport(lambda request: httpx.Response(status, text="private-secret-body"))
    with pytest.raises(CollectionError, match=f"Jobicy HTTP {status}") as error:
        await JobicyCollector().collect()
    assert "private" not in str(error.value)


@pytest.mark.parametrize("header", ["3600", "Wed, 16 Oct 2099 12:00:00 GMT", "invalid"])
async def test_retry_after_scheduled_without_immediate_loop(transport, header):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": header})

    transport(respond)
    with pytest.raises(CollectionError) as error:
        await JobicyCollector().collect()
    assert len(calls) == 1
    assert (error.value.retry_at is None) == (header == "invalid")


@pytest.mark.parametrize("error_type", [httpx.ReadTimeout, httpx.ConnectError])
async def test_transport_failures_sanitized(transport, error_type):
    def respond(request):
        raise error_type("private query", request=request)

    transport(respond)
    with pytest.raises(CollectionError) as error:
        await JobicyCollector().collect()
    assert "private" not in str(error.value)


@pytest.mark.parametrize("compressed", [False, True])
async def test_decompressed_response_limit(transport, monkeypatch, compressed):
    content = b"x" * 500
    transport(
        lambda request: httpx.Response(
            200,
            content=gzip.compress(content) if compressed else content,
            headers={"Content-Encoding": "gzip"} if compressed else {},
        )
    )
    monkeypatch.setattr(JobicyCollector, "max_response_bytes", 100)
    with pytest.raises(CollectionError, match="size limit"):
        await JobicyCollector().collect()


async def test_invalid_json(transport):
    transport(lambda request: httpx.Response(200, content=b"not-json"))
    with pytest.raises(CollectionError, match="invalid JSON"):
        await JobicyCollector().collect()


@pytest.mark.parametrize(
    "params",
    [
        {"max_pages": 0},
        {"max_pages": 6},
        {"max_pages": True},
        {"count": 0},
        {"count": 201},
        {"count": True},
    ],
)
def test_page_limits_validated(params):
    with pytest.raises(ValueError):
        JobicyCollector(**params)


@pytest.mark.parametrize("language", ["en", "es"])
def test_attribution_source_keyboard_and_source_neutral_score(raw, language):
    from src.bot.filters import render_screen
    from src.bot.formatter import build_job_keyboard, format_job_message
    from src.i18n import Language
    from src.schemas.filters import UserFilterDTO
    from src.services.scoring import ScoringService

    locale = Language(language)
    job = NormalizationService().normalize(parse_job(raw))
    score = ScoringService().calculate(job, UserFilterDTO())
    assert score == ScoringService().calculate(
        job.model_copy(update={"source": "himalayas"}), UserFilterDTO()
    )
    assert "Jobicy" in format_job_message(job, score, locale)
    assert (
        build_job_keyboard(1, job.url, locale)["inline_keyboard"][0][0]["url"]
        == raw["url"]
    )
    _, markup = render_screen(UserFilterDTO(sources=["jobicy"]), "sources", locale)
    assert any(
        button == {"text": "✅ Jobicy", "callback_data": "filters:sources:jobicy"}
        for row in markup["inline_keyboard"]
        for button in row
    )
