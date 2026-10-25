"""One explicitly configured regional Jooble REST API; no job-page requests."""

import asyncio
import logging
from datetime import UTC, datetime
from hashlib import sha256
from urllib.parse import quote, urlsplit

import httpx
from redis.asyncio import Redis

from src.collectors.base import (
    BaseJobCollector,
    CollectionError,
    CollectorConfigurationError,
)
from src.collectors.http import fetch_json
from src.collectors.salary import parse_salary_text
from src.collectors.text import html_to_text
from src.schemas.job import JobDTO

logger = logging.getLogger(__name__)
JOOBLE_SEARCH_QUERIES = (
    "engineering",
    "design",
    "product",
    "sales",
    "marketing",
    "customer support",
    "finance",
    "operations",
    "human resources",
    "data",
)
REMOTE_LOCATIONS = {"remote", "remote job", "work from home"}


def _text(value: object) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def _identity(value: object) -> str:
    # The documented integer identifier is not documented as positive-only.
    if type(value) is int:
        return str(value)
    if isinstance(value, str) and value.isascii() and value.lstrip("-").isdigit():
        return str(int(value))
    raise ValueError("Missing Jooble job ID")


def _updated(value: object) -> datetime | None:
    if isinstance(value, str):
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
            # Jooble's example is naive. Do not invent a market/server timezone.
            return result.astimezone(UTC) if result.tzinfo else None
        except ValueError:
            pass
    return None


def parse_job(raw: dict, *, collected_at: datetime | None = None) -> JobDTO:
    if not isinstance(raw, dict):
        raise ValueError("Invalid Jooble job")
    identity = _identity(raw.get("id"))
    title = html_to_text(_text(raw.get("title")))
    url = _text(raw.get("link"))
    if not title or not url:
        raise ValueError("Missing Jooble title or listing link")
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError("Invalid Jooble listing link")
    location = html_to_text(_text(raw.get("location")))
    salary_text = html_to_text(_text(raw.get("salary")))
    salary = (
        parse_salary_text(salary_text, exact=True)
        if salary_text
        else (None, None, None, None)
    )
    return JobDTO(
        source="jooble",
        external_id=identity,
        title=title,
        company=html_to_text(_text(raw.get("company"))),
        description=html_to_text(_text(raw.get("snippet"))),
        url=url,
        location=location,
        remote=bool(location and location.casefold() in REMOTE_LOCATIONS),
        # A city/country is not an eligibility restriction; Remote is not global.
        remote_regions=[],
        employment_type=_text(raw.get("type")),
        salary_min=salary[0],
        salary_max=salary[1],
        currency=salary[2],
        salary_period=salary[3],
        technologies=[],
        experience_level=None,
        timezone_text=None,
        timezone_min_utc_offset=None,
        timezone_max_utc_offset=None,
        # Only the update timestamp is available, not original publication time.
        published_at=_updated(raw.get("updated")),
        collected_at=collected_at or datetime.now(UTC),
    )


def parse_page(payload: object) -> tuple[list[JobDTO], int]:
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise CollectionError("Jooble returned an invalid jobs page")
    total = payload.get("totalCount")
    if type(total) is not int or total < len(payload["jobs"]):
        raise CollectionError("Jooble returned an invalid result count")
    jobs, now = [], datetime.now(UTC)
    for raw in payload["jobs"]:
        try:
            jobs.append(parse_job(raw, collected_at=now))
        except (ValueError, TypeError):
            logger.warning("Jooble skipped malformed job item")
    if payload["jobs"] and not jobs:
        raise CollectionError("Jooble page has no valid jobs")
    return jobs, total


