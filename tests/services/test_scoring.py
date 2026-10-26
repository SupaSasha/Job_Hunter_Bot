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


def test_scoring_rewards_only_user_relative_signals() -> None:
    service = ScoringService()
    job = build_job()
    filters = UserFilterDTO(
        keywords=["backend", "python"],
        preferred_technologies=["python", "docker"],
        allowed_regions=["latam"],
        timezone="America/Montevideo",
    )

    result = service.calculate(job, filters)

    assert result.score == 100
    assert any("Base score: +50" in entry for entry in result.matched_rules)
    assert any(
        "Preferred skills matched (2/2): +20" in entry for entry in result.matched_rules
    )
    assert any("Keywords matched (2/2): +15" in entry for entry in result.matched_rules)
    assert any(
        "Remote matches user preference: +5" in entry for entry in result.matched_rules
    )
    assert any(
        "Region matches user preferences: +10" in entry
        for entry in result.matched_rules
    )
    assert any("Timezone compatible: +10" in entry for entry in result.matched_rules)
    assert (
        service.calculate(job, filters).score
        == service.calculate(
            job.model_copy(update={"source": "usajobs"}), filters
        ).score
    )


def test_preferred_skills_rank_the_same_jobs_differently_per_user() -> None:
    service = ScoringService()
    python_job = build_job(
        title="Python Backend Developer",
        description="Build APIs with Python.",
        technologies=["python"],
        remote_regions=["worldwide"],
        timezone_min_utc_offset=None,
        timezone_max_utc_offset=None,
        experience_level=None,
        employment_type=None,
        salary_min=None,
        salary_max=None,
    )
    design_job = build_job(
        title="UX Designer",
        description="Create product experiences with Figma.",
        technologies=["figma"],
        remote_regions=["europe"],
        timezone_min_utc_offset=None,
        timezone_max_utc_offset=None,
        experience_level=None,
        employment_type=None,
        salary_min=None,
        salary_max=None,
    )
    python_user = UserFilterDTO(
        keywords=["python"],
        preferred_technologies=["python"],
        allowed_regions=["worldwide"],
        remote_only=False,
        timezone="UTC",
    )
    design_user = UserFilterDTO(
        keywords=["designer"],
        preferred_technologies=["figma"],
        allowed_regions=["europe"],
        remote_only=False,
        timezone="UTC",
    )

    python_scores = [
        service.calculate(job, python_user).score for job in (python_job, design_job)
    ]
    design_scores = [
        service.calculate(job, design_user).score for job in (python_job, design_job)
    ]

    assert python_scores[0] > python_scores[1]
    assert design_scores[1] > design_scores[0]


def test_empty_preferences_do_not_reward_a_particular_profession_or_region() -> None:
    service = ScoringService()
    filters = UserFilterDTO(remote_only=False, timezone=None, allowed_regions=[])
    jobs = [
        build_job(
            title=title,
            technologies=skills,
            remote_regions=regions,
            experience_level=experience,
            employment_type=employment,
            salary_min=salary,
            salary_max=salary,
            timezone_min_utc_offset=None,
            timezone_max_utc_offset=None,
        )
        for title, skills, regions, experience, employment, salary in (
            ("Python Developer", ["python"], ["latam"], "middle", "full_time", 90000),
            ("UX Designer", ["figma"], ["europe"], "senior", "contract", 70000),
            ("Accountant", ["excel"], ["uruguay"], "junior", "freelance", 60000),
        )
    ]

    results = [service.calculate(job, filters) for job in jobs]

    assert [result.score for result in results] == [50, 50, 50]
    assert all(not result.penalties for result in results)


