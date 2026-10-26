import pytest

from src.schemas.filters import UserFilterDTO
from src.schemas.job import JobDTO
from src.services.digests import select_digest_jobs
from src.services.filters import FilterService
from src.services.scoring import ScoringService


def job(**updates):
    values = dict(
        source="jooble",
        external_id="review",
        title="Accountant",
        url="https://example.com/review",
        remote=True,
        remote_regions=["worldwide"],
    )
    values.update(updates)
    return JobDTO(**values)


@pytest.mark.parametrize("regions", [[], ["worldwide"]])
def test_neutral_profile_is_not_blocked_by_default_delivery_threshold(regions):
    vacancy = job(remote_regions=regions)
    filters = UserFilterDTO(timezone="UTC")
    selected = select_digest_jobs([(1, vacancy)], filters, 70, 10)
    assert len(selected) == 1
    assert selected[0][2].score >= 70


@pytest.mark.parametrize(
    "skill,text",
    [
        ("excel", "Microsoft Excel"),
        ("postgresql", "Postgres"),
        ("nodejs", "Node.js"),
        ("fastapi", "Fast API"),
        ("ux research", "UX Research"),
    ],
)
def test_all_skill_preferences_match_description_with_the_same_aliases(skill, text):
    vacancy = job(description=f"Experience with {text} is required", technologies=[])
    assert (
        FilterService()
        .evaluate(vacancy, UserFilterDTO(required_technologies=[skill]))
        .accepted
    )
    assert (
        not FilterService()
        .evaluate(vacancy, UserFilterDTO(excluded_technologies=[skill]))
        .accepted
    )
    preferred = ScoringService().calculate(
        vacancy, UserFilterDTO(preferred_technologies=[skill])
    )
    assert any(
        "Preferred skills matched (1/1)" in rule for rule in preferred.matched_rules
    )
    required = ScoringService().calculate(
        vacancy, UserFilterDTO(required_technologies=[skill])
    )
    assert any(
        "Required skills matched (1/1)" in rule for rule in required.matched_rules
    )


@pytest.mark.parametrize(
    "amount,period,accepted",
    [
        (100, "hourly", True),
        (3000, "yearly", False),
        (30000, "annual", True),
        (29999, "year", False),
        (2500, "monthly", True),
        (2499, "month", False),
        (1000, None, True),
    ],
)
def test_minimum_salary_compares_only_monthly_equivalent_amounts(
    amount, period, accepted
):
    vacancy = job(salary_min=amount, currency="USD", salary_period=period)
    filters = UserFilterDTO(min_salary=2500, currency="USD")
    assert FilterService().evaluate(vacancy, filters).accepted is accepted
    scored = ScoringService().calculate(vacancy, filters)
    bonus = any("Salary meets user minimum" in rule for rule in scored.matched_rules)
    assert bonus is (accepted and period in {"annual", "monthly"})


def test_known_timezone_within_user_tolerance_outranks_unknown():
    filters = UserFilterDTO(timezone="UTC", timezone_tolerance_hours=4)
    known = job(timezone_min_utc_offset=4, timezone_max_utc_offset=4)
    unknown = job()
    assert FilterService().evaluate(known, filters).accepted
    assert (
        ScoringService().calculate(known, filters).score
        > ScoringService().calculate(unknown, filters).score
    )
    assert (
        not FilterService()
        .evaluate(known, filters.model_copy(update={"timezone_tolerance_hours": 0}))
        .accepted
    )
