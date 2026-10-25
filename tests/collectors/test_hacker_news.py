import copy
import gzip
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest

from src.collectors.base import CollectionError
from src.collectors.hacker_news import (
    HackerNewsCollector,
    find_thread,
    parse_comment,
    parse_thread,
    thread_titles,
)
from src.services.normalization import NormalizationService

NOW = datetime(2026, 10, 16, 16, tzinfo=UTC)
TITLE = "Ask HN: Who is hiring? (October 2026)"
THREAD = 49922569


@pytest.fixture
def root():
    return json.loads(
        (Path(__file__).parents[1] / "fixtures/hacker_news/thread.json").read_text()
    )


@pytest.fixture
def raw(root):
    return root["children"][0]


def hit(
    title=TITLE, identity=THREAD, author="whoishiring", date="2026-10-01T15:02:07Z"
):
    return {
        "objectID": str(identity),
        "title": title,
        "author": author,
        "_tags": ["story"],
        "created_at": date,
    }


def job(raw, text=None):
    if text is not None:
        raw = dict(raw, text=text)
    value = parse_comment(raw, thread_id=THREAD)
    assert value is not None
    return NormalizationService().normalize(value)


def test_current_thread_preferred_and_previous_month_fallback():
    previous = hit(
        "Ask HN: Who is hiring? (September 2026)", 49522897, date="2026-09-01T15:01:17Z"
    )
    assert find_thread({"hits": [previous, hit()]}, NOW) == (THREAD, TITLE)
    assert find_thread({"hits": [previous]}, NOW) == (49522897, previous["title"])
    assert thread_titles(datetime(2027, 1, 1, tzinfo=UTC)) == (
        "Ask HN: Who is hiring? (January 2027)",
        "Ask HN: Who is hiring? (December 2026)",
    )


@pytest.mark.parametrize(
    "change",
    [
        {"title": "Ask HN: Who wants to be hired? (October 2026)"},
        {"title": "Who is hiring Python developers?"},
        {"author": "random"},
        {"_tags": ["comment"]},
        {"_tags": None},
        {"objectID": True},
        {"created_at": "2026-09-01T00:00:00Z"},
        {"created_at": None},
    ],
)
def test_thread_identity_is_not_any_hiring_search_result(change):
    with pytest.raises(CollectionError):
        find_thread({"hits": [{**hit(), **change}]}, NOW)


@pytest.mark.parametrize("payload", [None, [], {}, {"hits": {}}, {"hits": []}])
def test_invalid_or_missing_thread_search_fails(payload):
    with pytest.raises(CollectionError):
        find_thread(payload, NOW)


def test_typical_explicit_fields_canonical_link_and_no_mutation(raw):
    before = copy.deepcopy(raw)
    parsed = parse_comment(raw, thread_id=THREAD, collected_at=NOW)
    assert raw == before
    assert parsed.source == "hacker_news" and parsed.external_id == "49922584"
    assert parsed.company == "Acme & Co" and parsed.title == "Senior Backend Engineer"
    assert parsed.url == "https://news.ycombinator.com/item?id=49922584"
    assert parsed.remote and parsed.remote_regions == ["LATAM"]
    assert "<p>" not in parsed.description and "&amp;" not in parsed.description
    assert parsed.published_at == datetime(2026, 10, 1, 15, 2, 37, tzinfo=UTC)
    assert parsed.collected_at == NOW
    assert parsed.timezone_text == "UTC-5 to UTC+1"
    normalized = NormalizationService().normalize(parsed)
    assert (
        normalized.timezone_min_utc_offset == -5
        and normalized.timezone_max_utc_offset == 1
    )
    assert normalized.remote_regions == ["latam"]
    assert (
        normalized.employment_type == "full_time"
        and normalized.experience_level == "senior"
    )
    assert {"python", "fastapi", "postgresql", "redis", "docker"} <= set(
        normalized.technologies
    )
    assert (
        normalized.salary_min,
        normalized.salary_max,
        normalized.currency,
        normalized.salary_period,
    ) == (120000, 160000, "USD", "yearly")


