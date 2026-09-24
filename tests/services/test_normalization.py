from __future__ import annotations

from datetime import datetime, timezone

from src.schemas.job import JobDTO
from src.services.normalization import NormalizationService


def test_normalization_service_normalizes_technologies_and_regions() -> None:
    service = NormalizationService()
    job = JobDTO(
        source="remoteok",
        external_id="1",
        title="Senior Python Developer",
        company="Acme Inc.",
        description="Python, FastAPI and PostgreSQL",
        url="https://example.com/jobs/1",
        location="Remote",
        remote=True,
        remote_regions=["Worldwide", "LatAm", "Uruguay", "Uruguay"],
        employment_type="Full-time",
        salary_min=120000,
        salary_max=150000,
        currency="USD",
        salary_period="year",
        technologies=["Python", "Fast API", "PYTHON", "postgres", "K8s", "redis"],
        experience_level="Senior",
        published_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        collected_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
        timezone_text="UTC-5 to UTC-2",
        timezone_min_utc_offset=-5,
        timezone_max_utc_offset=-2,
    )

    normalized = service.normalize(job)

    assert normalized.technologies == [
        "python",
        "fastapi",
        "postgresql",
        "kubernetes",
        "redis",
    ]
    assert normalized.remote_regions == ["worldwide", "latam", "uruguay"]
    assert normalized.employment_type == "full_time"
    assert normalized.experience_level == "senior"
    assert normalized.timezone_text == "UTC-5 to UTC-2"
    assert normalized.timezone_min_utc_offset == -5
    assert normalized.timezone_max_utc_offset == -2


def test_normalization_service_normalizes_location_and_company_and_timezone() -> None:
    service = NormalizationService()
    job = JobDTO(
        source="remoteok",
        external_id="2",
        title="  Senior  Python Developer  ",
        company="  Acme    Labs  ",
        description="Remote work",
        url="https://example.com/jobs/2",
        location="   Montevideo , Uruguay   ",
        remote=False,
        remote_regions=["Unknown region"],
        employment_type="Contractor",
        technologies=["JavaScript", "TypeScript", "Node.js"],
        experience_level="Mid-level",
        published_at=datetime(2026, 9, 3, tzinfo=timezone.utc),
        collected_at=datetime(2026, 9, 4, tzinfo=timezone.utc),
        timezone_text="GMT-3",
    )

    normalized = service.normalize(job)

    assert normalized.title == "Senior Python Developer"
    assert normalized.company == "Acme Labs"
    assert normalized.location == "Montevideo , Uruguay"
    assert normalized.employment_type == "contract"
    assert normalized.experience_level == "middle"
    assert normalized.technologies == ["javascript", "typescript", "nodejs"]
    assert normalized.timezone_text == "GMT-3"
    assert normalized.timezone_min_utc_offset == -3
    assert normalized.timezone_max_utc_offset == -3
