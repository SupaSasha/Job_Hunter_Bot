"""Bounded collection from The Muse's official public jobs API."""

import asyncio
import logging
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx

from src.collectors.base import BaseJobCollector, CollectionError
from src.collectors.http import fetch_json
from src.collectors.text import html_to_text
from src.schemas.job import JobDTO

logger = logging.getLogger(__name__)
REMOTE_LOCATION = "Flexible / Remote"


def _text(value: object) -> str | None:
    return (value.strip() or None) if isinstance(value, str) else None


def _names(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(
        dict.fromkeys(
            name
            for item in value
            if isinstance(item, dict) and (name := _text(item.get("name")))
        )
    )


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
        raise ValueError("Invalid The Muse job")
    identity = raw.get("id")
    if not (
        (type(identity) is int and identity > 0)
        or (
            isinstance(identity, str)
            and identity.isascii()
            and identity.isdigit()
            and int(identity) > 0
        )
    ):
        raise ValueError("Missing positive The Muse job ID")
    title = html_to_text(_text(raw.get("name")))
    refs = raw.get("refs")
    url = _text(refs.get("landing_page")) if isinstance(refs, dict) else None
    if not title or not url:
        raise ValueError("Missing job title or listing URL")
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc.lower() not in {"www.themuse.com", "themuse.com"}
        or len(parsed.path.strip("/").split("/")) < 3
        or not parsed.path.startswith("/jobs/")
    ):
        raise ValueError("Missing canonical The Muse vacancy URL")
    company = raw.get("company")
    locations = _names(raw.get("locations"))
    levels = _names(raw.get("levels"))
    return JobDTO(
        source="the_muse",
        external_id=str(int(identity)),
        title=title,
        company=(
            html_to_text(_text(company.get("name")))
            if isinstance(company, dict)
            else None
        ),
        description=html_to_text(_text(raw.get("contents"))),
        url=url,
        location=", ".join(locations) or None,
        # The legacy DTO has no nullable remote value. False also covers unknown.
        remote=any(name.casefold() == REMOTE_LOCATION.casefold() for name in locations),
        # City names and the flexible/remote label do not establish eligibility.
        remote_regions=[],
        employment_type=None,
        salary_min=None,
        salary_max=None,
        currency=None,
        salary_period=None,
        # Categories and observed employer-brand tags are not technical skills.
        technologies=[],
        experience_level=", ".join(levels) or None,
        timezone_text=None,
        timezone_min_utc_offset=None,
        timezone_max_utc_offset=None,
        published_at=_published(raw.get("publication_date")),
        collected_at=collected_at or datetime.now(UTC),
    )


def parse_page(payload: object, *, page: int) -> tuple[list[JobDTO], bool]:
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise CollectionError("The Muse returned an invalid jobs page")
    current, count = payload.get("page"), payload.get("page_count")
    if (
        type(current) is not int
        or current != page
        or type(count) is not int
        or count < 0
        or (payload["results"] and current >= count)
    ):
        raise CollectionError("The Muse returned invalid pagination")
    if payload.get("timed_out") is True:
        raise CollectionError("The Muse search timed out")
    jobs, now = [], datetime.now(UTC)
    for item in payload["results"]:
        try:
            jobs.append(parse_job(item, collected_at=now))
        except (ValueError, TypeError):
            logger.warning("The Muse skipped malformed job item")
    if payload["results"] and not jobs:
        raise CollectionError("The Muse page has no valid jobs")
    return jobs, current + 1 < count


class TheMuseCollector(BaseJobCollector):
    source_name = "the_muse"
    api_url = "https://www.themuse.com/api/public/jobs"
    max_response_bytes = 8 * 1024 * 1024

    def __init__(self, *, timeout: float | None = None, max_pages: int | None = None):
        from src.config import settings

        super().__init__(timeout=timeout)
        self.max_pages = settings.THE_MUSE_MAX_PAGES if max_pages is None else max_pages
        if type(self.max_pages) is not int or not 1 <= self.max_pages <= 5:
            raise ValueError("max_pages must be an integer from 1 to 5")
        self._api_key = settings.THE_MUSE_API_KEY

    async def collect(self) -> list[JobDTO]:
        from src.config import settings

        if settings.MODE == "PROD" and not self._api_key:
            raise CollectionError(
                "The Muse requires a registered THE_MUSE_API_KEY in production"
            )
        jobs, seen = [], set()
        async with httpx.AsyncClient(
            timeout=self.timeout, headers=self.request_headers, follow_redirects=False
        ) as client:
            for page in range(self.max_pages):
                params = {
                    "page": str(page),
                    "descending": "true",
                    "location": REMOTE_LOCATION,
                }
                if self._api_key:
                    params["api_key"] = self._api_key
                try:
                    payload = await fetch_json(
                        client,
                        self.api_url,
                        source="The Muse",
                        params=params,
                        max_response_bytes=self.max_response_bytes,
                    )
                except CollectionError as exc:
                    if str(exc) in {"The Muse HTTP 401", "The Muse HTTP 403"}:
                        raise CollectionError(
                            "The Muse access denied (HTTP 401/403); check registered "
                            "THE_MUSE_API_KEY and API quota"
                        ) from None
                    raise
                batch, has_more = parse_page(payload, page=page)
                added = 0
                for job in batch:
                    if job.external_id not in seen:
                        jobs.append(job)
                        seen.add(job.external_id)
                        added += 1
                if not batch or not added or not has_more:
                    break
                if page + 1 < self.max_pages:
                    await asyncio.sleep(1)
        logger.info("The Muse collected %s jobs", len(jobs))
        return jobs
