"""Bounded collection from Get on Board's official public JSON API."""

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


def _text(value) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def _resources(attributes: dict, name: str) -> list[dict]:
    relationship = attributes.get(name)
    data = relationship.get("data") if isinstance(relationship, dict) else None
    if isinstance(data, dict):
        data = [data]
    return (
        [item for item in data if isinstance(item, dict)]
        if isinstance(data, list)
        else []
    )


def _names(attributes: dict, name: str) -> list[str]:
    values = []
    for item in _resources(attributes, name):
        fields = item.get("attributes")
        value = _text(fields.get("name")) if isinstance(fields, dict) else None
        if value:
            values.append(value)
    return list(dict.fromkeys(values))


def _published(value) -> datetime | None:
    try:
        if type(value) in (int, float):
            return datetime.fromtimestamp(value, UTC)
        if isinstance(value, str):
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return result.astimezone(UTC) if result.tzinfo else None
    except (ValueError, OverflowError, OSError):
        pass
    return None


def _salary(value) -> int | None:
    return value if type(value) is int and value >= 0 else None


def parse_job(raw: dict, *, collected_at: datetime | None = None) -> JobDTO:
    if not isinstance(raw, dict) or not isinstance(raw.get("attributes"), dict):
        raise ValueError("Invalid Get on Board job")
    a = raw["attributes"]
    job_id, title = _text(raw.get("id")), _text(a.get("title"))
    links = raw.get("links")
    url = _text(links.get("public_url")) if isinstance(links, dict) else None
    if not job_id or not title or not url:
        raise ValueError("Missing job identity, title or URL")
    parsed_url = urlsplit(url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.hostname:
        raise ValueError("Invalid public job URL")

    mode = a.get("remote_modality")
    remote = a.get("remote") is True
    if mode in {"hybrid", "no_remote", "temporarily_remote"}:
        remote = False

    countries = a.get("countries")
    countries = (
        [
            value
            for item in countries
            if (value := _text(item)) and value.lower() != "remote"
        ]
        if isinstance(countries, list)
        else []
    )
    regions = _names(a, "location_regions")
    tenants = _names(a, "location_tenants")
    cities = _names(a, "location_cities")
    # These are explicitly selected eligible regions/countries, not company HQ.
    eligibility = list(dict.fromkeys([*regions, *tenants, *countries]))
    if remote and mode == "fully_remote" and not eligibility:
        eligibility = ["Worldwide"]
    location = (
        ", ".join(dict.fromkeys([*cities, *tenants, *countries, *regions])) or None
    )

    description = (
        "\n\n".join(
            part
            for field in (
                "projects",
                "description",
                "functions",
                "desirable",
                "benefits",
            )
            if (part := html_to_text(_text(a.get(field))))
        )
        or None
    )
    companies, modalities, seniorities = (
        _names(a, "company"),
        _names(a, "modality"),
        _names(a, "seniority"),
    )
    return JobDTO(
        source="getonboard",
        external_id=job_id,
        title=title,
        company=companies[0] if companies else None,
        description=description,
        url=url,
        location=location,
        remote=remote,
        remote_regions=eligibility if remote else [],
        technologies=_names(a, "tags"),
        employment_type=modalities[0] if modalities else None,
        experience_level=seniorities[0] if seniorities else None,
        salary_min=_salary(a.get("min_salary")),
        salary_max=_salary(a.get("max_salary")),
        currency=_text(a.get("currency")),
        salary_period=_text(a.get("salary_period")),
        timezone_text=_text(a.get("remote_zone")),
        published_at=_published(a.get("published_at")),
        collected_at=collected_at or datetime.now(UTC),
    )


def parse_page(payload: dict) -> tuple[list[JobDTO], int | None]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise CollectionError("Get on Board returned an invalid jobs page")
    meta = payload.get("meta")
    pages = meta.get("total_pages") if isinstance(meta, dict) else None
    if pages is not None and (type(pages) is not int or pages < 0):
        raise CollectionError("Get on Board returned invalid pagination")
    jobs = []
    now = datetime.now(UTC)
    for raw in payload["data"]:
        try:
            jobs.append(parse_job(raw, collected_at=now))
        except (ValueError, TypeError):
            logger.warning("Get on Board skipped malformed job item")
    if payload["data"] and not jobs:
        raise CollectionError("Get on Board page has no valid jobs")
    return jobs, pages


class GetOnBoardCollector(BaseJobCollector):
    source_name = "getonboard"
    api_url = "https://www.getonbrd.com/api/v0/search/jobs"
    max_pages = 2
    max_response_bytes = 8 * 1024 * 1024
    expansions = (
        "company",
        "tags",
        "seniority",
        "modality",
        "location_regions",
        "location_tenants",
        "location_cities",
    )

    def __init__(
        self, *, timeout: float | None = None, max_pages: int = 2, per_page: int = 50
    ):
        super().__init__(timeout=timeout)
        if type(max_pages) is not int or not 1 <= max_pages <= 5:
            raise ValueError("max_pages must be an integer from 1 to 5")
        if type(per_page) is not int or not 1 <= per_page <= 120:
            raise ValueError("per_page must be an integer from 1 to 120")
        self.max_pages = max_pages
        self.per_page = per_page

    async def collect(self) -> list[JobDTO]:
        jobs = []
        seen = set()
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                headers=self.request_headers,
                follow_redirects=True,
            ) as client:
                for page in range(1, self.max_pages + 1):
                    params = [
                        ("remote", "true"),
                        ("page", str(page)),
                        ("per_page", str(self.per_page)),
                        ("lang", "en"),
                        *[("expand[]", name) for name in self.expansions],
                    ]
                    payload = await fetch_json(
                        client,
                        self.api_url,
                        source="Get on Board",
                        params=params,
                        max_response_bytes=self.max_response_bytes,
                    )
                    batch, total_pages = parse_page(payload)
                    added = 0
                    for job in batch:
                        if job.external_id not in seen:
                            seen.add(job.external_id)
                            jobs.append(job)
                            added += 1
                    if (
                        not batch
                        or not added
                        or (total_pages is not None and page >= total_pages)
                    ):
                        break
                    if total_pages is None and len(payload["data"]) < self.per_page:
                        break
                    if page < self.max_pages:
                        await asyncio.sleep(1)
        except httpx.TimeoutException:
            raise CollectionError("Get on Board request timed out") from None
        except httpx.HTTPStatusError as exc:
            raise CollectionError(
                f"Get on Board HTTP {exc.response.status_code}"
            ) from None
        except httpx.HTTPError:
            raise CollectionError("Get on Board network request failed") from None
        logger.info("Get on Board collected %s jobs", len(jobs))
        return jobs


async def main() -> None:
    try:
        jobs = await GetOnBoardCollector().collect()
    except CollectionError as exc:
        print(str(exc))
        raise SystemExit(1) from None
    print(f"received: {len(jobs)}")
    for job in jobs[:3]:
        print(
            f"[Get on Board] {job.title} — {job.company or 'Unknown'} — "
            f"{job.location or ', '.join(job.remote_regions) or 'Unknown'}"
        )


if __name__ == "__main__":
    asyncio.run(main())
