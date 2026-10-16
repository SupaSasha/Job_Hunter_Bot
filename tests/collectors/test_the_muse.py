import copy
import gzip
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest

from src.collectors.base import CollectionError
from src.collectors.the_muse import (
    REMOTE_LOCATION,
    TheMuseCollector,
    parse_job,
    parse_page,
)
from src.config import settings
from src.services.normalization import NormalizationService


@pytest.fixture
def raw():
    return json.loads(
        (Path(__file__).parents[1] / "fixtures/the_muse/jobs.json").read_text()
    )["results"][0]


def page(items, number=0, count=1):
    return {"results": items, "page": number, "page_count": count, "timed_out": False}


def test_real_fields_mapping_and_no_mutation(raw):
    before = copy.deepcopy(raw)
    now = datetime.now(UTC)
    job = parse_job(raw, collected_at=now)
    assert raw == before
    assert (job.source, job.external_id, job.title, job.company) == (
        "the_muse",
        "22229841",
        raw["name"],
        "Atlassian",
    )
    assert job.description == "Join our team & build useful products."
    assert job.url == raw["refs"]["landing_page"]
    assert job.location == "Bangalore, India, Flexible / Remote"
    assert job.remote and job.remote_regions == []
    assert job.experience_level == "Senior Level"
    assert NormalizationService().normalize(job).experience_level == "senior"
    assert job.published_at == datetime(2026, 10, 3, 21, 25, 38, tzinfo=UTC)
    assert job.collected_at == now and job.collected_at.utcoffset() == timedelta(0)
    assert job.technologies == []
    assert all(
        getattr(job, field) is None
        for field in (
            "employment_type",
            "salary_min",
            "salary_max",
            "currency",
            "salary_period",
            "timezone_text",
            "timezone_min_utc_offset",
            "timezone_max_utc_offset",
        )
    )


@pytest.mark.parametrize(
    "locations,expected",
    [
        ([{"name": REMOTE_LOCATION}], True),
        ([{"name": "flexible / remote"}, {"name": "New York, NY"}], True),
        ([{"name": "New York, NY"}], False),
        ([{"name": "On-site"}], False),
        ([{"name": "Remote possible"}], False),
        ([], False),
        (None, False),
        ({"name": REMOTE_LOCATION}, False),
    ],
)
def test_only_explicit_location_marker_establishes_remote(raw, locations, expected):
    raw.update(locations=locations, name="Remote worldwide Python engineer")
    job = parse_job(raw)
    assert job.remote is expected
    assert job.remote_regions == [] and job.timezone_text is None


def test_live_fixtures_cover_nonremote_multiple_locations_and_missing_fields():
    rows = json.loads(
        (Path(__file__).parents[1] / "fixtures/the_muse/jobs.json").read_text()
    )["results"]
    jobs = [parse_job(row) for row in rows]
    assert jobs[0].remote and not jobs[1].remote
    assert len(rows[0]["locations"]) > 1
    assert jobs[2].remote and len(rows[2]["levels"]) > 1
    assert jobs[2].experience_level == ", ".join(
        item["name"] for item in rows[2]["levels"]
    )
    minimal = jobs[3]
    assert minimal.company is minimal.description is minimal.location is None
    assert minimal.published_at is minimal.experience_level is None
    assert not minimal.remote and minimal.remote_regions == minimal.technologies == []


@pytest.mark.parametrize(
    "level,expected",
    [
        ("Entry Level", "junior"),
        ("Mid Level", "middle"),
        ("Senior Level", "senior"),
        ("Management", "management"),
        ("Internship", "internship"),
        (None, None),
    ],
)
def test_source_levels_use_shared_normalization(raw, level, expected):
    raw["levels"] = [{"name": level}] if level else []
    assert NormalizationService().normalize(parse_job(raw)).experience_level == expected


def test_categories_tags_type_and_description_do_not_invent_structured_fields(raw):
    raw.update(
        contents="Full time Python USD 150000 UTC-3 Senior remote worldwide",
        categories=[{"name": "Software Engineering"}, {"name": "Data Science"}],
        tags=[{"name": "Fortune 1000"}],
        type="external",
        levels=[],
    )
    job = parse_job(raw)
    assert job.technologies == []
    assert job.employment_type is job.experience_level is job.salary_min is None
    assert job.timezone_text is None and job.remote_regions == []