def test_region_and_worldwide_compatibility_are_user_relative() -> None:
    service = ScoringService()
    jobs = {
        region: build_job(
            title="Role",
            technologies=[],
            remote=False,
            remote_regions=[region],
            experience_level=None,
            employment_type=None,
            salary_min=None,
            salary_max=None,
            timezone_min_utc_offset=None,
            timezone_max_utc_offset=None,
        )
        for region in ("latam", "europe", "worldwide")
    }
    latam = UserFilterDTO(allowed_regions=["latam"], remote_only=False, timezone=None)
    europe = UserFilterDTO(allowed_regions=["europe"], remote_only=False, timezone=None)
    latam_scores = {
        region: service.calculate(job, latam).score for region, job in jobs.items()
    }
    europe_scores = {
        region: service.calculate(job, europe).score for region, job in jobs.items()
    }

    assert latam_scores["latam"] > latam_scores["europe"]
    assert europe_scores["europe"] > europe_scores["latam"]
    assert latam_scores["worldwide"] == europe_scores["worldwide"]


@pytest.mark.parametrize(
    ("title", "keyword", "skill"),
    [
        ("Python Backend Developer", "backend", "python"),
        ("UX Designer", "designer", "figma"),
        ("Sales Manager", "sales", "salesforce"),
        ("Accountant", "accountant", "excel"),
        ("Customer Support Specialist", "support", "zendesk"),
    ],
)
def test_profession_neutral_profiles_can_reach_same_match_score(title, keyword, skill):
    job = build_job(
        title=title,
        description=f"Experienced {keyword} professional",
        technologies=[skill],
        remote=False,
        remote_regions=["worldwide"],
        experience_level=None,
        employment_type=None,
        salary_min=None,
        salary_max=None,
        timezone_min_utc_offset=None,
        timezone_max_utc_offset=None,
    )
    filters = UserFilterDTO(
        keywords=[keyword],
        preferred_technologies=[skill],
        allowed_regions=["worldwide"],
        remote_only=False,
        timezone=None,
    )

    assert ScoringService().calculate(job, filters).score == 100


def test_remote_bonus_requires_remote_user_preference() -> None:
    service = ScoringService()
    job = build_job(
        remote=True,
        remote_regions=[],
        technologies=[],
        experience_level=None,
        employment_type=None,
        salary_min=None,
        salary_max=None,
        timezone_min_utc_offset=None,
        timezone_max_utc_offset=None,
    )
    remote_preference = service.calculate(
        job, UserFilterDTO(remote_only=True, timezone=None, allowed_regions=[])
    )
    no_remote_preference = service.calculate(
        job, UserFilterDTO(remote_only=False, timezone=None, allowed_regions=[])
    )
    assert remote_preference.score > no_remote_preference.score
    assert "Remote matches user preference: +5" in remote_preference.matched_rules


def test_required_skills_get_proportional_completeness_bonus() -> None:
    job = build_job(
        title="Accountant",
        description="",
        technologies=["excel"],
        remote=False,
        remote_regions=[],
        experience_level=None,
        employment_type=None,
        salary_min=None,
        salary_max=None,
        timezone_min_utc_offset=None,
        timezone_max_utc_offset=None,
    )
    filters = UserFilterDTO(
        required_technologies=["excel", "salesforce"],
        timezone=None,
        allowed_regions=[],
        remote_only=False,
    )
    result = ScoringService().calculate(job, filters)
    assert result.score == 75
    assert "Required skills matched (1/2): +5" in result.matched_rules


def test_salary_and_employment_only_score_when_user_configures_them() -> None:
    service = ScoringService()
    job = build_job(
        title="Sales Manager",
        description="",
        technologies=[],
        remote=False,
        remote_regions=[],
        experience_level=None,
        employment_type="contract",
        salary_min=6000,
        salary_max=8000,
        salary_period="monthly",
        currency="USD",
        timezone_min_utc_offset=None,
        timezone_max_utc_offset=None,
    )
    empty = service.calculate(job, UserFilterDTO(timezone=None, allowed_regions=[]))
    configured = service.calculate(
        job,
        UserFilterDTO(
            min_salary=5000,
            currency="USD",
            employment_types=["contract"],
            remote_only=False,
            timezone=None,
            allowed_regions=[],
        ),
    )
    assert empty.score == 50
    assert configured.score == 100
    assert "Employment matches user preferences: +5" in configured.matched_rules
    assert "Salary meets user minimum: +5" in configured.matched_rules

    upper_bound_only = job.model_copy(update={"salary_min": None, "salary_max": 8000})
    uncertain = service.calculate(
        upper_bound_only,
        UserFilterDTO(
            min_salary=5000, remote_only=False, timezone=None, allowed_regions=[]
        ),
    )
    assert uncertain.score == 50


