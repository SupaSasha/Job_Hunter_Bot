from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from xml.etree import ElementTree as ET

import httpx
import pytest

from src.collectors.base import CollectionError
from src.collectors.weworkremotely import (
    WeWorkRemotelyCollector,
    parse_feed,
    parse_job_item,
)

ITEM = """<item>
<title>Acme: Python Backend Developer</title>
<link>https://weworkremotely.com/remote-jobs/acme-python?source=rss</link>
<guid>https://weworkremotely.com/remote-jobs/acme-python</guid>
<region>Anywhere in the World</region><country/><state>California</state>
<skills>Django and Python, PostgreSQL, and Docker</skills>
<category>Back-End Programming</category><category>Sales and Marketing</category>
<type>Full-Time</type>
<description><![CDATA[<p>Build <strong>APIs</strong> &amp; tools.</p>
<script>ignore me</script><style>ignore me too</style>
<p>Redis in prose only.</p>]]></description>
<pubDate>Mon, 28 Sep 2026 09:00:00 -0300</pubDate>
</item>"""
FEED = (
    f'<?xml version="1.0"?><rss version="2.0"><channel>{ITEM}</channel></rss>'.encode()
)


def test_real_feed_shape_maps_existing_dto():
    job = parse_feed(FEED)[0]
    assert job.source == "weworkremotely"
    assert job.external_id == "https://weworkremotely.com/remote-jobs/acme-python"
    assert job.url == job.external_id
    assert job.title == "Python Backend Developer" and job.company == "Acme"
    assert job.description == "Build APIs & tools.\nRedis in prose only."
    assert job.published_at == datetime(2026, 9, 28, 12, tzinfo=UTC)
    assert job.collected_at.tzinfo == UTC
    assert job.remote is True and job.remote_regions == ["Worldwide"]
    assert job.location == "Anywhere in the World"
    assert job.technologies == [
        "Django",
        "Python",
        "PostgreSQL",
        "Docker",
    ]
    assert job.employment_type == "Full-Time"
    for field in (
        "salary_min",
        "salary_max",
        "currency",
        "salary_period",
        "experience_level",
        "timezone_text",
        "timezone_min_utc_offset",
        "timezone_max_utc_offset",
    ):
        assert getattr(job, field) is None


def test_optional_fields_and_title_without_company_prefix():
    job = parse_job_item(ET.fromstring("""<item><title>Engineer</title>
        <link>https://weworkremotely.com/remote-jobs/engineer</link></item>"""))
    assert job.company is None and job.description is None
    assert job.remote_regions == job.technologies == []
    assert job.published_at is None and job.employment_type is None
    assert job.external_id == job.url and job.remote is True


def test_explicit_countries_override_worldwide_without_using_headquarters():
    item = ET.fromstring(
        ITEM.replace("<country/>", "<country>🇺🇸 United States, and 🇨🇦 Canada</country>")
    )
    job = parse_job_item(item)
    assert job.remote_regions == ["United States", "Canada"]
    assert job.location == "United States, Canada"
    assert "Worldwide" not in job.remote_regions and "California" not in job.location


@pytest.mark.parametrize(
    "region", ["USA Only", "Latin America", "Europe", "North America Only"]
)
def test_explicit_regions_preserved(region):
    job = parse_job_item(ET.fromstring(ITEM.replace("Anywhere in the World", region)))
    assert job.remote_regions == [region]


def test_guid_is_used_as_id_and_link_fallback():
    item = ET.fromstring(ITEM)
    item.remove(item.find("link"))
    assert parse_job_item(item).url.endswith("/acme-python")
    item.find("guid").text = "stable-source-id"
    with pytest.raises(ValueError):
        parse_job_item(item)
    ET.SubElement(item, "link").text = (
        "https://weworkremotely.com/remote-jobs/acme-python"
    )
    assert parse_job_item(item).external_id == "stable-source-id"


