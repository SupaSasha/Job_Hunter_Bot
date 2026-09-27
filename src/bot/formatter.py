from urllib.parse import urlsplit

from src.schemas.job import JobDTO
from src.schemas.scoring import ScoreResult

_TECHNOLOGIES = {
    "python": "🐍 Python",
    "fastapi": "⚡ FastAPI",
    "postgresql": "🐘 PostgreSQL",
    "docker": "🐳 Docker",
    "redis": "Redis",
    "celery": "Celery",
}
_REGIONS = {
    "worldwide": "Worldwide",
    "latam": "LATAM",
    "south_america": "South America",
    "us_only": "US only",
    "uruguay": "Uruguay",
}
_EMPLOYMENT = {"full_time": "Full-time", "part_time": "Part-time"}
_PERIODS = {"month": "month", "year": "year", "hour": "hour"}


def _truncate(value: str, limit: int) -> str:
    # Conservatively count UTF-16 units, including emoji surrogate pairs.
    encoded = value.encode("utf-16-le")
    if len(encoded) <= limit * 2:
        return value
    return encoded[: (limit - 1) * 2].decode("utf-16-le", errors="ignore") + "…"


def _salary(job: JobDTO) -> str:
    if job.salary_min is None and job.salary_max is None:
        return "Salary not specified"
    if job.salary_min is not None and job.salary_max is not None:
        amount = f"{job.salary_min:,}–{job.salary_max:,}"
    elif job.salary_min is not None:
        amount = f"From {job.salary_min:,}"
    else:
        amount = f"Up to {job.salary_max:,}"
    currency = f" {job.currency}" if job.currency else ""
    period = (
        f" / {_PERIODS.get(job.salary_period, job.salary_period)}"
        if job.salary_period
        else ""
    )
    return amount + currency + period


def format_job_message(job: JobDTO, score: ScoreResult) -> str:
    regions = ", ".join(_REGIONS.get(r, r) for r in job.remote_regions)
    location = regions or job.location or "Region not specified"
    if job.remote:
        location = f"Remote · {location}"
    employment = _EMPLOYMENT.get(
        job.employment_type, job.employment_type or "Employment type not specified"
    )
    technologies = (
        "\n".join(_TECHNOLOGIES.get(t, t) for t in job.technologies)
        or "Technologies not specified"
    )
    sections = [
        f"🔥 Match: {score.score}%",
        f"{_truncate(job.title, 240)}\n"
        f"{_truncate(job.company or 'Company not specified', 160)}",
        f"💰 {_salary(job)}\n🌎 {_truncate(location, 300)}\n🕐 {employment}",
        _truncate(technologies, 600),
        f"Experience: {job.experience_level or 'not specified'}\n"
        f"Source: {'Remote OK' if job.source == 'remoteok' else job.source}",
    ]
    for title, items, icon in (
        ("Matches", score.matched_rules, "✅"),
        ("Penalties", score.penalties, "⚠️"),
        ("Warnings", score.warnings, "⚠️"),
    ):
        entries = [item for item in items if item.strip()]
        if entries:
            sections.append(title + ":\n" + "\n".join(f"{icon} {v}" for v in entries))
    return _truncate("\n\n".join(sections), 4096)


def build_job_keyboard(job_id: int, url: str) -> dict:
    parsed = urlsplit(url)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        raise ValueError("Job URL must be an absolute HTTP(S) URL")
    callbacks = [f"save:{job_id}", f"reject:{job_id}"]
    if job_id <= 0 or any(len(value.encode("utf-8")) > 64 for value in callbacks):
        raise ValueError("Job ID does not fit Telegram callback_data")
    return {
        "inline_keyboard": [
            [{"text": "View job", "url": url}],
            [
                {"text": "Save", "callback_data": callbacks[0]},
                {"text": "Not suitable", "callback_data": callbacks[1]},
            ],
        ]
    }
