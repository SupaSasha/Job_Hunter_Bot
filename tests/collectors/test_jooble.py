import copy
import gzip
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import quote

import httpx
import pytest

from src.collectors.base import CollectionError, CollectorConfigurationError
from src.collectors.jooble import (
    JOOBLE_SEARCH_QUERIES,
    JoobleCollector,
    parse_job,
    parse_page,
)
from src.config import Settings, settings
from src.services.normalization import NormalizationService


@pytest.fixture
def raw():
    return json.loads(
        (Path(__file__).parents[1] / "fixtures/jooble/jobs.json").read_text()
    )["jobs"][0]


def page(items, total=None):
    return {"jobs": items, "totalCount": len(items) if total is None else total}


def test_all_documented_fields_no_source_alias_or_mutation(raw):
    before = copy.deepcopy(raw)
    now = datetime.now(UTC)
    job = parse_job(raw, collected_at=now)
    assert raw == before
    assert (job.source, job.external_id, job.title, job.company) == (
        "jooble",
        "123",
        "Senior Software Engineer",
        "Acme & Co",
    )
    assert job.description == "Build useful software & APIs."
    assert job.url == raw["link"] and job.location == "Remote"
    assert job.remote and job.remote_regions == []
    assert job.employment_type == "Full-time"
    assert NormalizationService().normalize(job).employment_type == "full_time"
    assert (job.salary_min, job.salary_max, job.currency, job.salary_period) == (
        120000,
        160000,
        "USD",
        "yearly",
    )
    assert job.published_at == datetime(2026, 10, 16, 9, 30, tzinfo=UTC)
    assert job.collected_at == now and now.utcoffset() == timedelta(0)
    assert job.technologies == []
    assert (
        job.experience_level
        is job.timezone_text
        is job.timezone_min_utc_offset
        is job.timezone_max_utc_offset
        is None
    )


def test_real_shaped_office_contract_missing_optional_and_documented_salary():
    rows = json.loads(
        (Path(__file__).parents[1] / "fixtures/jooble/jobs.json").read_text()
    )["jobs"]
    jobs = [NormalizationService().normalize(parse_job(row)) for row in rows]
    assert (
        not jobs[1].remote
        and jobs[1].remote_regions == []
        and jobs[1].employment_type == "contract"
    )
    assert jobs[1].salary_min is jobs[1].published_at is None
    assert jobs[2].remote and jobs[2].salary_min == 17600 and jobs[2].currency == "UAH"
    assert jobs[2].salary_period is None
    assert (
        jobs[3].company
        is jobs[3].description
        is jobs[3].location
        is jobs[3].employment_type
        is None
    )
    assert (
        jobs[3].salary_min
        is jobs[3].salary_max
        is jobs[3].currency
        is jobs[3].salary_period
        is None
    )
    assert not jobs[3].remote


@pytest.mark.parametrize(
    "location,expected",
    [
        ("Remote", True),
        ("REMOTE JOB", True),
        (" Work from home ", True),
        ("London, UK", False),
        ("United States", False),
        ("Hybrid", False),
        ("Remote - United States", False),
        ("Anywhere", False),
        (None, False),
    ],
)
def test_only_obvious_source_location_establishes_remote(raw, location, expected):
    raw.update(
        location=location,
        title="Senior Remote Worldwide Python Engineer",
        snippet="Remote USD 100k UTC-3 Python FastAPI",
        remote=True,
    )
    job = parse_job(raw)
    assert job.remote is expected and job.remote_regions == []
    assert job.technologies == [] and job.experience_level is job.timezone_text is None


