from urllib.parse import urlsplit

from src.i18n import DEFAULT_LANGUAGE, Language, display_label, t
from src.schemas.job import JobDTO
from src.schemas.scoring import ScoreResult
from src.services.collector_policy import source_display_name

_TECHNOLOGIES = {
    "python": "🐍 Python",
    "fastapi": "⚡ FastAPI",
    "postgresql": "🐘 PostgreSQL",
    "docker": "🐳 Docker",
    "redis": "Redis",
    "celery": "Celery",
}


def _truncate(value: str, limit: int) -> str:
    # Conservatively count UTF-16 units, including emoji surrogate pairs.
    encoded = value.encode("utf-16-le")
    if len(encoded) <= limit * 2:
        return value
    return encoded[: (limit - 1) * 2].decode("utf-16-le", errors="ignore") + "…"


def _salary(job: JobDTO, language: Language = DEFAULT_LANGUAGE) -> str:
    if job.salary_min is None and job.salary_max is None:
        return t("job.salary_missing", language)
    if job.salary_min is not None and job.salary_max is not None:
        amount = f"{job.salary_min:,}–{job.salary_max:,}"
    elif job.salary_min is not None:
        amount = t("job.salary_from", language, amount=f"{job.salary_min:,}")
    else:
        amount = t("job.salary_up_to", language, amount=f"{job.salary_max:,}")
    currency = f" {job.currency}" if job.currency else ""
    period = (
        f" / {display_label(job.salary_period, language)}" if job.salary_period else ""
    )
    return amount + currency + period


def format_job_message(
    job: JobDTO, score: ScoreResult, language: Language = DEFAULT_LANGUAGE
) -> str:
    regions = ", ".join(
        display_label(region, language) for region in job.remote_regions
    )
    location = regions or job.location or t("job.region_missing", language)
    if job.remote:
        location = f"{t('job.remote', language)} · {location}"
    employment = (
        display_label(job.employment_type, language)
        if job.employment_type
        else t("job.employment_missing", language)
    )
    technologies = "\n".join(
        _TECHNOLOGIES.get(value, value) for value in job.technologies
    ) or t("job.technologies_missing", language)
    experience = (
        display_label(job.experience_level, language)
        if job.experience_level
        else t("common.not_specified", language)
    )
    company = _truncate(job.company or t("job.company_missing", language), 160)
    sections = [
        t("job.match", language, score=score.score),
        _truncate(job.title, 240),
        f"{t('job.company', language)}: {company}",
        f"💰 {t('job.salary', language)}: {_salary(job, language)}\n"
        f"🌎 {t('job.region', language)}: {_truncate(location, 300)}\n"
        f"🕐 {t('job.employment', language)}: {employment}",
        f"{t('job.technologies', language)}:\n{_truncate(technologies, 600)}",
        f"{t('job.experience', language)}: {experience}\n"
        f"{t('job.source', language)}: {source_display_name(job.source)}",
    ]
    return _truncate("\n\n".join(sections), 4096)


def build_job_keyboard(
    job_id: int, url: str, language: Language = DEFAULT_LANGUAGE
) -> dict:
    parsed = urlsplit(url)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        raise ValueError("Job URL must be an absolute HTTP(S) URL")
    callbacks = [f"save:{job_id}", f"reject:{job_id}"]
    if job_id <= 0 or any(len(value.encode("utf-8")) > 64 for value in callbacks):
        raise ValueError("Job ID does not fit Telegram callback_data")
    return {
        "inline_keyboard": [
            [{"text": t("job.open", language), "url": url}],
            [
                {"text": t("job.save", language), "callback_data": callbacks[0]},
                {"text": t("job.reject", language), "callback_data": callbacks[1]},
            ],
        ]
    }