@pytest.mark.parametrize("value", [None, True, False, 0, -1, 1.5, "", "slug", [], {}])
def test_invalid_identity_is_not_replaced(raw, value):
    raw["id"] = value
    with pytest.raises(ValueError):
        parse_job(raw)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.themuse.com/api/public/jobs/1",
        "https://employer.example/apply",
        "https://www.themuse.com.evil/jobs/company/title",
        "https://www.themuse.com/jobs/",
        "http://www.themuse.com/jobs/company/title",
    ],
)
def test_requires_canonical_source_listing(raw, url):
    raw["refs"] = {"landing_page": url}
    with pytest.raises(ValueError):
        parse_job(raw)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("2026-10-16T10:00:00+03:00", datetime(2026, 10, 16, 7, tzinfo=UTC)),
        ("2026-10-16T10:00:00Z", datetime(2026, 10, 16, 10, tzinfo=UTC)),
        ("2026-10-16T10:00:00", None),
        ("bad", None),
        (None, None),
    ],
)
def test_publication_date_not_fabricated(raw, value, expected):
    raw["publication_date"] = value
    assert parse_job(raw).published_at == expected


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"results": {}},
        page([{}]),
        {**page([]), "page_count": True},
        {**page([]), "page_count": -1},
        {**page([]), "page": True},
        {**page([]), "page": 1},
        {**page([]), "timed_out": True},
    ],
)
def test_invalid_or_partial_pages_do_not_appear_successful(payload):
    with pytest.raises(CollectionError):
        parse_page(payload, page=0)


def test_mixed_and_empty_pages_sanitized(raw, caplog):
    jobs, more = parse_page(page([{"secret": "do-not-log"}, raw]), page=0)
    assert len(jobs) == 1 and not more
    assert "do-not-log" not in caplog.text
    assert parse_page(page([], count=0), page=0) == ([], False)


@pytest.fixture
def transport(monkeypatch):
    client_type = httpx.AsyncClient
    monkeypatch.setattr(settings, "THE_MUSE_API_KEY", None)

    def install(handler):
        factory = Mock(
            side_effect=lambda **kwargs: client_type(
                transport=httpx.MockTransport(handler), **kwargs
            )
        )
        monkeypatch.setattr("src.collectors.the_muse.httpx.AsyncClient", factory)
        return factory

    async def sleep(_):
        pass

    monkeypatch.setattr("src.collectors.the_muse.asyncio.sleep", sleep)
    return install


async def test_bounded_pages_global_remote_query_anonymous(raw, transport):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(
            200, json=page([dict(raw, id=len(calls))], len(calls) - 1, 100)
        )

    factory = transport(respond)
    jobs = await TheMuseCollector(max_pages=3, timeout=7).collect()
    assert len(calls) == len(jobs) == 3
    for index, request in enumerate(calls):
        assert dict(request.url.params) == {
            "page": str(index),
            "descending": "true",
            "location": REMOTE_LOCATION,
        }
        assert "Authorization" not in request.headers
    assert factory.call_args.kwargs["timeout"] == 7
    assert not factory.call_args.kwargs["follow_redirects"]


@pytest.mark.parametrize("mode", ["empty", "last", "duplicate"])
async def test_stops_at_end_or_no_progress(raw, transport, mode):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(
            200,
            json=page(
                [] if mode == "empty" else [raw],
                len(calls) - 1,
                1 if mode == "last" else 5,
            ),
        )

    transport(respond)
    await TheMuseCollector(max_pages=5).collect()
    assert len(calls) == (2 if mode == "duplicate" else 1)


