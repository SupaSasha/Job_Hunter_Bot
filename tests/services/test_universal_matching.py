import pytest

from src.schemas.filters import UserFilterDTO
from src.schemas.job import JobDTO
from src.services.filters import FilterService
from src.services.normalization import NormalizationService
from src.services.region_compatibility import regions_compatible
from src.services.regions import normalize_country
from src.services.scoring import ScoringService


def job(**values):
    return JobDTO(
        source="remoteok",
        external_id="generic",
        url="https://example.com/generic",
        title=values.pop("title", "Accountant"),
        remote=True,
        **values,
    )


@pytest.mark.parametrize(
    "title,keyword,skills",
    [
        ("Python Backend Developer", "python", ["fastapi"]),
        ("Sales Manager", "sales", ["salesforce", "b2b sales"]),
        ("UX Designer", "designer", ["figma", "ux research"]),
        ("Accountant", "accountant", ["excel", "quickbooks"]),
        ("Recruiter", "recruiter", ["talent acquisition"]),
        ("Customer Support Specialist", "customer support", ["customer support"]),
    ],
)
def test_generic_profiles_filter_and_rank_matching_jobs(title, keyword, skills):
    filters = UserFilterDTO(
        keywords=[keyword], required_technologies=skills, preferred_technologies=skills
    )
    matching = NormalizationService().normalize(job(title=title, technologies=skills))
    other = job(title="Unrelated vacancy")
    assert FilterService().evaluate(matching, filters).accepted
    assert ScoringService().calculate(matching, filters).score >= 90
    assert not FilterService().evaluate(other, filters).accepted
    assert (
        ScoringService().calculate(matching, filters).score
        > ScoringService().calculate(other, filters).score
    )
    excluded = filters.model_copy(update={"excluded_technologies": skills})
    assert not FilterService().evaluate(matching, excluded).accepted


@pytest.mark.parametrize(
    "skill",
    [
        "ux research",
        "b2b sales",
        "customer support",
        "talent acquisition",
        "бухгалтерия",
    ],
)
def test_multiword_and_unicode_skills_match_description(skill):
    filters = UserFilterDTO(preferred_technologies=[skill], allowed_regions=[])
    result = ScoringService().calculate(
        job(description=f"Experience with {skill} required"), filters
    )
    assert result.score == 100


@pytest.mark.parametrize(
    "title",
    [
        "Sales Manager",
        "Director",
        "Leadership Consultant",
        "Staff Accountant",
        "Middle School Teacher",
    ],
)
def test_profession_titles_do_not_infer_it_hierarchy(title):
    assert ScoringService._infer_experience_level_from_title(title) is None


@pytest.mark.parametrize(
    "experience", [None, "unknown", "not_applicable", "executive", "senior, lead"]
)
def test_noncomparable_experience_does_not_reject(experience):
    assert (
        FilterService()
        .evaluate(
            job(experience_level=experience),
            UserFilterDTO(experience_levels=["senior"]),
        )
        .accepted
    )


@pytest.mark.parametrize(
    "region,allowed,expected",
    [
        ("Spain", ["europe"], True),
        ("ES", ["eu"], True),
        ("Canada", ["north_america"], True),
        ("CA", ["americas"], True),
        ("UY", ["latam"], True),
        ("Chile", ["south_america"], True),
        ("Japan", ["apac"], True),
        ("South Africa", ["emea"], True),
        ("Europe", ["Spain"], True),
        ("Uruguay", ["spain"], False),
        ("Germany", ["latam"], False),
        ("Uruguay", ["europe"], False),
        ("Uruguay", ["worldwide"], True),
        ("worldwide", ["Japan"], True),
        ("Spain", [], True),
        ("US only", ["Canada"], False),
    ],
)
def test_global_country_and_region_compatibility(region, allowed, expected):
    assert regions_compatible(region, allowed) is expected


def test_new_user_does_not_exclude_us_jobs_and_legacy_flags_are_ignored():
    filters = UserFilterDTO(allowed_regions=["europe"], latam_allowed=True)
    assert not FilterService().evaluate(job(remote_regions=["latam"]), filters).accepted
    assert (
        FilterService()
        .evaluate(job(remote_regions=["us_only"]), UserFilterDTO())
        .accepted
    )
    assert normalize_country("UY") == normalize_country("Uruguay") == "uruguay"


def test_keywords_use_unicode_boundaries():
    filters = UserFilterDTO(keywords=["бухгалтер"])
    assert FilterService().evaluate(job(title="Главный бухгалтер"), filters).accepted
    assert not FilterService().evaluate(job(title="бухгалтерия"), filters).accepted


def test_five_profiles_rank_relevant_fixture_jobs_in_top_three():
    from src.scripts.validate_profiles import validate_profiles

    results = validate_profiles()
    assert {result["profile"] for result in results} == {
        "Backend",
        "Design",
        "Sales",
        "Accounting",
        "Support",
    }
    assert all(len(result["jobs"]) == 3 for result in results)


@pytest.mark.parametrize("employment", ["temporary", "seasonal", "permanent"])
def test_employment_types_are_not_mapped_to_full_time(employment):
    normalized = NormalizationService().normalize(job(employment_type=employment))
    assert normalized.employment_type == employment


def test_currency_preferences_never_convert_or_score_other_currencies():
    filters = UserFilterDTO(currency="JPY", min_salary=100000)
    matching = job(currency="JPY", salary_min=200000, salary_period="monthly")
    different = job(currency="USD", salary_min=200000, salary_period="monthly")
    assert FilterService().evaluate(matching, filters).accepted
    assert not FilterService().evaluate(different, filters).accepted
    assert (
        ScoringService().calculate(matching, filters).score
        > ScoringService().calculate(different, filters).score
    )
    assert FilterService().evaluate(different, UserFilterDTO(currency=None)).accepted


def test_salary_minimum_never_compares_different_currencies():
    filters = UserFilterDTO(currency="JPY", min_salary=100000)
    result = FilterService().evaluate(job(currency="USD", salary_min=1000), filters)
    assert result.reasons == ["Currency mismatch: USD"]
    assert (
        FilterService().evaluate(job(currency=None, salary_min=1000), filters).accepted
    )
    assert (
        not FilterService()
        .evaluate(
            job(currency="JPY", salary_min=1000, salary_period="monthly"), filters
        )
        .accepted
    )


@pytest.mark.parametrize("regions", [[], ["worldwide"]])
def test_profession_and_global_region_neutrality(regions):
    filters = UserFilterDTO(allowed_regions=regions, remote_only=False, timezone=None)
    titles = [
        "Python Developer",
        "UX Designer",
        "Sales Manager",
        "Accountant",
        "Recruiter",
    ]
    scores = [
        ScoringService()
        .calculate(job(title=title, remote_regions=[region]), filters)
        .score
        for title in titles
        for region in ("latam", "europe", "asia")
    ]
    assert len(set(scores)) == 1


def test_worldwide_defaults_across_dto_and_bootstrap():
    from src.models.user_filter import DEFAULT_REGIONS
    from src.services.default_filters import default_user_filters
    from src.services.user_filters import filter_defaults

    for filters in (
        UserFilterDTO(),
        default_user_filters(),
        UserFilterDTO(**filter_defaults()),
    ):
        assert filters.allowed_regions == list(DEFAULT_REGIONS) == ["worldwide"]
        assert (
            filters.keywords
            == filters.required_technologies
            == filters.preferred_technologies
            == filters.excluded_technologies
            == []
        )
        assert filters.exclude_us_only is False
