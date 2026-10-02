from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.schemas.filters import UserFilterDTO
from src.schemas.job import JobDTO
from src.services.scoring import ScoringService


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
        "remote_regions": ["latam"],
        "employment_type": "full_time",
        "salary_min": None,
        "salary_max": None,
        "currency": "USD",
        "salary_period": "year",
        "technologies": [
            "python",
            "fastapi",
            "postgresql",
            "redis",
            "celery",
            "docker",
        ],
        "experience_level": "middle",
        "published_at": datetime(2026, 9, 1, tzinfo=timezone.utc),
        "collected_at": datetime(2026, 9, 2, tzinfo=timezone.utc),
        "timezone_text": "UTC-5 to UTC-2",
        "timezone_min_utc_offset": -5,
        "timezone_max_utc_offset": -2,
    }
    data.update(overrides)
    return JobDTO(**data)


def test_scoring_rewards_profile_match_and_remote_and_region() -> None:
    service = ScoringService()
    job = build_job()
    filters = UserFilterDTO(
        keywords=["backend", "python"],
        preferred_technologies=["python", "docker"],
        timezone="America/Montevideo",
    )

    result = service.calculate(job, filters)

    assert result.score >= 80
    assert any("Base score: +50" in entry for entry in result.matched_rules)
    assert any("Python: +10" in entry for entry in result.matched_rules)
    assert any("FastAPI: +10" in entry for entry in result.matched_rules)
    assert any("Remote: +10" in entry for entry in result.matched_rules)
    assert any("LATAM region: +10" in entry for entry in result.matched_rules)
    assert any("Keyword: backend: +3" in entry for entry in result.matched_rules)


def test_scoring_penalizes_senior_levels_once_and_infers_title_seniority() -> None:
    service = ScoringService()
    job = build_job(
        experience_level="senior",
        title="Senior Python Developer",
        description="Requires 5+ years of professional experience",
    )
    filters = UserFilterDTO(timezone="America/Montevideo")

    result = service.calculate(job, filters)

    assert result.penalties.count("Senior level: -5") == 1
    assert any(
        "Requires 5+ years of experience: -10" in penalty
        for penalty in result.penalties
    )
    assert result.score <= 100


def test_scoring_handles_timezone_exact_distance_and_unknown_timezone() -> None:
    service = ScoringService()

    compatible = service.calculate(
        build_job(timezone_min_utc_offset=-5, timezone_max_utc_offset=-2),
        UserFilterDTO(timezone="America/Montevideo"),
    )
    assert any(
        "Timezone compatible: +10" in entry for entry in compatible.matched_rules
    )

    distance = service.calculate(
        build_job(timezone_min_utc_offset=0, timezone_max_utc_offset=0),
        UserFilterDTO(timezone="America/Montevideo"),
    )
    assert any(
        "Timezone distance: 3 hours: 0" in entry
        for entry in distance.matched_rules + distance.penalties
    )

    unknown = service.calculate(
        build_job(timezone_min_utc_offset=None, timezone_max_utc_offset=None),
        UserFilterDTO(timezone="America/Montevideo"),
    )
    assert any(
        "Timezone is not specified: -2" in penalty for penalty in unknown.penalties
    )
    assert any("Timezone is not specified" in warning for warning in unknown.warnings)


def test_scoring_warns_for_unknown_salary_and_clamps_score_bounds() -> None:
    service = ScoringService()

    unknown_salary = service.calculate(
        build_job(), UserFilterDTO(timezone="America/Montevideo")
    )
    assert any(
        "Salary is not specified: -2" in penalty for penalty in unknown_salary.penalties
    )
    assert any(
        "Salary is not specified" in warning for warning in unknown_salary.warnings
    )

    top = service.calculate(
        build_job(
            remote=True,
            remote_regions=["worldwide"],
            technologies=[
                "python",
                "fastapi",
                "postgresql",
                "redis",
                "celery",
                "docker",
            ],
            employment_type="full_time",
            experience_level="junior",
            timezone_min_utc_offset=-5,
            timezone_max_utc_offset=-2,
        ),
        UserFilterDTO(
            keywords=["python", "backend"],
            preferred_technologies=["python", "fastapi", "docker"],
            timezone="America/Montevideo",
        ),
    )
    assert 0 <= top.score <= 100

    bad = service.calculate(
        build_job(
            remote=False,
            remote_regions=[],
            technologies=[],
            title="Senior Staff Backend Engineer",
            description="Requires 7+ years of professional experience",
            employment_type="contract",
            experience_level="principal",
            timezone_min_utc_offset=6,
            timezone_max_utc_offset=8,
        ),
        UserFilterDTO(timezone="America/Montevideo"),
    )
    assert 0 <= bad.score <= 100
    assert bad.score == 0 or bad.score < 40


@pytest.mark.parametrize(
    "description,expected",
    [
        ("We've been growing for 12 years. Requires 2 years of experience.", 2),
        ("5+ years of professional experience", 5),
        ("At least 4 years experience with Python", 4),
        ("minimum 3 years experience", 3),
        ("3+ years experience with Python", 3),
        ("5 years software experience; 2 years Python experience", 5),
        ("Company founded 10 years ago", None),
        ("Product has been used for 7 years", None),
        ("The team has worked together for 6 years", None),
    ],
)
def test_years_require_explicit_experience_context(description, expected):
    assert ScoringService._infer_years_of_experience(description) == expected
