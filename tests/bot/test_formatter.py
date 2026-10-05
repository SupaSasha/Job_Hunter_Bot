import pytest

from src.bot.formatter import build_job_keyboard, format_job_message
from src.schemas.job import JobDTO
from src.schemas.scoring import ScoreResult


@pytest.fixture
def job() -> JobDTO:
    return JobDTO(
        source="remoteok",
        external_id="1",
        title="Python <Backend> & Developer",
        company="Acme [Inc.]",
        url="https://example.com/1",
        remote=True,
        remote_regions=["latam"],
        salary_min=2500,
        salary_max=4000,
        currency="USD",
        salary_period="month",
        employment_type="full_time",
        technologies=["python", "fastapi", "postgresql", "docker"],
        experience_level="middle",
    )


def test_formatter_includes_fields_and_explanations(job: JobDTO) -> None:
    score = ScoreResult(
        score=87,
        matched_rules=["Python: +10", "Remote: +10"],
        penalties=["Senior level: -5"],
        warnings=["Timezone is not specified"],
    )
    message = format_job_message(job, score)
    for value in (
        "87%",
        job.title,
        job.company,
        "2,500–4,000 USD / month",
        "Remote · LATAM",
        "Full-time",
        "Python",
        "FastAPI",
        "PostgreSQL",
        "Docker",
        "Experience: Middle",
        "Source: Remote OK",
        "Matches:",
        "✅ Python: +10",
        "Penalties:",
        "⚠️ Senior level: -5",
        "Warnings:",
        "⚠️ Timezone is not specified",
    ):
        assert value in message


def test_unknown_salary_and_empty_sections(job: JobDTO) -> None:
    job.salary_min = job.salary_max = None
    message = format_job_message(job, ScoreResult(score=70, matched_rules=[" "]))
    assert "Salary not specified" in message
    for heading in ("Matches:", "Penalties:", "Warnings:"):
        assert heading not in message


@pytest.mark.parametrize(
    ("minimum", "maximum", "expected"),
    [(0, None, "From 0"), (None, 4000, "Up to 4,000")],
)
def test_partial_salary(
    job: JobDTO, minimum: int | None, maximum: int | None, expected: str
) -> None:
    job.salary_min, job.salary_max = minimum, maximum
    job.currency = job.salary_period = None
    message = format_job_message(job, ScoreResult(score=70))
    assert expected in message
    assert "USD" not in message
    assert "None" not in message


def test_long_unicode_message_fits_telegram(job: JobDTO) -> None:
    job.title = "🐍" * 10000
    message = format_job_message(
        job, ScoreResult(score=70, matched_rules=["🐍" * 5000])
    )
    assert len(message.encode("utf-16-le")) // 2 <= 4096
    assert message.endswith("…")


def test_keyboard_uses_small_callbacks_and_url() -> None:
    keyboard = build_job_keyboard(42, "https://example.com/42")["inline_keyboard"]
    assert keyboard[0] == [{"text": "Open vacancy", "url": "https://example.com/42"}]
    assert keyboard[1] == [
        {"text": "Save", "callback_data": "save:42"},
        {"text": "Not suitable", "callback_data": "reject:42"},
    ]
    assert all(len(button["callback_data"].encode()) <= 64 for button in keyboard[1])


@pytest.mark.parametrize("job_id", [0, -1, 10**70])
def test_invalid_callback_id(job_id: int) -> None:
    with pytest.raises(ValueError, match="callback_data"):
        build_job_keyboard(job_id, "https://example.com")


def test_invalid_url() -> None:
    with pytest.raises(ValueError, match="HTTP"):
        build_job_keyboard(1, "javascript:alert(1)")


@pytest.mark.parametrize(
    "source,label",
    [
        ("remoteok", "Remote OK"),
        ("weworkremotely", "We Work Remotely"),
        ("getonboard", "Get on Board"),
    ],
)
def test_shared_source_display_names(job, source, label):
    job.source = source
    assert f"Source: {label}" in format_job_message(job, ScoreResult(score=70))