def test_top_level_only_deleted_noise_multi_and_unknown(root):
    jobs, report = parse_thread(root, thread_id=THREAD, title=TITLE)
    assert len(jobs) == 4 and report["top_level_received"] == 7
    assert (
        report["parsed"] == 4 and report["ignored"] == 3 and report["multi_role"] == 1
    )
    assert all(item.external_id != "49922999" for item in jobs)
    assert jobs[2].title == "Multiple roles" and jobs[2].experience_level is None
    unknown = jobs[3]
    assert unknown.company is None and not unknown.remote
    assert (
        unknown.employment_type is unknown.salary_min is unknown.timezone_text is None
    )
    assert unknown.remote_regions == unknown.technologies == []
    assert parse_comment(root["children"][0]["children"][0], thread_id=THREAD) is None


@pytest.mark.parametrize(
    "marker,remote,regions",
    [
        ("Remote", True, []),
        ("REMOTE (US only)", True, ["us_only"]),
        ("Remote | USA only", True, ["us_only"]),
        ("Remote | Worldwide", True, ["worldwide"]),
        ("Remote | Anywhere", True, ["worldwide"]),
        ("Remote | Europe | EMEA", True, ["europe", "emea"]),
        (
            "Remote | APAC | Canada | Uruguay | South America",
            True,
            ["apac", "canada", "uruguay", "south_america"],
        ),
        ("Remote | US timezones", True, []),
        ("Remote | not US only", True, []),
        ("On-site NYC", False, []),
        ("ONSITE", False, []),
        ("Hybrid / Remote", False, []),
        ("No remote", False, []),
        ("Non-remote", False, []),
        ("New York, NY", False, []),
    ],
)
def test_only_explicit_workplace_and_regions(raw, marker, remote, regions):
    parsed = job(raw, f"Acme | Backend Engineer | {marker}")
    assert parsed.remote is remote and parsed.remote_regions == regions
    assert parsed.location is None


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Acme | Senior Backend Engineer | Remote", "Senior Backend Engineer"),
        ("Acme | Sales Manager | Remote", "Sales Manager"),
        ("Acme | UX Designer | Remote", "UX Designer"),
        ("Acme | Accountant | Remote", "Accountant"),
        ("Acme | Customer Support Specialist | Remote", "Customer Support Specialist"),
        ("Acme | Marketing Specialist | Remote", "Marketing Specialist"),
        ("Acme | Recruiter | Remote", "Recruiter"),
        ("Acme | Data Analyst | Remote", "Data Analyst"),
        ("Acme | Remote<p>Mid Backend Engineer", "Mid Backend Engineer"),
        ("Acme | Remote | Python", "Multiple roles"),
        ("Acme | Backend Engineer, Product Designer | Remote", "Multiple roles"),
        (
            "Acme | Remote<p>We are hiring:<ul><li>Backend Engineer</li>"
            "<li>DevOps Engineer</li></ul>",
            "Multiple roles",
        ),
        (
            "Acme | Cloud Engineer | Remote<p>We work directly with their developers.",
            "Cloud Engineer",
        ),
        (
            "Acme | Full-Stack Software Engineer | Remote",
            "Full-Stack Software Engineer",
        ),
    ],
)
def test_bounded_title_and_one_entry_per_comment(raw, text, expected):
    assert job(raw, text).title == expected


def test_company_parentheses_preserved_and_urls_not_company_identity(raw):
    assert (
        job(raw, "Acme (Series B) | Backend Engineer | Remote").company
        == "Acme (Series B)"
    )
    assert (
        job(raw, "Acme (https://example.com) | Backend Engineer | Remote").company
        == "Acme"
    )


