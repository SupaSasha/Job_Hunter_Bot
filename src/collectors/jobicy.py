"""Bounded collection from Jobicy's official public JSON jobs feed."""

import logging
import math
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx

from src.collectors.base import BaseJobCollector, CollectionError
from src.collectors.pagination import collect_cursor_pages
from src.collectors.text import html_to_text
from src.schemas.job import JobDTO

logger = logging.getLogger(__name__)


def _text(value: object) -> str | None:
    return (value.strip() or None) if isinstance(value, str) else None


def _identity(value: object) -> str:
    if type(value) is int and value > 0:
        return str(value)
    if (
        isinstance(value, str)
        and value.isascii()
        and value.isdigit()
        and int(value) > 0
    ):
        return str(int(value))
    raise ValueError("Missing positive Jobicy job ID")


def _salary(value: object) -> int | None:
    if type(value) is int:
        return value if value >= 0 else None
    if (
        type(value) is float
        and math.isfinite(value)
        and value >= 0
        and value.is_integer()
    ):
        return int(value)
    return None


def _published(value: object) -> datetime | None:
    if isinstance(value, str):
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return result.astimezone(UTC) if result.tzinfo else None
        except ValueError:
            pass
    return None


def parse_job(raw: dict, *, collected_at: datetime | None = None) -> JobDTO:
    if not isinstance(raw, dict):
        raise ValueError("Invalid Jobicy job")
    external_id = _identity(raw.get("id"))
    title = html_to_text(_text(raw.get("jobTitle")))
    url = _text(raw.get("url"))
    if not title or not url:
        raise ValueError("Missing job title or URL")
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc.lower() != "jobicy.com"
        or not parsed.path.startswith("/jobs/")
        or not parsed.path.removeprefix("/jobs/").strip("/")
    ):
        raise ValueError("Missing canonical Jobicy vacancy URL")
    location = html_to_text(_text(raw.get("jobGeo")))
    regions = (
        list(
            dict.fromkeys(
                value.strip() for value in location.split(",") if value.strip()
            )
        )
        if location
        else []
    )
    types = raw.get("jobType")
    types = (
        list(dict.fromkeys(value.strip() for value in types if _text(value)))
        if isinstance(types, list)
        else []
    )
    return JobDTO(
        source="jobicy",
        external_id=external_id,
        title=title,
        company=html_to_text(_text(raw.get("companyName"))),
        description=html_to_text(_text(raw.get("jobDescription"))),
        url=url,
        location=location,
        remote=True,
        remote_regions=regions,
        employment_type=", ".join(types) or None,
        experience_level=_text(raw.get("jobLevel")),
        salary_min=_salary(raw.get("salaryMin")),
        salary_max=_salary(raw.get("salaryMax")),
        currency=_text(raw.get("salaryCurrency")),
        salary_period=_text(raw.get("salaryPeriod")),
        # jobIndustry is a category, not a structured technology/skill list.
        technologies=[],
        timezone_text=None,
        timezone_min_utc_offset=None,
        timezone_max_utc_offset=None,
        published_at=_published(raw.get("pubDate")),
        collected_at=collected_at or datetime.now(UTC),
    )


def parse_page(payload: object) -> tuple[list[JobDTO], str | None]:
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise CollectionError("Jobicy returned an invalid jobs page")
    if payload.get("success") is False or payload.get("statusCode", 200) != 200:
        raise CollectionError("Jobicy returned an unsuccessful jobs page")
    count = payload.get("jobCount")
    if count is not None and (type(count) is not int or count != len(payload["jobs"])):
        raise CollectionError("Jobicy returned invalid job count")
    cursor, has_more = payload.get("nextCursor"), payload.get("hasMore")
    if cursor is not None and (
        not isinstance(cursor, str) or not cursor or len(cursor) > 2048
    ):
        raise CollectionError("Jobicy returned invalid pagination")
    if has_more is not None and (
        type(has_more) is not bool or has_more != (cursor is not None)
    ):
        raise CollectionError("Jobicy returned inconsistent pagination")
    jobs, now = [], datetime.now(UTC)
    for item in payload["jobs"]:
        try:
            jobs.append(parse_job(item, collected_at=now))
        except (ValueError, TypeError):
            logger.warning("Jobicy skipped malformed job item")
    if payload["jobs"] and not jobs:
        raise CollectionError("Jobicy page has no valid jobs")
    return jobs, cursor


class JobicyCollector(BaseJobCollector):
    source_name = "jobicy"
    api_url = "https://jobicy.com/api/v2/remote-jobs"
    max_response_bytes = 8 * 1024 * 1024

    def __init__(
        self,
        *,
        timeout: float | None = None,
        max_pages: int | None = None,
        count: int = 50,
    ):
        from src.config import settings

        super().__init__(timeout=timeout)
        self.max_pages = settings.JOBICY_MAX_PAGES if max_pages is None else max_pages
        if type(self.max_pages) is not int or not 1 <= self.max_pages <= 5:
            raise ValueError("max_pages must be an integer from 1 to 5")
        if type(count) is not int or not 1 <= count <= 200:
            raise ValueError("count must be an integer from 1 to 200")
        self.count = count

    async def collect(self) -> list[JobDTO]:
        async with httpx.AsyncClient(
            timeout=self.timeout, headers=self.request_headers, follow_redirects=False
        ) as client:
            jobs = await collect_cursor_pages(
                client,
                self.api_url,
                source="Jobicy",
                params={"count": str(self.count)},
                parser=parse_page,
                max_pages=self.max_pages,
                max_response_bytes=self.max_response_bytes,
            )
        logger.info("Jobicy collected %s jobs", len(jobs))
        return jobs