def test_timezone_score_uses_the_calling_users_timezone() -> None:
    job = build_job(
        title="Role",
        technologies=[],
        remote=False,
        remote_regions=[],
        experience_level=None,
        employment_type=None,
        salary_min=None,
        salary_max=None,
        timezone_min_utc_offset=1,
        timezone_max_utc_offset=3,
    )
    service = ScoringService()
    madrid = service.calculate(job, UserFilterDTO(timezone="Europe/Madrid"))
    tokyo = service.calculate(job, UserFilterDTO(timezone="Asia/Tokyo"))
    assert madrid.score > tokyo.score


def test_experience_scoring_uses_user_preferences_and_ignores_years() -> None:
    service = ScoringService()
    job = build_job(
        experience_level="senior",
        title="Senior Python Developer",
        description="Requires 5+ years of professional experience",
    )
    filters = UserFilterDTO(
        experience_levels=["senior"], remote_only=False, timezone=None
    )

    result = service.calculate(job, filters)

    assert "Experience matches user preferences: +10" in result.matched_rules
    assert not any("years of experience" in penalty for penalty in result.penalties)
    assert not result.penalties


def test_title_inferred_experience_is_compared_to_each_user() -> None:
    service = ScoringService()
    job = build_job(
        title="Senior Backend Engineer",
        experience_level=None,
        remote=False,
        remote_regions=[],
        timezone_min_utc_offset=None,
        timezone_max_utc_offset=None,
    )
    senior = service.calculate(
        job, UserFilterDTO(experience_levels=["senior"], timezone=None)
    )
    junior = service.calculate(
        job, UserFilterDTO(experience_levels=["junior"], timezone=None)
    )
    assert senior.score > junior.score
    assert "Experience matches user preferences: +10" in senior.matched_rules
    assert "Inferred experience differs from user preferences: -5" in junior.penalties


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
    assert not any("Timezone compatible" in entry for entry in distance.matched_rules)
    assert not any("Timezone differs" in entry for entry in distance.penalties)

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
        build_job(), UserFilterDTO(min_salary=80000, timezone="UTC")
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
    assert 0 <= bad.score <= 100


@pytest.mark.parametrize(
    "description,expected",
    [
        ("We've been growing for 12 years. Requires 2 years of experience.", 2),
        ("5+ years of professional experience", 5),
        ("Requires 5 years of <strong>professional experience</strong>.", 5),
        ("<p>Requires <b>5+</b> years of experience.</p>", 5),
        ("Requires 5 years' experience.", 5),
        ("Requires 5 years’ experience.", 5),
        ("Requires 5 years of hands-on experience.", 5),
        ("Requires 5 years of hands‑on experience.", 5),
        ("Requires 5&nbsp;years&#39; professional experience.", 5),
        ("<p>Company founded 12 years ago.</p><p>2 years’ experience.</p>", 2),
        ("<script>12 years of experience</script><p>2 years experience</p>", 2),
        ("5 years of hands-on experience; 2 years Python experience", 5),
        ("Company has existed for 12 years", None),
        ("<p>Company founded 12 years ago.</p><p>Experience is valued.</p>", None),
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


def test_remoteok_html_experience_scores_like_plain_text():
    from src.collectors.remoteok import RemoteOKCollector
    from src.services.normalization import NormalizationService

    raw = {
        "id": "review",
        "position": "Python Developer",
        "url": "https://example.com/job",
        "tags": ["python"],
        "description": "Requires 5 years of <strong>professional experience</strong>.",
    }
    job = NormalizationService().normalize(RemoteOKCollector.map_job(raw))
    plain = job.model_copy(
        update={"description": "Requires 5 years of professional experience."}
    )
    service = ScoringService()
    filters = UserFilterDTO()
    assert service.calculate(job, filters) == service.calculate(plain, filters)
    assert not any(
        "years of experience" in penalty
        for penalty in service.calculate(job, filters).penalties
    )