@pytest.mark.parametrize(
    "level,expected",
    [
        ("Senior", "senior"),
        ("Mid", None),
        ("Junior", "junior"),
        ("Staff", None),
        ("Lead", "lead"),
        ("Principal", "principal"),
    ],
)
def test_experience_only_from_single_explicit_role(raw, level, expected):
    assert (
        job(raw, f"Acme | {level} Backend Engineer | Remote").experience_level
        == expected
    )


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("Full-time", "full_time"),
        ("Part-time", "part_time"),
        ("Contract", "contract"),
        ("Freelance", "freelance"),
        ("Internship", "internship"),
        ("No internship", None),
        ("Full-time / Contract", None),
    ],
)
def test_employment_uses_shared_normalization(raw, kind, expected):
    assert (
        job(raw, f"Acme | Backend Engineer | Remote | {kind}").employment_type
        == expected
    )


def test_known_tech_tokens_aliases_and_short_word_boundaries(raw):
    parsed = job(
        raw,
        "Acme | Backend Engineer | Remote<p>Python/FastAPI/Postgres, Redis, Docker, "
        "Kubernetes, TypeScript, React, Go, Rust, C++, C#. We go to market. "
        "https://python.example.com",
    )
    assert {
        "python",
        "fastapi",
        "postgresql",
        "redis",
        "docker",
        "kubernetes",
        "typescript",
        "react",
        "go",
        "rust",
        "c++",
        "c#",
    } <= set(parsed.technologies)
    assert (
        job(
            raw,
            "Acme | Backend Engineer | Remote<p>We go-to-market and move quickly. "
            "Contact python@example.com.",
        ).technologies
        == []
    )


@pytest.mark.parametrize(
    "value,low,high",
    [
        ("UTC-3", -3, -3),
        ("GMT-3", -3, -3),
        ("UTC-5 to UTC+1", -5, 1),
        ("UTC+5:30", None, None),
        ("CET", None, None),
        ("EST / PST", None, None),
        ("UTC-5 or UTC+1", None, None),
        ("UTC+99", None, None),
    ],
)
def test_timezone_text_uses_existing_common_offset_parser(raw, value, low, high):
    parsed = job(raw, f"Acme | Backend Engineer | Remote | {value}")
    assert (
        parsed.timezone_min_utc_offset == low and parsed.timezone_max_utc_offset == high
    )
    if value != "UTC+99":
        assert parsed.timezone_text is not None


@pytest.mark.parametrize(
    "value,expected",
    [
        ("$120k-$160k", (120000, 160000, None, None)),
        ("$120,000 - $160,000", (120000, 160000, None, None)),
        ("USD 120k–160k/year", (120000, 160000, "USD", "yearly")),
        ("$60/hour", (60, 60, None, "hourly")),
        ("EUR 100000 per year", (100000, 100000, "EUR", "yearly")),
        ("$120-160k", (None, None, None, None)),
        ("$160k-$120k", (None, None, None, None)),
        ("$1.25/hour", (None, None, None, None)),
        ("competitive", (None, None, None, None)),
        ("USD 100k / EUR 90k", (None, None, None, None)),
    ],
)
def test_salary_only_unambiguous_numbers_no_period_or_currency_guess(
    raw, value, expected
):
    parsed = job(raw, f"Acme | Backend Engineer | Remote | {value}")
    assert (
        parsed.salary_min,
        parsed.salary_max,
        parsed.currency,
        parsed.salary_period,
    ) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "[deleted]",
        "[dead]",
        "Please specify your remote policy.",
        "Seeking work | Remote | Python",
        "Senior Engineer | For hire | Remote",
        "I am looking for a job as a software engineer.",
        "As a software engineer I wish companies would disclose pay.",
        "Thanks for posting!",
    ],
)
def test_noise_and_job_seekers_ignored(raw, text):
    assert parse_comment(dict(raw, text=text), thread_id=THREAD) is None


