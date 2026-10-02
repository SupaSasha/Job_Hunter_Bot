from datetime import UTC, datetime

import pytest

from src.schemas.filters import UserFilterDTO
from src.schemas.job import JobDTO
from src.services.filters import FilterService
from src.services.normalization import NormalizationService
from src.services.scoring import ScoringService
from src.services.timezones import user_utc_offset
from src.services.tokens import normalize_technology


@pytest.mark.parametrize(
    "value,expected",
    [
        ("C++", "c++"),
        ("C#", "c#"),
        ("C", "c"),
        ("postgres", "postgresql"),
        ("fast api", "fastapi"),
    ],
)
def test_technology_tokens_preserve_symbols_and_aliases(value, expected):
    assert normalize_technology(value) == expected
    assert NormalizationService._canonicalize_technology(value) == expected


@pytest.mark.parametrize(
    "required,accepted", [("C", False), ("C#", False), ("C++", True)]
)
def test_filter_and_preference_do_not_match_different_c_languages(required, accepted):
    job = JobDTO(
        source="test",
        external_id="1",
        title="Developer",
        url="https://example.com",
        technologies=["C++"],
    )
    filters = UserFilterDTO(
        required_technologies=[required],
        preferred_technologies=[required],
        remote_only=False,
    )
    assert FilterService().evaluate(job, filters).accepted is accepted
    score = ScoringService().calculate(job, filters)
    assert any("Preferred technology" in r for r in score.matched_rules) is accepted


@pytest.mark.parametrize(
    "zone,date,expected",
    [
        ("Asia/Kolkata", datetime(2026, 1, 1, tzinfo=UTC), 5.5),
        ("America/St_Johns", datetime(2026, 1, 1, tzinfo=UTC), -3.5),
        ("America/St_Johns", datetime(2026, 7, 1, tzinfo=UTC), -2.5),
    ],
)
def test_fractional_timezone_and_dst(zone, date, expected):
    assert user_utc_offset(zone, date) == expected
    assert ScoringService._get_user_timezone_offset(zone, date) == expected
    assert FilterService._get_user_timezone_offset(zone, date) == expected


def test_fractional_distance_does_not_fall_into_largest_penalty(monkeypatch):
    monkeypatch.setattr(ScoringService, "_get_user_timezone_offset", lambda _: -3.5)
    rules, penalties, warnings = [], [], []
    job = JobDTO(
        source="test",
        external_id="1",
        title="Developer",
        url="https://example.com",
        timezone_min_utc_offset=-3,
        timezone_max_utc_offset=-3,
    )
    assert (
        ScoringService._score_timezone(job, UserFilterDTO(), rules, penalties, warnings)
        == 7
    )
    assert not penalties
