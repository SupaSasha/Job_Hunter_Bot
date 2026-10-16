"""We Work Remotely's official public RSS, without job-page scraping."""

import logging
import re
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit, urlunsplit
from xml.etree import ElementTree as ET

import httpx

from src.collectors.base import BaseJobCollector, CollectionError
from src.collectors.skills import technical_categories
from src.collectors.text import html_to_text
from src.schemas.job import JobDTO

logger = logging.getLogger(__name__)


def _date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        result = parsedate_to_datetime(value)
        return result.astimezone(UTC) if result.tzinfo else None
    except (ValueError, TypeError, OverflowError):
        return None


def _job_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme not in {"https", "http"}
        or parsed.netloc.lower() != "weworkremotely.com"
        or not parsed.path.startswith("/remote-jobs/")
        or not parsed.path.removeprefix("/remote-jobs/").strip("/")
    ):
        raise ValueError("Missing valid WWR job URL")
    return urlunsplit(("https", "weworkremotely.com", parsed.path.rstrip("/"), "", ""))


def parse_job_item(item: ET.Element, *, collected_at: datetime | None = None) -> JobDTO:
    def field(name):
        return (item.findtext(name) or "").strip()

    raw_title = field("title")
    company, separator, title = raw_title.partition(": ")
    if not separator:
        company, title = "", raw_title
    if not title.strip():
        raise ValueError("Missing job title")
    url = _job_url(field("link") or field("guid"))
    guid = field("guid")
    if guid.startswith(("http://", "https://")):
        # WWR currently publishes the job permalink as its GUID.
        external_id = _job_url(guid)
    else:
        external_id = guid or url

    countries = [
        re.sub(r"^(?:and\s+|[\U0001F1E6-\U0001F1FF]\s*)+", "", part.strip()).strip()
        for part in field("country").split(",")
        if part.strip()
    ]
    region = field("region")
    # Explicit country restrictions take precedence over a generic world label.
    regions = countries or (
        ["Worldwide" if region == "Anywhere in the World" else region] if region else []
    )
    skills = re.split(r",|\s+and\s+", field("skills"))
    categories = [(node.text or "").strip() for node in item.findall("category")]
    technologies = technical_categories([*skills, *categories])
    return JobDTO(
        source="weworkremotely",
        external_id=external_id,
        title=title.strip(),
        company=company.strip() or None,
        description=html_to_text(field("description")),
        url=url,
        location=", ".join(countries) if countries else region or None,
        remote=True,
        remote_regions=regions,
        technologies=technologies,
        employment_type=field("type") or None,
        published_at=_date(field("pubDate")),
        collected_at=collected_at or datetime.now(UTC),
    )


def parse_feed(content: bytes) -> list[JobDTO]:
    if len(content) > WeWorkRemotelyCollector.max_response_bytes:
        raise CollectionError("WWR feed exceeds size limit")
    if b"<!DOCTYPE" in content.upper() or b"<!ENTITY" in content.upper():
        raise CollectionError("WWR feed contains unsupported XML declarations")
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        raise CollectionError("WWR returned invalid XML") from None
    channel = root.find("channel")
    if root.tag != "rss" or channel is None:
        raise CollectionError("WWR returned an unexpected feed")
    items = channel.findall("item")
    jobs = []
    collected_at = datetime.now(UTC)
    for item in items:
        try:
            jobs.append(parse_job_item(item, collected_at=collected_at))
        except (ValueError, TypeError):
            logger.warning("WWR skipped malformed job item")
    if items and not jobs:
        raise CollectionError("WWR feed has no valid job items")
    return jobs


class WeWorkRemotelyCollector(BaseJobCollector):
    source_name = "weworkremotely"
    feed_url = "https://weworkremotely.com/remote-jobs.rss"
    max_response_bytes = 8 * 1024 * 1024

    async def collect(self) -> list[JobDTO]:
        headers = {
            **self.request_headers,
            "Accept": "application/rss+xml,application/xml",
        }
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout, headers=headers, follow_redirects=True
            ) as client:
                async with client.stream("GET", self.feed_url) as response:
                    if response.status_code == 429:
                        value = response.headers.get("Retry-After", "")
                        retry_at = _date(value)
                        if value.isdigit():
                            try:
                                retry_at = datetime.now(UTC) + timedelta(
                                    seconds=int(value)
                                )
                            except OverflowError:
                                retry_at = datetime.max.replace(tzinfo=UTC)
                        raise CollectionError(
                            "WWR HTTP 429 rate limited", retry_at=retry_at
                        )
                    response.raise_for_status()
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > self.max_response_bytes:
                            raise CollectionError("WWR feed exceeds size limit")
        except httpx.TimeoutException:
            raise CollectionError("WWR request timed out") from None
        except httpx.HTTPStatusError as exc:
            raise CollectionError(f"WWR HTTP {exc.response.status_code}") from None
        except httpx.HTTPError:
            raise CollectionError("WWR network request failed") from None
        jobs = parse_feed(bytes(content))
        logger.info("WWR collected %s jobs", len(jobs))
        return jobs


async def main() -> None:
    try:
        jobs = await WeWorkRemotelyCollector().collect()
    except CollectionError as exc:
        print(str(exc))
        raise SystemExit(1) from None
    print(f"received: {len(jobs)}")
    for job in jobs[:3]:
        region = ", ".join(job.remote_regions) or "Unknown"
        print(f"[We Work Remotely] {job.title} — {job.company or 'Unknown'} — {region}")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
