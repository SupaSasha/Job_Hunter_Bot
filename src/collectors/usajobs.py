"""Bounded USAJOBS search; no details requests or source-specific business rules."""

import asyncio
import logging
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import httpx

from src.collectors.base import (
    BaseJobCollector,
    CollectionError,
    CollectorConfigurationError,
)
from src.collectors.http import fetch_json
from src.collectors.text import html_to_text
from src.logging_filters import install_network_log_filter
from src.schemas.job import JobDTO

logger = logging.getLogger(__name__)
SEARCH_URL = "https://data.usajobs.gov/api/Search"
USAJOBS_CATEGORIES = ("2210",)  # Official Information Technology Management series.
REMOTE_LOCATION = "anywhere in the u.s. (remote job)"
REMOTE_US_LOCATIONS = {REMOTE_LOCATION, f"{REMOTE_LOCATION}, united states"}
EASTERN = ZoneInfo("America/New_York")


def _text(value: object) -> str | None:
    return html_to_text(value) if isinstance(value, str) and value.strip() else None


def _list(value: object) -> list:
    return value if isinstance(value, list) else []


def _date(value: object) -> datetime | None:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return None


def _closed(value: object, now: datetime) -> bool:
    close = _date(value)
    if close is None:
        return False
    if close.tzinfo is not None:
        return close.astimezone(UTC) < now
    # USAJOBS defines calendar closing dates as the end of that date in ET.
    # Midnight/date-only values encode that date, not a deadline at its start.
    if close.time() == time():
        end = datetime.combine(close.date() + timedelta(days=1), time(), EASTERN)
        return end.astimezone(UTC) <= now
    # No documented timezone for arbitrary naive instants: avoid premature expiry.
    return False


def _details(descriptor: dict) -> dict:
    area = descriptor.get("UserArea")
    details = area.get("Details") if isinstance(area, dict) else None
    return details if isinstance(details, dict) else {}


def _locations(descriptor: dict) -> list[str]:
    values = [
        _text(row.get("LocationName"))
        for row in _list(descriptor.get("PositionLocation"))
        if isinstance(row, dict)
    ]
    values = list(dict.fromkeys(value for value in values if value))
    if not values and (display := _text(descriptor.get("PositionLocationDisplay"))):
        values = [display]
    return values


def _boolean(value: object) -> bool | None:
    if type(value) is bool:
        return value
    if isinstance(value, str):
        return {"true": True, "yes": True, "false": False, "no": False}.get(
            value.strip().lower()
        )
    return None


def _eligibility(details: dict) -> list[str]:
    who = details.get("WhoMayApply")
    values = [_text(who.get("Name"))] if isinstance(who, dict) else []
    values.extend(_text(item) for item in _list(details.get("KeyRequirements")))
    values.append(_text(details.get("Requirements")))
    return list(dict.fromkeys(value for value in values if value))


def _citizens_only(values: list[str]) -> bool:
    # Whole explicit statements only; never infer eligibility from a city/agency,
    # public hiring path, clearance, qualifications or a negated/conditional clause.
    statements = {
        "us citizens only",
        "u.s. citizens only",
        "united states citizens only",
        "you must be a u.s. citizen",
        "you must be a united states citizen",
        "you must be a u.s. citizen to apply for this job",
        "u.s. citizenship is required",
    }
    return any(value.casefold().strip().rstrip(".") in statements for value in values)


def _salary(descriptor: dict) -> tuple:
    rows = _list(descriptor.get("PositionRemuneration"))
    unknown = (None, None, None, None)
    if len(rows) != 1 or not isinstance(rows[0], dict):
        return unknown
    row = rows[0]
    try:
        amounts = []
        for field in ("MinimumRange", "MaximumRange"):
            value = row.get(field)
            if isinstance(value, bool) or value is None:
                return unknown
            number = Decimal(str(value))
            if not number.is_finite() or number != number.to_integral_value():
                return unknown
            if not 0 <= number <= 2_147_483_647:
                return unknown
            amounts.append(int(number))
    except (InvalidOperation, ValueError):
        return unknown
    if amounts[0] > amounts[1]:
        return unknown
    period = {"PA": "yearly", "PH": "hourly"}.get(row.get("RateIntervalCode"))
    return *amounts, "USD", period


def _employment(descriptor: dict) -> str | None:
    schedules = _list(descriptor.get("PositionSchedule"))
    if len(schedules) != 1 or not isinstance(schedules[0], dict):
        return None
    row = schedules[0]
    code = str(row.get("Code", ""))
    if code in {"1", "2"}:
        return {"1": "full_time", "2": "part_time"}[code]
    # Multiple/intermittent schedules are not conventional employment types;
    # Permanent/Term describe appointment tenure, not contract employment.
    return None


