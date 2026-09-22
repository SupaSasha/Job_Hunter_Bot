from __future__ import annotations

from datetime import datetime, timezone

from src.collectors.remoteok import RemoteOKCollector


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