@pytest.mark.parametrize("flag", ["dead", "deleted"])
def test_dead_deleted_ignored(raw, flag):
    assert parse_comment(dict(raw, **{flag: True}), thread_id=THREAD) is None


@pytest.mark.parametrize("date", [None, "bad", "2026-10-01T10:00:00"])
def test_unknown_dates_not_fabricated(raw, date):
    parsed = job(dict(raw, created_at=date))
    assert parsed.published_at is None and parsed.collected_at.utcoffset() == timedelta(
        0
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", 1),
        ("title", "Who wants to be hired?"),
        ("author", "other"),
        ("type", "comment"),
        ("parent_id", 1),
        ("children", None),
        ("dead", True),
    ],
)
def test_invalid_thread_schema_fails(root, field, value):
    root[field] = value
    with pytest.raises(CollectionError):
        parse_thread(root, thread_id=THREAD, title=TITLE)


def test_schema_errors_sanitized_and_duplicates_not_inserted(root, caplog):
    first = root["children"][0]
    root["children"] = [{"id": "secret-id", "text": "private full body"}, first, first]
    jobs, report = parse_thread(root, thread_id=THREAD, title=TITLE)
    assert len(jobs) == 1 and report["ignored"] == 2
    assert "private" not in caplog.text and "secret-id" not in caplog.text
    root["children"] = [{"secret": "private"}]
    with pytest.raises(CollectionError):
        parse_thread(root, thread_id=THREAD, title=TITLE)


@pytest.fixture
def transport(monkeypatch):
    client_type = httpx.AsyncClient

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW if tz else NOW.replace(tzinfo=None)

    monkeypatch.setattr("src.collectors.hacker_news.datetime", Clock)

    def install(handler):
        factory = Mock(
            side_effect=lambda **kwargs: client_type(
                transport=httpx.MockTransport(handler), **kwargs
            )
        )
        monkeypatch.setattr("src.collectors.hacker_news.httpx.AsyncClient", factory)
        return factory

    return install


async def test_exactly_search_and_one_thread_request_no_recursive_reply_fetch(
    root, transport
):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            200,
            json=(
                {"hits": [hit()]}
                if request.url.path.endswith("search_by_date")
                else root
            ),
        )

    factory = transport(respond)
    collector = HackerNewsCollector(timeout=7)
    jobs = await collector.collect()
    assert (
        len(requests) == 2 and len(jobs) == 4 and collector.last_report["parsed"] == 4
    )
    query = requests[0].url.params
    assert query["tags"] == "story,author_whoishiring"
    assert query["query"] == "Ask HN: Who is hiring?" and query["hitsPerPage"] == "10"
    assert requests[1].url.path == f"/api/v1/items/{THREAD}"
    assert all("Authorization" not in request.headers for request in requests)
    assert (
        factory.call_args.kwargs["timeout"] == 7
        and not factory.call_args.kwargs["follow_redirects"]
    )


@pytest.mark.parametrize("status", [400, 401, 403, 404, 500, 503])
async def test_http_errors_sanitized(transport, status):
    transport(lambda request: httpx.Response(status, text="private response body"))
    with pytest.raises(CollectionError, match=f"Hacker News HTTP {status}") as caught:
        await HackerNewsCollector().collect()
    assert "private" not in str(caught.value)


@pytest.mark.parametrize("header", ["3600", "Wed, 16 Oct 2099 12:00:00 GMT", "invalid"])
async def test_retry_after_without_retry_loop(transport, header):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": header})

    transport(respond)
    with pytest.raises(CollectionError) as caught:
        await HackerNewsCollector().collect()
    assert len(calls) == 1 and (caught.value.retry_at is None) == (header == "invalid")


@pytest.mark.parametrize("error_type", [httpx.ReadTimeout, httpx.ConnectError])
async def test_network_failures_hide_request(transport, error_type):
    def respond(request):
        raise error_type("private query", request=request)

    transport(respond)
    with pytest.raises(CollectionError) as caught:
        await HackerNewsCollector().collect()
    assert "private" not in str(caught.value)