def parse_job(raw: dict, *, collected_at: datetime | None = None) -> JobDTO | None:
    if not isinstance(raw, dict):
        raise ValueError("Invalid USAJOBS item")
    descriptor = raw.get("MatchedObjectDescriptor")
    if not isinstance(descriptor, dict):
        raise ValueError("Missing USAJOBS descriptor")
    identity = raw.get("MatchedObjectId")
    if (
        type(identity) not in {int, str}
        or not str(identity).isascii()
        or not str(identity).isdigit()
    ):
        raise ValueError("Missing USAJOBS control number")
    title, url = _text(descriptor.get("PositionTitle")), descriptor.get("PositionURI")
    if not title or not isinstance(url, str):
        raise ValueError("Missing USAJOBS title or URL")
    url = url.strip()
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"www.usajobs.gov", "usajobs.gov"}
        or parsed.username
        or parsed.password
    ):
        raise ValueError("Invalid USAJOBS position URL")
    now = collected_at or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("collected_at must be timezone-aware")
    now = now.astimezone(UTC)
    if _closed(descriptor.get("ApplicationCloseDate"), now):
        return None
    details, locations = _details(descriptor), _locations(descriptor)
    explicit = _boolean(details.get("RemoteIndicator"))
    remote_location = any(
        value.casefold() in REMOTE_US_LOCATIONS for value in locations
    )
    remote = explicit if explicit is not None else remote_location
    eligibility = _eligibility(details)
    regions = ["us_only"] if remote_location or _citizens_only(eligibility) else []
    summary = _text(details.get("JobSummary")) or _text(
        descriptor.get("QualificationSummary")
    )
    sections = [summary] if summary else []
    if eligibility:
        sections.append("Eligibility: " + "; ".join(eligibility)[:3000])
    telework = _boolean(details.get("TeleworkEligible"))
    if telework is not None:
        sections.append(f"Telework eligible: {'Yes' if telework else 'No'}")
    location = "; ".join(locations[:5])
    if len(locations) > 5:
        location += f"; +{len(locations) - 5} more"
    published = _date(descriptor.get("PublicationStartDate"))
    published = published.astimezone(UTC) if published and published.tzinfo else None
    salary = _salary(descriptor)
    return JobDTO(
        source="usajobs",
        external_id=str(identity),
        title=title,
        company=_text(descriptor.get("OrganizationName"))
        or _text(descriptor.get("DepartmentName")),
        description="\n\n".join(sections)[:12000] or None,
        url=url,
        location=location or None,
        remote=remote,
        remote_regions=regions,
        employment_type=_employment(descriptor),
        salary_min=salary[0],
        salary_max=salary[1],
        currency=salary[2],
        salary_period=salary[3],
        technologies=[],
        experience_level=None,
        published_at=published,
        collected_at=now,
        timezone_text=None,
        timezone_min_utc_offset=None,
        timezone_max_utc_offset=None,
    )


def parse_page(
    payload: object, *, collected_at: datetime | None = None
) -> tuple[list[JobDTO], int, dict]:
    result = payload.get("SearchResult") if isinstance(payload, dict) else None
    if not isinstance(result, dict) or not isinstance(
        result.get("SearchResultItems"), list
    ):
        raise CollectionError("USAJOBS returned an invalid search page")
    rows = result["SearchResultItems"]
    total, count = result.get("SearchResultCountAll"), result.get("SearchResultCount")
    if (
        type(total) is not int
        or type(count) is not int
        or count != len(rows)
        or total < count
    ):
        raise CollectionError("USAJOBS returned invalid result counts")
    jobs, now = [], collected_at or datetime.now(UTC)
    audit = {"received": count, "closed": 0, "invalid": 0, "telework_only": 0}
    for row in rows:
        try:
            job = parse_job(row, collected_at=now)
        except (ValueError, TypeError):
            audit["invalid"] += 1
            logger.warning("USAJOBS skipped malformed job item")
            continue
        if job is None:
            audit["closed"] += 1
            continue
        details = _details(row["MatchedObjectDescriptor"])
        audit["telework_only"] += int(
            _boolean(details.get("TeleworkEligible")) is True and not job.remote
        )
        jobs.append(job)
    if rows and audit["invalid"] == len(rows):
        raise CollectionError("USAJOBS page has no valid items")
    return jobs, total, audit