@pytest.mark.parametrize("status", [200, 400, 401, 403, 404, 500, 503])
async def test_documented_key_transport_and_safe_logs(
    raw, transport, monkeypatch, caplog, status
):
    calls = []
    secret = "test-private-key/+?="
    monkeypatch.setattr(settings, "THE_MUSE_API_KEY", secret)

    def respond(request):
        calls.append(request)
        return httpx.Response(
            status, json=page([raw]) if status == 200 else {"error": secret}
        )

    transport(respond)
    with caplog.at_level(logging.DEBUG):
        if status == 200:
            assert len(await TheMuseCollector().collect()) == 1
        else:
            with pytest.raises(CollectionError) as caught:
                await TheMuseCollector().collect()
            assert secret not in str(caught.value)
            if status in {401, 403}:
                assert "THE_MUSE_API_KEY" in str(caught.value)
    assert calls[0].url.params["api_key"] == secret
    assert "Authorization" not in calls[0].headers
    assert secret not in caplog.text and "test-private-key" not in caplog.text
    assert "api_key=<redacted>" in caplog.text
    assert secret not in repr(settings)


@pytest.mark.parametrize("header", ["3600", "Wed, 16 Oct 2099 12:00:00 GMT", "invalid"])
async def test_retry_after_uses_common_helper_without_retry_loop(transport, header):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": header})

    transport(respond)
    with pytest.raises(CollectionError) as caught:
        await TheMuseCollector().collect()
    assert len(calls) == 1
    assert (caught.value.retry_at is None) == (header == "invalid")


@pytest.mark.parametrize("error_type", [httpx.ReadTimeout, httpx.ConnectError])
async def test_network_errors_do_not_expose_request(transport, error_type):
    def respond(request):
        raise error_type("private URL/key", request=request)

    transport(respond)
    with pytest.raises(CollectionError) as caught:
        await TheMuseCollector().collect()
    assert "private" not in str(caught.value)


@pytest.mark.parametrize("compressed", [False, True])
async def test_decompressed_response_size_limit(transport, monkeypatch, compressed):
    content = b"x" * 500
    transport(
        lambda request: httpx.Response(
            200,
            content=gzip.compress(content) if compressed else content,
            headers={"Content-Encoding": "gzip"} if compressed else {},
        )
    )
    monkeypatch.setattr(TheMuseCollector, "max_response_bytes", 100)
    with pytest.raises(CollectionError, match="size limit"):
        await TheMuseCollector().collect()


async def test_invalid_json(transport):
    transport(lambda request: httpx.Response(200, content=b"not-json"))
    with pytest.raises(CollectionError, match="invalid JSON"):
        await TheMuseCollector().collect()


async def test_production_requires_registered_key_before_network(
    transport, monkeypatch
):
    factory = transport(lambda request: pytest.fail("Unexpected anonymous request"))
    monkeypatch.setattr(settings, "MODE", "PROD")
    with pytest.raises(CollectionError, match="registered THE_MUSE_API_KEY"):
        await TheMuseCollector().collect()
    factory.assert_not_called()


@pytest.mark.parametrize("limit", [0, 6, True, 1.5, "3"])
def test_bounded_config(limit):
    with pytest.raises(ValueError):
        TheMuseCollector(max_pages=limit)


@pytest.mark.parametrize("language", ["en", "es"])
def test_attribution_source_button_and_source_neutral_scoring(raw, language):
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
    assert "The Muse" in format_job_message(job, score, locale)
    assert (
        build_job_keyboard(1, job.url, locale)["inline_keyboard"][0][0]["url"]
        == job.url
    )
    _, markup = render_screen(UserFilterDTO(sources=["the_muse"]), "sources", locale)
    assert any(
        button == {"text": "✅ The Muse", "callback_data": "filters:sources:the_muse"}
        for row in markup["inline_keyboard"]
        for button in row
    )


@pytest.mark.parametrize(
    "name", ["httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2"]
)
def test_http_diagnostics_redact_query_keys(name, caplog):
    with caplog.at_level(logging.DEBUG):
        logging.getLogger(name).debug(
            "request target=%r",
            b"/api/public/jobs?page=0&api_key=test-private-key%2F&location=Remote",
        )
    assert "test-private-key" not in caplog.text
    assert "api_key=<redacted>&location=Remote" in caplog.text