@pytest.mark.parametrize(
    "value,expected",
    [
        ("2026-10-16T12:00:00+03:00", datetime(2026, 10, 16, 9, tzinfo=UTC)),
        ("2026-10-16T12:00:00Z", datetime(2026, 10, 16, 12, tzinfo=UTC)),
        ("2023-09-15T12:55:35.3870000", None),
        ("2026-10-16", None),
        ("bad", None),
        (None, None),
    ],
)
def test_updated_is_update_metadata_and_naive_dates_remain_unknown(
    raw, value, expected
):
    raw["updated"] = value
    assert parse_job(raw).published_at == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        ("17,600 UAH", (17600, 17600, "UAH", None)),
        ("120k–160k USD/year", (120000, 160000, "USD", "yearly")),
        ("USD 120000 - 160000", (120000, 160000, "USD", None)),
        ("GBP 60/hour", (60, 60, "GBP", "hourly")),
        ("€100000 per year", (100000, 100000, "EUR", "yearly")),
        ("100000 CAD", (100000, 100000, "CAD", None)),
        ("$120k-$160k", (None, None, None, None)),
        ("17.600 UAH", (None, None, None, None)),
        ("USD 60.5/hour", (None, None, None, None)),
        ("USD 160k-120k", (None, None, None, None)),
        ("USD 120-160k", (None, None, None, None)),
        ("up to USD 100000", (None, None, None, None)),
        ("USD 100000 plus bonus", (None, None, None, None)),
        ("negotiable", (None, None, None, None)),
        ("", (None, None, None, None)),
    ],
)
def test_conservative_shared_salary_parser_no_currency_or_period_inference(
    raw, value, expected
):
    raw["salary"] = value
    job = parse_job(raw)
    assert (job.salary_min, job.salary_max, job.currency, job.salary_period) == expected


@pytest.mark.parametrize("value", [-123, 0, 123, "-123", "123"])
def test_stable_documented_id_not_assumed_positive_only(raw, value):
    raw["id"] = value
    assert parse_job(raw).external_id == str(int(value))


@pytest.mark.parametrize(
    "value", [None, True, False, 1.5, "", "arbitrary-slug", [], {}]
)
def test_missing_invalid_identity_never_generates_hash_or_uuid(raw, value):
    raw["id"] = value
    with pytest.raises(ValueError):
        parse_job(raw)


@pytest.mark.parametrize(
    "url",
    [
        "https://uk.jooble.org/jdp/123",
        "https://jooble.org/redirect?id=123",
        "https://employer.example/jobs/123",
        "http://board.example/jobs/123",
    ],
)
def test_official_returned_listing_or_redirect_preserved_without_following(raw, url):
    raw["link"] = url
    assert parse_job(raw).url == url


@pytest.mark.parametrize(
    "url", ["javascript:alert(1)", "/jobs/123", "https://user:secret@board.example/123"]
)
def test_invalid_listing_link_rejected(raw, url):
    raw["link"] = url
    with pytest.raises(ValueError):
        parse_job(raw)


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"jobs": {}},
        page([], True),
        page([], -1),
        page([{}]),
        page([{}], 0),
    ],
)
def test_invalid_pages_fail_not_successfully_empty(payload):
    with pytest.raises(CollectionError):
        parse_page(payload)


def test_empty_and_mixed_pages_sanitized(raw, caplog):
    assert parse_page(page([])) == ([], 0)
    jobs, total = parse_page(page([{"secret": "do-not-log"}, raw]))
    assert len(jobs) == 1 and total == 2 and "do-not-log" not in caplog.text


@pytest.fixture
def transport(monkeypatch):
    client_type = httpx.AsyncClient
    monkeypatch.setattr(settings, "JOOBLE_API_KEY", "test-private-key/+?=")
    monkeypatch.setattr(settings, "JOOBLE_API_DOMAIN", "uk.jooble.org")
    monkeypatch.setattr(settings, "JOOBLE_SEARCH_LOCATION", "United Kingdom")

    def install(handler):
        factory = Mock(
            side_effect=lambda **kwargs: client_type(
                transport=httpx.MockTransport(handler), **kwargs
            )
        )
        monkeypatch.setattr("src.collectors.jooble.httpx.AsyncClient", factory)
        return factory

    async def sleep(_):
        pass

    monkeypatch.setattr("src.collectors.jooble.asyncio.sleep", sleep)
    return install


@pytest.mark.parametrize(
    "missing", ["JOOBLE_API_KEY", "JOOBLE_API_DOMAIN", "JOOBLE_SEARCH_LOCATION"]
)
async def test_missing_configuration_fails_before_any_network(
    transport, monkeypatch, missing
):
    factory = transport(lambda request: pytest.fail("No configured request expected"))
    monkeypatch.setattr(settings, missing, None)
    with pytest.raises(CollectorConfigurationError, match=missing):
        await JoobleCollector().collect()
    factory.assert_not_called()