class USAJobsCollector(BaseJobCollector):
    source_name = "usajobs"
    page_size = 50
    max_response_bytes = 8 * 1024 * 1024
    categories = USAJOBS_CATEGORIES

    def __init__(
        self,
        *,
        timeout: float | None = None,
        max_pages: int | None = None,
        max_jobs: int | None = None,
    ):
        from src.config import settings

        super().__init__(timeout=timeout)
        self._api_key, self._email = settings.USAJOBS_API_KEY, settings.USAJOBS_EMAIL
        self.max_pages = (
            settings.USAJOBS_MAX_PAGES_PER_QUERY if max_pages is None else max_pages
        )
        self.max_jobs = (
            settings.USAJOBS_MAX_JOBS_PER_RUN if max_jobs is None else max_jobs
        )
        if type(self.max_pages) is not int or not 1 <= self.max_pages <= 5:
            raise ValueError("max_pages must be an integer from 1 to 5")
        if type(self.max_jobs) is not int or not 1 <= self.max_jobs <= 500:
            raise ValueError("max_jobs must be an integer from 1 to 500")
        self.last_report: dict = {}
        self.query_job_ids: dict[str, list[str]] = {}

    async def collect(self) -> list[JobDTO]:
        self.last_report = {}
        self.query_job_ids = {category: [] for category in self.categories}
        for name, value in (
            ("USAJOBS_API_KEY", self._api_key),
            ("USAJOBS_EMAIL", self._email),
        ):
            if not value:
                raise CollectorConfigurationError(f"USAJOBS requires {name}")
            if not value.isascii() or any(
                ord(char) < 32 or ord(char) == 127 for char in value
            ):
                raise CollectorConfigurationError(f"USAJOBS requires a valid {name}")
        if "@" not in self._email or any(char.isspace() for char in self._email):
            raise CollectorConfigurationError("USAJOBS requires a valid USAJOBS_EMAIL")
        install_network_log_filter(secrets=(self._api_key, self._email))
        headers = {
            "Host": "data.usajobs.gov",
            "User-Agent": self._email,
            "Authorization-Key": self._api_key,
            "Accept": "application/json",
        }
        jobs, seen, finished = [], set(), set()
        counters = {
            category: {
                "category": category,
                "requests": 0,
                "received": 0,
                "unique": 0,
                "remote": 0,
                "telework_only": 0,
                "closed": 0,
                "invalid": 0,
            }
            for category in self.categories
        }
        async with httpx.AsyncClient(
            timeout=self.timeout, headers=headers, follow_redirects=False
        ) as client:
            requests = 0
            for page in range(1, self.max_pages + 1):
                for category in self.categories:
                    if category in finished or len(jobs) >= self.max_jobs:
                        continue
                    if requests:
                        await asyncio.sleep(1)
                    requests += 1
                    counters[category]["requests"] += 1
                    try:
                        payload = await fetch_json(
                            client,
                            SEARCH_URL,
                            source="USAJOBS",
                            params={
                                "JobCategoryCode": category,
                                "RemoteIndicator": "True",
                                "DatePosted": 30,
                                "SortField": "opendate",
                                "SortDirection": "Desc",
                                "ResultsPerPage": self.page_size,
                                "Page": page,
                                "Fields": "Full",
                            },
                            max_response_bytes=self.max_response_bytes,
                        )
                    except CollectionError as exc:
                        if str(exc) in {"USAJOBS HTTP 401", "USAJOBS HTTP 403"}:
                            raise CollectionError(
                                "USAJOBS access denied (HTTP 401/403); check "
                                "USAJOBS_API_KEY and USAJOBS_EMAIL"
                            ) from None
                        raise
                    batch, total, audit = parse_page(payload)
                    row = counters[category]
                    for field, value in audit.items():
                        row[field] += value
                    prior = len(self.query_job_ids[category])
                    query_seen = set(self.query_job_ids[category])
                    for job in batch:
                        if job.external_id not in query_seen:
                            query_seen.add(job.external_id)
                            self.query_job_ids[category].append(job.external_id)
                            row["remote"] += int(job.remote)
                        if job.external_id not in seen and len(jobs) < self.max_jobs:
                            seen.add(job.external_id)
                            jobs.append(job)
                    row["unique"] = len(query_seen)
                    if (
                        audit["received"] < self.page_size
                        or page * self.page_size >= total
                        or (len(query_seen) == prior and not audit["closed"])
                    ):
                        finished.add(category)
        self.last_report = {
            "queries": list(counters.values()),
            "queries_executed": sum(row["requests"] > 0 for row in counters.values()),
            "api_results_received": sum(row["received"] for row in counters.values()),
            "unique_jobs": len(jobs),
            "remote_jobs": sum(job.remote for job in jobs),
            "closed_jobs_skipped": sum(row["closed"] for row in counters.values()),
        }
        logger.info("USAJOBS collection: %s", self.last_report)
        return jobs
