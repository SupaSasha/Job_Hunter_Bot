from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
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
    max_response_bytes = 8 * 1024 * 1024

    async def collect(self) -> list[JobDTO]:
        logger.info("[%s] starting collection", self.source_name)

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
                headers=self.request_headers,
            ) as client:
                async with client.stream("GET", self.api_url) as response:
                    if response.status_code == 429:
                        retry_at = self._retry_at(
                            response.headers.get("Retry-After", "")
                        )
                        logger.warning("Remote OK HTTP 429; retry_at=%s", retry_at)
                        raise CollectionError(
                            "Remote OK rate limited", retry_at=retry_at
                        )
                    response.raise_for_status()
                    content = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        content.extend(chunk)
                        if len(content) > self.max_response_bytes:
                            raise CollectionError(
                                "Remote OK response exceeds size limit"
                            )
                payload = json.loads(content)
        except httpx.TimeoutException as exc:
            logger.error("Remote OK request timeout (%s)", type(exc).__name__)
            raise CollectionError("Remote OK request timed out") from exc
        except httpx.HTTPError as exc:
            logger.error("Remote OK HTTP request failed (%s)", type(exc).__name__)
            raise CollectionError("Remote OK collection failed") from exc
        except (ValueError, UnicodeDecodeError) as exc:
            logger.error("Remote OK invalid JSON (%s)", type(exc).__name__)
            raise CollectionError("Remote OK invalid JSON") from exc

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
                    type(exc).__name__,
                )
                continue

        logger.info("[%s] collected %s jobs", self.source_name, len(jobs))
        return jobs

    @staticmethod
    def _retry_at(value: str) -> datetime | None:
        try:
            if value.isdigit():
                return datetime.now(timezone.utc) + timedelta(seconds=int(value))
            return RemoteOKCollector._parse_datetime(parsedate_to_datetime(value))
        except (ValueError, TypeError, OverflowError):
            return None

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
                parsed = datetime.fromisoformat(normalized)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc)
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
        # The remote-jobs feed normally omits this flag, including jobs with a
        # location. Keep an explicit rejection, but default missing flags to remote.
        remote_value = bool(raw_job.get("remote", True))

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