async def test_two_broad_queries_dedup_identical_id_123_no_per_user_calls(
    raw, transport, caplog
):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, json=page([raw]))

    factory = transport(respond)
    collector = JoobleCollector(timeout=7)
    with caplog.at_level(logging.DEBUG):
        jobs = await collector.collect()
    assert len(jobs) == 1 and jobs[0].external_id == "123"
    assert (
        len(calls) == 2
        and tuple(json.loads(r.content)["keywords"] for r in calls)
        == JOOBLE_SEARCH_QUERIES
    )
    for request in calls:
        assert request.method == "POST" and request.url.host == "uk.jooble.org"
        assert (
            request.url.raw_path
            == ("/api/" + quote(settings.JOOBLE_API_KEY, safe="")).encode()
        )
        assert json.loads(request.content) == {
            "keywords": json.loads(request.content)["keywords"],
            "location": "United Kingdom",
            "page": 1,
            "ResultOnPage": 20,
            "companysearch": False,
        }
        assert "Authorization" not in request.headers and not request.url.query
        assert request.headers["Content-Type"] == "application/json"
    assert collector.query_job_ids == {"software": ["123"], "developer": ["123"]}
    assert (
        collector.last_report["api_results_received"] == 2
        and collector.last_report["unique_jobs"] == 1
    )
    assert [q["contributed"] for q in collector.last_report["queries"]] == [1, 0]
    assert "test-private-key" not in caplog.text and "/api/<redacted>" in caplog.text
    assert settings.JOOBLE_API_KEY not in repr(settings)
    assert (
        factory.call_args.kwargs["timeout"] == 7
        and not factory.call_args.kwargs["follow_redirects"]
    )


async def test_small_bounded_round_robin_pagination(raw, transport):
    calls = []

    def respond(request):
        calls.append(json.loads(request.content))
        return httpx.Response(
            200,
            json=page([dict(raw, id=100 * len(calls) + i) for i in range(20)], 10000),
        )

    transport(respond)
    jobs = await JoobleCollector(max_pages=3, max_jobs=200).collect()
    assert len(jobs) == 120 and len(calls) == 6
    assert [(call["keywords"], call["page"]) for call in calls] == [
        (q, p) for p in (1, 2, 3) for q in JOOBLE_SEARCH_QUERIES
    ]


async def test_per_run_cap_even_if_provider_ignores_page_size(raw, transport):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(
            200, json=page([dict(raw, id=i) for i in range(100)], 10000)
        )

    transport(respond)
    jobs = await JoobleCollector(max_pages=3, max_jobs=7).collect()
    assert len(jobs) == 7 and len(calls) == 1


@pytest.mark.parametrize("mode", ["empty", "short", "total", "repeated"])
async def test_pagination_stops_per_query_at_end_or_no_progress(raw, transport, mode):
    calls = []

    def respond(request):
        calls.append(request)
        size = 0 if mode == "empty" else 1 if mode == "short" else 20
        return httpx.Response(
            200,
            json=page(
                [dict(raw, id=i) for i in range(size)], 20 if mode == "total" else 10000
            ),
        )

    transport(respond)
    await JoobleCollector(max_pages=3, max_jobs=200).collect()
    assert len(calls) == (4 if mode == "repeated" else 2)


@pytest.mark.parametrize("status", [400, 401, 403, 404, 500, 503])
async def test_http_failures_do_not_expose_path_key_or_body(transport, status):
    transport(
        lambda request: httpx.Response(status, text="private body test-private-key")
    )
    with pytest.raises(CollectionError) as caught:
        await JoobleCollector().collect()
    assert "private" not in str(caught.value)
    if status in {401, 403}:
        assert "JOOBLE_API_KEY" in str(caught.value) and "domain" in str(caught.value)


@pytest.mark.parametrize("header", ["3600", "Wed, 16 Oct 2099 12:00:00 GMT", "invalid"])
async def test_retry_after_deferred_without_immediate_retry(transport, header):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": header})

    transport(respond)
    with pytest.raises(CollectionError) as caught:
        await JoobleCollector().collect()
    assert len(calls) == 1 and (caught.value.retry_at is None) == (header == "invalid")