@pytest.mark.parametrize("compressed", [False, True])
async def test_bounded_decompressed_response(transport, monkeypatch, compressed):
    content = b"x" * 500
    transport(
        lambda request: httpx.Response(
            200,
            content=gzip.compress(content) if compressed else content,
            headers={"Content-Encoding": "gzip"} if compressed else {},
        )
    )
    monkeypatch.setattr(HackerNewsCollector, "max_response_bytes", 100)
    with pytest.raises(CollectionError, match="size limit"):
        await HackerNewsCollector().collect()


async def test_invalid_json(transport):
    transport(lambda request: httpx.Response(200, content=b"private-not-json"))
    with pytest.raises(CollectionError, match="invalid JSON"):
        await HackerNewsCollector().collect()


@pytest.mark.parametrize("language", ["en", "es"])
def test_shared_i18n_filters_and_attribution_source_neutral_score(raw, language):
    from src.bot.filters import render_screen
    from src.bot.formatter import build_job_keyboard, format_job_message
    from src.i18n import Language
    from src.schemas.filters import UserFilterDTO
    from src.services.scoring import ScoringService

    locale = Language(language)
    parsed = job(raw)
    score = ScoringService().calculate(parsed, UserFilterDTO())
    assert score == ScoringService().calculate(
        parsed.model_copy(update={"source": "the_muse"}), UserFilterDTO()
    )
    assert "Hacker News" in format_job_message(parsed, score, locale)
    assert (
        build_job_keyboard(1, parsed.url, locale)["inline_keyboard"][0][0]["url"]
        == parsed.url
    )
    _, markup = render_screen(UserFilterDTO(sources=["hacker_news"]), "sources", locale)
    assert any(
        button
        == {"text": "✅ Hacker News", "callback_data": "filters:sources:hacker_news"}
        for row in markup["inline_keyboard"]
        for button in row
    )


@pytest.mark.parametrize(
    "role",
    [
        "Account Executive",
        "Business Development",
        "Marketing",
        "Marketing Manager",
        "Growth",
        "Customer Support",
        "Customer Success Manager",
        "Recruiter",
        "Talent Acquisition",
        "HR",
        "Operations",
        "Operations Manager",
        "Finance",
        "Accountant",
        "Legal",
        "Project Manager",
        "Product Manager",
        "Designer",
        "Copywriter",
        "Content",
        "Data Analyst",
        "Analyst",
        "Consultant",
    ],
)
def test_generic_hiring_titles(raw, role):
    parsed = job(raw, f"Acme | Remote | {role}")
    assert parsed is not None and parsed.remote
    assert parsed.title == role


def test_unknown_profession_hiring_fallback_and_nontech_skills(raw):
    parsed = job(
        raw,
        "Acme | Remote | Ornithologist<p>We are hiring. "
        "Excel, Salesforce, Figma, UX Research and Accounting.",
    )
    assert parsed is not None and parsed.title == "Ornithologist"
    assert {"excel", "salesforce", "figma", "ux research", "accounting"} <= set(
        parsed.technologies
    )


def test_staff_accountant_does_not_inherit_it_seniority(raw):
    parsed = job(raw, "Acme | Remote | Staff Accountant")
    assert parsed.title == "Staff Accountant" and parsed.experience_level is None


@pytest.mark.parametrize(
    "text,title",
    [
        ("Acme | Remote | Sales | Account Executive", "Account Executive"),
        ("Company | Remote | Customer Success Manager", "Customer Success Manager"),
        ("Startup | Remote | Recruiter", "Recruiter"),
        ("Firm | Remote | Accountant", "Accountant"),
    ],
)
def test_prompt_nontech_hiring_examples(raw, text, title):
    parsed = job(raw, text)
    assert parsed is not None and parsed.remote and parsed.title == title
