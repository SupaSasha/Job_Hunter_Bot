"""Himalayas' official, bounded remote-jobs JSON feed."""

import logging
import math
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

import httpx

from src.collectors.base import BaseJobCollector, CollectionError
from src.collectors.pagination import collect_cursor_pages
from src.collectors.skills import technical_categories
from src.collectors.text import html_to_text
from src.schemas.job import JobDTO

logger = logging.getLogger(__name__)


def _text(value: object) -> str | None:
    return (value.strip() or None) if isinstance(value, str) else None


def _strings(value: object) -> list[str]:
    return (
        list(dict.fromkeys(item.strip() for item in value if _text(item)))
        if isinstance(value, list)
        else []
    )


def _published(value: object) -> datetime | None:
    try:
        if type(value) in (int, float):
            # The current response uses seconds; OpenAPI also documents millis.
            return datetime.fromtimestamp(
                value / 1000 if abs(value) >= 10**11 else value, UTC
            )
        if isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.astimezone(UTC) if parsed.tzinfo else None
    except (ValueError, OverflowError, OSError):
        pass
    return None


def _salary(value: object) -> int | None:
    if (
        type(value) in (int, float)
        and math.isfinite(value)
        and value >= 0
        and int(value) == value
    ):
        return int(value)
    return None


def _timezone_text(value: object) -> str | None:
    if not isinstance(value, list):
        return None
    labels = []
    for item in value:
        if type(item) not in (str, int, float):
            continue
        try:
            offset = Decimal(str(item))
        except InvalidOperation:
            label = _text(item)
        else:
            if not offset.is_finite() or not -12 <= offset <= 14:
                continue
            minutes = abs(offset * 60)
            if minutes != minutes.to_integral_value():
                label = f"UTC offset {offset}"
            else:
                hours, minute = divmod(int(minutes), 60)
                sign = "-" if offset < 0 else "+"
                label = f"UTC{sign}{hours}" + (f":{minute:02}" if minute else "")
        if label and label not in labels:
            labels.append(label)
    return "UTC offsets: [" + ", ".join(labels) + "]" if labels else None


def parse_job(raw: dict, *, collected_at: datetime | None = None) -> JobDTO:
    if not isinstance(raw, dict):
        raise ValueError("Invalid Himalayas job")
    job_id, title, url = (
        _text(raw.get(key)) for key in ("guid", "title", "applicationLink")
    )
    if not job_id or not title or not url:
        raise ValueError("Missing job identity, title or URL")
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc.lower() != "himalayas.app"
        or not parsed.path.startswith("/companies/")
        or "/jobs/" not in parsed.path
        or not parsed.path.rsplit("/jobs/", 1)[1]
    ):
        raise ValueError("Missing canonical Himalayas job URL")

    restrictions = raw.get("locationRestrictions")
    regions = []
    if isinstance(restrictions, list):
        for entry in restrictions:
            name = _text(entry.get("name")) if isinstance(entry, dict) else _text(entry)
            if name and name not in regions:
                regions.append(name)
        # An explicit empty array is documented as worldwide; absent is unknown.
        if not restrictions:
            regions = ["Worldwide"]
    seniority = _strings(raw.get("seniority"))
    return JobDTO(
        source="himalayas",
        external_id=job_id,
        title=title,
        company=_text(raw.get("companyName")),
        description=html_to_text(_text(raw.get("description"))),
        url=url,
        remote=True,
        location=", ".join(regions) or None,
        remote_regions=regions,
        employment_type=_text(raw.get("employmentType")),
        experience_level=", ".join(seniority) or None,
        salary_min=_salary(raw.get("minSalary")),
        salary_max=_salary(raw.get("maxSalary")),
        currency=_text(raw.get("currency")),
        salary_period=_text(raw.get("salaryPeriod")),
        technologies=technical_categories(
            _strings(raw.get("categories")), role_labels=True
        ),
        timezone_text=_timezone_text(raw.get("timezoneRestrictions")),
        published_at=_published(raw.get("pubDate")),
        collected_at=collected_at or datetime.now(UTC),
    )


def parse_page(payload: object) -> tuple[list[JobDTO], str | None]:
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise CollectionError("Himalayas returned an invalid jobs page")
    cursor = payload.get("nextCursor")
    if cursor is not None and (not isinstance(cursor, str) or len(cursor) > 2048):
        raise CollectionError("Himalayas returned invalid pagination")
    jobs, now = [], datetime.now(UTC)
    for raw in payload["jobs"]:
        try:
            jobs.append(parse_job(raw, collected_at=now))
        except (ValueError, TypeError):
            logger.warning("Himalayas skipped malformed job item")
    if payload["jobs"] and not jobs:
        raise CollectionError("Himalayas page has no valid jobs")
    return jobs, cursor or None


class HimalayasCollector(BaseJobCollector):
    source_name = "himalayas"
    api_url = "https://himalayas.app/jobs/api"
    max_response_bytes = 8 * 1024 * 1024

    def __init__(
        self,
        *,
        timeout: float | None = None,
        max_pages: int | None = None,
        api_key: str | None = None,
    ):
        from src.config import settings

        super().__init__(timeout=timeout)
        self.max_pages = (
            settings.HIMALAYAS_MAX_PAGES if max_pages is None else max_pages
        )
        if type(self.max_pages) is not int or not 1 <= self.max_pages <= 5:
            raise ValueError("max_pages must be an integer from 1 to 5")
        self._api_key = settings.HIMALAYAS_API_KEY if api_key is None else api_key

    @property
    def request_headers(self) -> dict[str, str]:
        headers = super().request_headers
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    async def collect(self) -> list[JobDTO]:
        async with httpx.AsyncClient(
            timeout=self.timeout, headers=self.request_headers, follow_redirects=False
        ) as client:
            jobs = await collect_cursor_pages(
                client,
                self.api_url,
                source="Himalayas",
                params={"limit": "20"},
                parser=parse_page,
                max_pages=self.max_pages,
                max_response_bytes=self.max_response_bytes,
            )
        logger.info("Himalayas collected %s jobs", len(jobs))
        return jobs