@pytest.mark.parametrize("error_type", [httpx.ReadTimeout, httpx.ConnectError])
async def test_network_error_path_sanitized(transport, error_type):
    def respond(request):
        raise error_type(str(request.url), request=request)

    transport(respond)
    with pytest.raises(CollectionError) as caught:
        await JoobleCollector().collect()
    assert "test-private-key" not in str(caught.value)


@pytest.mark.parametrize("compressed", [False, True])
async def test_decompressed_size_limit(transport, monkeypatch, compressed):
    content = b"x" * 500
    transport(
        lambda request: httpx.Response(
            200,
            content=gzip.compress(content) if compressed else content,
            headers={"Content-Encoding": "gzip"} if compressed else {},
        )
    )
    monkeypatch.setattr(JoobleCollector, "max_response_bytes", 100)
    with pytest.raises(CollectionError, match="size limit"):
        await JoobleCollector().collect()


async def test_invalid_json(transport):
    transport(lambda request: httpx.Response(200, content=b"private-not-json"))
    with pytest.raises(CollectionError, match="invalid JSON"):
        await JoobleCollector().collect()


@pytest.mark.parametrize(
    "name", ["httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2"]
)
def test_relative_http_diagnostics_redact_path_secret(name, caplog):
    with caplog.at_level(logging.DEBUG):
        logging.getLogger(name).debug(
            "request target=%r", b"/api/test-private-key%2F?x=1"
        )
    assert (
        "test-private-key" not in caplog.text and "/api/<redacted>?x=1" in caplog.text
    )


@pytest.mark.parametrize("domain", ["jooble.org", "uk.jooble.org", "de.jooble.org"])
def test_explicit_single_regional_domain_config(domain):
    cfg = Settings(
        _env_file=None,
        DB_HOST="test",
        DB_USER="test",
        DB_PASS="test",
        DB_NAME="test",
        JOOBLE_API_DOMAIN=domain,
    )
    assert cfg.JOOBLE_API_DOMAIN == domain


@pytest.mark.parametrize(
    "domain",
    [
        "evil.example",
        "jooble.org.evil",
        "https://jooble.org/api",
        "user@jooble.org",
        "jooble.org/path",
        "localhost",
    ],
)
def test_domain_cannot_redirect_keys_to_arbitrary_host(domain):
    with pytest.raises(ValueError):
        Settings(
            _env_file=None,
            DB_HOST="test",
            DB_USER="test",
            DB_PASS="test",
            DB_NAME="test",
            JOOBLE_API_DOMAIN=domain,
        )


@pytest.mark.parametrize(
    "arguments",
    [
        {"max_pages": 0},
        {"max_pages": 4},
        {"max_pages": True},
        {"max_jobs": 0},
        {"max_jobs": 201},
        {"max_jobs": True},
    ],
)
def test_limits_validated(arguments):
    with pytest.raises(ValueError):
        JoobleCollector(**arguments)


@pytest.mark.parametrize("language", ["en", "es"])
def test_shared_source_filters_attribution_and_source_neutral_score(raw, language):
    from src.bot.filters import render_screen
    from src.bot.formatter import build_job_keyboard, format_job_message
    from src.i18n import Language
    from src.schemas.filters import UserFilterDTO
    from src.services.scoring import ScoringService

    locale = Language(language)
    job = NormalizationService().normalize(parse_job(raw))
    score = ScoringService().calculate(job, UserFilterDTO())
    assert score == ScoringService().calculate(
        job.model_copy(update={"source": "jobicy"}), UserFilterDTO()
    )
    assert "Jooble" in format_job_message(job, score, locale)
    assert (
        build_job_keyboard(1, job.url, locale)["inline_keyboard"][0][0]["url"]
        == raw["link"]
    )
    _, markup = render_screen(UserFilterDTO(sources=["jooble"]), "sources", locale)
    assert any(
        button == {"text": "✅ Jooble", "callback_data": "filters:sources:jooble"}
        for row in markup["inline_keyboard"]
        for button in row
    )