class JoobleCollector(BaseJobCollector):
    source_name = "jooble"
    max_response_bytes = 8 * 1024 * 1024
    page_size = 20
    search_queries = JOOBLE_SEARCH_QUERIES

    def __init__(
        self,
        *,
        timeout: float | None = None,
        max_pages: int | None = None,
        max_jobs: int | None = None,
        redis: Redis | None = None,
    ):
        from src.config import settings

        super().__init__(timeout=timeout)
        self._api_key = settings.JOOBLE_API_KEY
        self.api_domain = settings.JOOBLE_API_DOMAIN
        self.location = settings.JOOBLE_SEARCH_LOCATION
        self.redis = redis
        self.max_pages = (
            settings.JOOBLE_MAX_PAGES_PER_QUERY if max_pages is None else max_pages
        )
        self.max_jobs = (
            settings.JOOBLE_MAX_JOBS_PER_RUN if max_jobs is None else max_jobs
        )
        if type(self.max_pages) is not int or not 1 <= self.max_pages <= 3:
            raise ValueError("max_pages must be an integer from 1 to 3")
        if type(self.max_jobs) is not int or not 1 <= self.max_jobs <= 200:
            raise ValueError("max_jobs must be an integer from 1 to 200")
        self.last_report: dict = {}
        self.query_job_ids: dict[str, list[str]] = {}

    @property
    def rotation_key(self) -> str:
        market = sha256((self.location or "").casefold().encode()).hexdigest()[:16]
        return f"collector:jooble:query_rotation:{self.api_domain}:{market}"

    async def _next_query(self) -> str:
        if self.redis is None:
            raise CollectorConfigurationError("Jooble requires Redis rotation state")
        # Atomic and persistent. The collection service holds the source lock;
        # only queries actually started consume a rotation slot.
        position = await self.redis.incr(self.rotation_key)
        return self.search_queries[(position - 1) % len(self.search_queries)]

    async def collect(self) -> list[JobDTO]:
        self.last_report = {}
        self.query_job_ids = {}
        for name, value in (
            ("JOOBLE_API_KEY", self._api_key),
            ("JOOBLE_API_DOMAIN", self.api_domain),
            ("JOOBLE_SEARCH_LOCATION", self.location),
        ):
            if not value:
                raise CollectorConfigurationError(f"Jooble requires {name}")
        if self.redis is None:
            raise CollectorConfigurationError("Jooble requires Redis rotation state")
        url = f"https://{self.api_domain}/api/{quote(self._api_key, safe='')}"
        jobs, seen, finished = [], set(), set()
        query_seen, counters, active_queries = {}, {}, []
        # Preserve the current single-query request budget, even though the
        # vocabulary now has ten professions. Never run ten searches per cycle.
        request_budget = self.max_pages
        query_slots = min(2, request_budget)
        async with httpx.AsyncClient(
            timeout=self.timeout, headers=self.request_headers, follow_redirects=False
        ) as client:
            # Round-robin pages keep the first query from monopolizing the run cap.
            requests = 0
            for page in range(1, self.max_pages + 1):
                for slot in range(query_slots):
                    if requests >= request_budget or len(jobs) >= self.max_jobs:
                        break
                    if slot >= len(active_queries):
                        if page != 1:
                            continue
                        query = await self._next_query()
                        active_queries.append(query)
                        query_seen[query] = set()
                        self.query_job_ids[query] = []
                        counters[query] = dict(
                            query=query, requests=0, received=0, unique=0, contributed=0
                        )
                    query = active_queries[slot]
                    if query in finished or len(jobs) >= self.max_jobs:
                        continue
                    if requests:
                        await asyncio.sleep(1)
                    requests += 1
                    counters[query]["requests"] += 1
                    try:
                        payload = await fetch_json(
                            client,
                            url,
                            source="Jooble",
                            params={},
                            method="POST",
                            json_body={
                                "keywords": query,
                                "location": self.location,
                                "page": page,
                                "ResultOnPage": self.page_size,
                                "companysearch": False,
                            },
                            max_response_bytes=self.max_response_bytes,
                        )
                    except CollectionError as exc:
                        if str(exc) in {"Jooble HTTP 401", "Jooble HTTP 403"}:
                            raise CollectionError(
                                "Jooble access denied (HTTP 401/403); check "
                                "JOOBLE_API_KEY, regional domain and quota"
                            ) from None
                        raise
                    batch, total = parse_page(payload)
                    counters[query]["received"] += len(payload["jobs"])
                    progress = 0
                    for job in batch:
                        if job.external_id not in query_seen[query]:
                            query_seen[query].add(job.external_id)
                            self.query_job_ids[query].append(job.external_id)
                            progress += 1
                        if job.external_id not in seen and len(jobs) < self.max_jobs:
                            seen.add(job.external_id)
                            jobs.append(job)
                            counters[query]["contributed"] += 1
                    counters[query]["unique"] = len(query_seen[query])
                    if (
                        not progress
                        or len(payload["jobs"]) < self.page_size
                        or page * self.page_size >= total
                    ):
                        finished.add(query)
        self.last_report = {
            "domain": self.api_domain,
            "location": self.location,
            "queries": list(counters.values()),
            "queries_executed": sum(row["requests"] > 0 for row in counters.values()),
            "api_results_received": sum(row["received"] for row in counters.values()),
            "unique_jobs": len(jobs),
        }
        logger.info("Jooble collection: %s", self.last_report)
        return jobs
