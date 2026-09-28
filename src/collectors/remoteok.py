from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from src.collectors.base import BaseJobCollector
from src.collectors.base import CollectionError as CollectionError
from src.schemas.job import JobDTO

logger = logging.getLogger(__name__)


class RemoteOKCollector(BaseJobCollector):
    """Collect jobs from the public Remote OK JSON API."""

    source_name = "remoteok"
    api_url = "https://remoteok.com/api"

    async def collect(self) -> list[JobDTO]:
        logger.info("[%s] starting collection", self.source_name)

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
                headers=self.request_headers,
            ) as client:
                response = await client.get(self.api_url)
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    logger.warning(
                        "[%s] rate limited by Remote OK. Retry-After: %s",
                        self.source_name,
                        retry_after,
                    )
                    raise CollectionError("Remote OK rate limited")
                response.raise_for_status()
                payload = response.json()
        except httpx.TimeoutException as exc:
            logger.error("[%s] request timeout: %s", self.source_name, exc)
            raise CollectionError("Remote OK collection failed")
        except httpx.HTTPError as exc:
            logger.error(
                "[%s] HTTP error while fetching jobs: %s",
                self.source_name,
                exc,
            )
            raise CollectionError("Remote OK collection failed")
        except (json.JSONDecodeError, ValueError) as exc:
            logger.error("[%s] invalid JSON response: %s", self.source_name, exc)
            raise CollectionError("Remote OK collection failed")

        if not isinstance(payload, list):
            logger.error(
                "[%s] unexpected payload type: %s",
                self.source_name,
                type(payload).__name__,
            )
            raise CollectionError("Remote OK collection failed")

        jobs: list[JobDTO] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            if not any(key in item for key in ("id", "position", "slug")):
                continue
            try:
                jobs.append(self.map_job(item))
            except (TypeError, ValueError) as exc:
                logger.warning(
                    "[%s] skipping malformed job item: %s",
                    self.source_name,
                    exc,
                )
                continue

        logger.info("[%s] collected %s jobs", self.source_name, len(jobs))
        return jobs

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc)
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc)
        if isinstance(value, str):
            normalized = value.strip()
            if not normalized:
                return None
            try:
                if normalized.endswith("Z"):
                    normalized = normalized[:-1] + "+00:00"
                return datetime.fromisoformat(normalized).astimezone(timezone.utc)
            except ValueError:
                return None
        return None

    @staticmethod
    def map_job(raw_job: dict[str, Any]) -> JobDTO:
        if "id" in raw_job and raw_job.get("id") is not None:
            external_id = str(raw_job["id"])
        elif "slug" in raw_job and raw_job.get("slug") is not None:
            external_id = str(raw_job["slug"])
        else:
            raise ValueError("Job payload does not include a usable external id")

        title = str(raw_job.get("position") or "").strip() or "Untitled position"
        company = raw_job.get("company")
        description = raw_job.get("description")
        url = raw_job.get("url") or raw_job.get("apply_url")
        if not url:
            raise ValueError("Job payload does not include url")

        location = raw_job.get("location")
        if isinstance(location, str):
            location = location.strip() or None
        remote_value = bool(raw_job.get("remote", False))
        if not location and remote_value is False:
            remote_value = True

        remote_regions: list[str] = []
        if remote_value and location:
            remote_regions = [location]

        technologies = raw_job.get("tags") or []
        if not isinstance(technologies, list):
            technologies = [str(technologies)] if technologies else []
        technologies = [str(item).strip() for item in technologies if str(item).strip()]

        published_at = RemoteOKCollector._parse_datetime(raw_job.get("date"))
        collected_at = datetime.now(timezone.utc)

        return JobDTO(
            source="remoteok",
            external_id=external_id,
            title=title,
            company=str(company).strip() if company else None,
            description=str(description).strip() if description else None,
            url=str(url).strip(),
            location=location,
            remote=remote_value,
            remote_regions=remote_regions,
            employment_type=None,
            salary_min=(
                raw_job.get("salary_min")
                if isinstance(raw_job.get("salary_min"), int)
                else None
            ),
            salary_max=(
                raw_job.get("salary_max")
                if isinstance(raw_job.get("salary_max"), int)
                else None
            ),
            currency=None,
            salary_period=None,
            technologies=technologies,
            experience_level=None,
            published_at=published_at,
            collected_at=collected_at,
        )


async def main() -> None:
    collector = RemoteOKCollector()
    jobs = await collector.collect()
    print(f"[Remote OK] collected {len(jobs)} jobs")
    for job in jobs[:5]:
        location_label = "Remote" if job.remote else (job.location or "Unknown")
        print(
            f"[Remote OK] {job.title} — {job.company or 'Unknown'} — {location_label}"
        )


if __name__ == "__main__":
    asyncio.run(main())
