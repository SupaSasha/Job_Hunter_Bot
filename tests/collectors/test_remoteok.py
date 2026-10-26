from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.collectors.remoteok import RemoteOKCollector
from src.schemas.filters import UserFilterDTO
from src.services.filters import FilterService
from src.services.normalization import NormalizationService


def test_remoteok_map_job_parses_expected_fields() -> None:
    raw_job = {
        "id": 12345,
        "position": "Senior Python Developer",
        "company": "Acme Labs",
        "description": "Build backend APIs",
        "url": "https://remoteok.com/remote-jobs/senior-python-developer-acme-12345",
        "location": "",
        "remote": True,
        "tags": ["python", "fastapi", "postgres"],
        "date": "2026-09-22T10:30:00+00:00",
        "salary_min": 120000,
        "salary_max": 160000,
    }

    dto = RemoteOKCollector.map_job(raw_job)

    assert dto.source == "remoteok"
    assert dto.external_id == "12345"
    assert dto.title == "Senior Python Developer"
    assert dto.company == "Acme Labs"
    assert dto.description == "Build backend APIs"
    assert (
        dto.url == "https://remoteok.com/remote-jobs/senior-python-developer-acme-12345"
    )
    assert dto.remote is True
    assert dto.remote_regions == []
    assert dto.technologies == ["python", "fastapi", "postgres"]
    assert dto.published_at == datetime(2026, 9, 22, 10, 30, tzinfo=timezone.utc)
    assert dto.collected_at.tzinfo is not None


def test_remoteok_map_job_handles_missing_optionals() -> None:
    raw_job = {
        "id": "abc-1",
        "position": "QA Engineer",
        "company": "TestCo",
        "url": "https://example.com/jobs/qa-engineer",
        "location": "Berlin",
        "remote": False,
        "tags": ["qa", "automation"],
        "date": "2026-09-22T08:00:00+00:00",
    }

    dto = RemoteOKCollector.map_job(raw_job)

    assert dto.external_id == "abc-1"
    assert dto.title == "QA Engineer"
    assert dto.company == "TestCo"
    assert dto.location == "Berlin"
    assert dto.remote is False
    assert dto.description is None
    assert dto.salary_min is None
    assert dto.salary_max is None
    assert dto.technologies == ["qa", "automation"]
    assert dto.published_at == datetime(2026, 9, 22, 8, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("location", [None, "Remote", "Berlin", "Brazil"])
def test_missing_remote_flag_passes_default_remote_filter(location):
    job = NormalizationService().normalize(
        RemoteOKCollector.map_job(
            {
                "id": "remote-without-flag",
                "position": "Accountant",
                "url": "https://remoteok.com/remote-jobs/accountant",
                "location": location,
            }
        )
    )

    assert job.remote is True
    assert FilterService().evaluate(job, UserFilterDTO()).accepted


def test_naive_iso_is_utc_independent_of_host_timezone(monkeypatch):
    import os
    import time

    previous = os.environ.get("TZ")
    monkeypatch.setenv("TZ", "America/Los_Angeles")
    time.tzset()
    try:
        assert RemoteOKCollector._parse_datetime("2026-09-22T10:30:00") == datetime(
            2026, 9, 22, 10, 30, tzinfo=timezone.utc
        )
    finally:
        if previous is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = previous
        time.tzset()


async def test_remoteok_response_limit_and_retry_after(monkeypatch):
    import httpx
    import pytest

    from src.collectors.base import CollectionError

    real_client = httpx.AsyncClient
    for status, content, headers in [
        (200, b"x" * 101, {}),
        (429, b"", {"Retry-After": "60"}),
    ]:
        monkeypatch.setattr(
            "src.collectors.remoteok.httpx.AsyncClient",
            lambda **kwargs: real_client(
                **kwargs,
                transport=httpx.MockTransport(
                    lambda _: httpx.Response(status, content=content, headers=headers)
                ),
            ),
        )
        collector = RemoteOKCollector()
        collector.max_response_bytes = 100
        with pytest.raises(CollectionError) as caught:
            await collector.collect()
        if status == 429:
            assert caught.value.retry_at is not None
            assert (
                caught.value.retry_at - datetime.now(timezone.utc)
            ).total_seconds() > 50
        else:
            assert "size limit" in str(caught.value)