@pytest.mark.parametrize("date", ["not a date", "", "Mon, 28 Sep 2026 12:00:00"])
def test_invalid_or_naive_date_is_unknown(date):
    item = ET.fromstring(ITEM)
    item.find("pubDate").text = date
    assert parse_job_item(item).published_at is None


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "https://example.com/job",
        "https://weworkremotely.com/remote-jobs/",
    ],
)
def test_invalid_url_is_rejected(url):
    item = ET.fromstring(ITEM)
    item.find("link").text = url
    with pytest.raises(ValueError):
        parse_job_item(item)


@pytest.mark.parametrize(
    "body",
    [
        b"not xml",
        b"<html/>",
        b"<rss/>",
        b'<!DOCTYPE rss [<!ENTITY a "text">]><rss><channel/></rss>',
        b"<rss><channel><item><title>No link</title></item></channel></rss>",
    ],
)
def test_bad_feed_is_failure_not_successful_empty_batch(body):
    with pytest.raises(CollectionError):
        parse_feed(body)


def test_empty_feed_and_mixed_malformed_items():
    assert parse_feed(b"<rss><channel/></rss>") == []
    mixed = FEED.replace(b"</channel>", b"<item><title>Broken</title></item></channel>")
    assert len(parse_feed(mixed)) == 1


@pytest.fixture
def transport(monkeypatch):
    def install(response_handler):
        client = httpx.AsyncClient(transport=httpx.MockTransport(response_handler))
        factory = Mock(return_value=client)
        monkeypatch.setattr("src.collectors.weworkremotely.httpx.AsyncClient", factory)
        return factory

    return install


async def test_http_collect_sets_headers_timeout_and_parses(transport):
    requests = []

    def response(request):
        requests.append(request)
        return httpx.Response(200, content=FEED)

    factory = transport(response)
    jobs = await WeWorkRemotelyCollector(timeout=12).collect()
    assert len(jobs) == 1 and len(requests) == 1
    assert str(requests[0].url) == WeWorkRemotelyCollector.feed_url
    kwargs = factory.call_args.kwargs
    assert kwargs["timeout"] == 12
    assert kwargs["headers"]["User-Agent"].startswith("JobHunterBot/")
    assert "application/rss+xml" in kwargs["headers"]["Accept"]


@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_http_failure_is_not_retried(transport, status):
    calls = []

    def response(request):
        calls.append(request)
        return httpx.Response(status, headers={"Retry-After": "7200"})

    transport(response)
    before = datetime.now(UTC)
    with pytest.raises(CollectionError, match=str(status)) as exc:
        await WeWorkRemotelyCollector().collect()
    assert len(calls) == 1
    if status == 429:
        assert exc.value.retry_at >= before + timedelta(hours=2)


async def test_retry_after_http_date(transport):
    transport(
        lambda _: httpx.Response(
            429, headers={"Retry-After": "Tue, 29 Sep 2026 12:00:00 GMT"}
        )
    )
    with pytest.raises(CollectionError) as exc:
        await WeWorkRemotelyCollector().collect()
    assert exc.value.retry_at == datetime(2026, 9, 29, 12, tzinfo=UTC)


@pytest.mark.parametrize("error", [httpx.ReadTimeout, httpx.ConnectError])
async def test_network_failure_is_sanitized(transport, error):
    def response(request):
        raise error("private transport details", request=request)

    transport(response)
    with pytest.raises(CollectionError) as exc:
        await WeWorkRemotelyCollector().collect()
    assert "private transport" not in str(exc.value)


async def test_feed_size_limit(transport, monkeypatch):
    monkeypatch.setattr(WeWorkRemotelyCollector, "max_response_bytes", 32)
    transport(lambda _: httpx.Response(200, content=FEED))
    with pytest.raises(CollectionError, match="size limit"):
        await WeWorkRemotelyCollector().collect()


def test_nontech_structured_skills_survive_profession_categories():
    item = ITEM.replace(
        "Django and Python, PostgreSQL, and Docker",
        "Figma, UX Research, Excel, Salesforce, Accounting, Communication",
    )
    job = parse_feed(f"<rss><channel>{item}</channel></rss>".encode())[0]
    assert job.technologies == [
        "Figma",
        "UX Research",
        "Excel",
        "Salesforce",
        "Accounting",
    ]
