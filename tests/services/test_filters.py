from __future__ import annotations

from datetime import datetime, timezone

from src.schemas.filters import UserFilterDTO
from src.schemas.job import JobDTO
from src.services.filters import FilterService


def build_job(**overrides: object) -> JobDTO:
    data = {
        "source": "remoteok",
        "external_id": "job-1",
        "title": "Python Backend Developer",
        "company": "Acme Inc.",
        "description": "Build APIs with Python, FastAPI and PostgreSQL.",
        "url": "https://example.com/job/1",
        "location": "Montevideo, Uruguay",
        "remote": True,
        "remote_regions": ["worldwide"],
        "employment_type": "full_time",
        "salary_min": 120000,
        "salary_max": 180000,
        "currency": "USD",
        "salary_period": "year",
        "technologies": ["python", "fastapi", "postgresql"],
        "experience_level": "middle",
        "published_at": datetime(2026, 9, 1, tzinfo=timezone.utc),
        "collected_at": datetime(2026, 9, 2, tzinfo=timezone.utc),
        "timezone_text": "UTC-3",
        "timezone_min_utc_offset": -3,
        "timezone_max_utc_offset": -3,
    }
    data.update(overrides)
    return JobDTO(**data)


def test_filter_service_accepts_matching_remote_job() -> None:
    service = FilterService()
    job = build_job()
    filters = UserFilterDTO(
        sources=["remoteok"],
        required_technologies=["python", "postgresql"],
        keywords=["python", "backend"],
        remote_only=True,
        worldwide_allowed=True,
        latam_allowed=True,
        south_america_allowed=True,
        uruguay_allowed=True,
    )

    result = service.evaluate(job, filters)

    assert result.accepted is True
    assert result.reasons == []


def test_filter_service_rejects_non_remote_and_excluded_and_required_technology() -> (
    None
):
    service = FilterService()
    job = build_job(remote=False, technologies=["python", "php"])
    filters = UserFilterDTO(
        remote_only=True,
        required_technologies=["python", "postgresql"],
        excluded_technologies=["php"],
        keywords=["python"],
    )

    result = service.evaluate(job, filters)

    assert result.accepted is False
    assert any("Vacancy is not remote" in reason for reason in result.reasons)
    assert any("Excluded technology: php" in reason for reason in result.reasons)
    assert any(
        "Missing required technology: postgresql" in reason for reason in result.reasons
    )


def test_filter_service_rejects_blacklist_and_salary_and_experience() -> None:
    service = FilterService()
    job = build_job(
        company="WordPress Labs",
        title="PHP Backend Developer",
        description="We operate WordPress sites.",
        technologies=["php", "wordpress"],
        salary_min=1000,
        salary_max=2000,
        experience_level="staff",
    )
    filters = UserFilterDTO(
        min_salary=2500,
        currency="USD",
        experience_levels=["junior", "middle"],
        blacklisted_words=["wordpress"],
        blacklisted_companies=["wordpress labs"],
        excluded_technologies=["php"],
    )

    result = service.evaluate(job, filters)

    assert result.accepted is False
    assert any("Blacklisted word: wordpress" in reason for reason in result.reasons)
    assert any(
        "Blacklisted company: WordPress Labs" in reason for reason in result.reasons
    )
    assert any("Salary is below minimum" in reason for reason in result.reasons)
    assert any(
        "Experience level is not allowed: staff" in reason for reason in result.reasons
    )


def test_filter_service_rejects_us_only_and_respects_region_flags() -> None:
    service = FilterService()
    job = build_job(remote_regions=["us_only"])
    filters = UserFilterDTO(exclude_us_only=True, worldwide_allowed=True)

    result = service.evaluate(job, filters)

    assert result.accepted is False
    assert any("US-only vacancy" in reason for reason in result.reasons)


def test_filter_service_accepts_timezone_overlap_and_rejects_incompatible_range() -> (
    None
):
    service = FilterService()
    user_filters = UserFilterDTO(
        timezone="America/Montevideo", timezone_tolerance_hours=2
    )

    compatible_job = build_job(timezone_min_utc_offset=-5, timezone_max_utc_offset=-2)
    compatible = service.evaluate(compatible_job, user_filters)
    assert compatible.accepted is True

    incompatible_job = build_job(timezone_min_utc_offset=2, timezone_max_utc_offset=4)
    incompatible = service.evaluate(incompatible_job, user_filters)
    assert incompatible.accepted is False
    assert any(
        "Timezone is not compatible" in reason for reason in incompatible.reasons
    )


def test_filter_service_allows_unknown_timezone_and_empty_regions() -> None:
    service = FilterService()
    job = build_job(
        remote_regions=[], timezone_min_utc_offset=None, timezone_max_utc_offset=None
    )
    filters = UserFilterDTO(remote_only=True)

    result = service.evaluate(job, filters)

    assert result.accepted is True
    assert result.reasons == []
