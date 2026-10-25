from __future__ import annotations

import re

from src.collectors.text import html_to_text
from src.schemas.filters import UserFilterDTO
from src.schemas.job import JobDTO
from src.schemas.scoring import ScoreResult
from src.services.timezones import user_utc_offset
from src.services.tokens import normalize_technology

BASE_SCORE = 50

TECHNOLOGY_WEIGHTS = {
    "python": 10,
    "fastapi": 10,
    "postgresql": 5,
    "redis": 3,
    "celery": 3,
    "docker": 4,
}

TECHNOLOGY_LABELS = {
    "python": "Python",
    "fastapi": "FastAPI",
    "postgresql": "PostgreSQL",
    "redis": "Redis",
    "celery": "Celery",
    "docker": "Docker",
    "kubernetes": "Kubernetes",
    "nodejs": "Node.js",
    "javascript": "JavaScript",
    "typescript": "TypeScript",
}

REGION_BONUSES = {
    "worldwide": 10,
    "latam": 10,
    "uruguay": 10,
    "south_america": 8,
    "americas": 5,
}

EXPERIENCE_LEVEL_BONUSES = {
    "junior": 5,
    "middle": 5,
}

EXPERIENCE_LEVEL_PENALTIES = {
    "senior": -5,
    "lead": -10,
    "staff": -20,
    "principal": -20,
}

TITLE_SENIORITY_PENALTIES = {
    "senior": -5,
    "lead": -10,
    "staff": -20,
    "principal": -20,
    "architect": -15,
    "engineering manager": -20,
}

PREFERRED_TECH_BONUS = 4
MAX_PREFERRED_TECH_BONUS = 12
MAX_KEYWORD_BONUS = 9


class ScoringService:
    """Rank jobs for user interest using explainable score rules."""

    @staticmethod
    def _normalize_token(value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip().lower()
        return cleaned or None

    @staticmethod
    def _normalize_text(value: str | None) -> str:
        if value is None:
            return ""
        return re.sub(r"\s+", " ", str(value).strip()).lower()

    @staticmethod
    def _append_unique(items: list[str], value: str | None) -> None:
        if value is None or value in items:
            return
        items.append(value)

    _get_user_timezone_offset = staticmethod(user_utc_offset)

    @staticmethod
    def _infer_years_of_experience(description: str | None) -> int | None:
        description = html_to_text(description)
        if not description:
            return None

        # Require explicit experience context; do not match company/product age.
        pattern = (
            r"(?<![\w.])(?P<years>\d+)\+?\s*(?:years?|yrs?)[’']?\s+"
            r"(?:of\s+)?(?:[a-z+#]+(?:[-‑–][a-z+#]+)*\s+){0,3}experience\b"
        )
        found = [
            int(match.group("years"))
            for match in re.finditer(pattern, description, flags=re.IGNORECASE)
        ]

        if not found:
            return None
        return max(found)

    @classmethod
    def _infer_experience_level_from_title(cls, title: str | None) -> str | None:
        if not title:
            return None

        normalized = cls._normalize_text(title)
        if "senior" in normalized or "sr." in normalized:
            return "senior"
        if "engineering manager" in normalized:
            return "engineering manager"
        if "principal" in normalized:
            return "principal"
        if "staff" in normalized:
            return "staff"
        if "lead" in normalized:
            return "lead"
        if "architect" in normalized:
            return "architect"
        return None

    @classmethod
    def _technology_label(cls, technology: str) -> str:
        canonical = normalize_technology(technology)
        if canonical is None:
            return technology
        return TECHNOLOGY_LABELS.get(canonical, canonical.title())

    @classmethod
    def _score_technologies(
        cls,
        job: JobDTO,
        filters: UserFilterDTO,
        matched_rules: list[str],
        penalties: list[str],
    ) -> int:
        score = 0
        seen_technologies: set[str] = set()

        for technology in job.technologies:
            canonical = normalize_technology(technology)
            if canonical is None or canonical in seen_technologies:
                continue
            seen_technologies.add(canonical)
            if canonical in TECHNOLOGY_WEIGHTS:
                bonus = TECHNOLOGY_WEIGHTS[canonical]
                score += bonus
                cls._append_unique(
                    matched_rules,
                    f"{cls._technology_label(canonical)}: +{bonus}",
                )

        preferred_bonus_total = 0
        preferred_hits: list[str] = []
        for technology in filters.preferred_technologies:
            canonical = normalize_technology(technology)
            if canonical is None or canonical not in seen_technologies:
                continue
            preferred_bonus_total += PREFERRED_TECH_BONUS
            preferred_hits.append(
                f"Preferred technology {cls._technology_label(canonical)}: "
                f"+{PREFERRED_TECH_BONUS}"
            )

        if preferred_bonus_total > MAX_PREFERRED_TECH_BONUS:
            preferred_bonus_total = MAX_PREFERRED_TECH_BONUS

        if preferred_bonus_total:
            for entry in preferred_hits:
                if preferred_bonus_total <= 0:
                    break
                cls._append_unique(matched_rules, entry)
            score += preferred_bonus_total

        return score

    @classmethod
    def _score_keywords(
        cls,
        job: JobDTO,
        filters: UserFilterDTO,
        matched_rules: list[str],
    ) -> int:
        haystack = f"{job.title or ''} {job.description or ''}".lower()
        score = 0
        matched_keywords = []

        for keyword in filters.keywords:
            normalized_keyword = cls._normalize_text(keyword)
            if not normalized_keyword:
                continue
            pattern = rf"(?<![a-z0-9]){re.escape(normalized_keyword)}(?![a-z0-9])"
            if re.search(pattern, haystack):
                matched_keywords.append(normalized_keyword)

        unique_keywords = []
        for keyword in matched_keywords:
            if keyword not in unique_keywords:
                unique_keywords.append(keyword)

        for keyword in unique_keywords:
            if score >= MAX_KEYWORD_BONUS:
                break
            score += 3
            cls._append_unique(matched_rules, f"Keyword: {keyword}: +3")

        return score

    @classmethod
    def _score_region(
        cls,
        job: JobDTO,
        matched_rules: list[str],
        warnings: list[str],
        penalties: list[str],
    ) -> int:
        if not job.remote_regions:
            cls._append_unique(penalties, "Region is not specified: -2")
            cls._append_unique(warnings, "Remote region is unknown")
            return -2

        best_region = None
        best_bonus = 0
        for region in job.remote_regions:
            canonical = cls._normalize_token(region)
            if canonical is None:
                continue
            if canonical in REGION_BONUSES:
                bonus = REGION_BONUSES[canonical]
                if bonus > best_bonus:
                    best_region = canonical
                    best_bonus = bonus

        if best_region is None:
            cls._append_unique(penalties, "Region is not specified: -2")
            cls._append_unique(warnings, "Remote region is unknown")
            return -2

        label = {
            "worldwide": "Worldwide",
            "latam": "LATAM",
            "uruguay": "Uruguay",
            "south_america": "South America",
            "americas": "Americas",
        }.get(best_region, best_region.title())

        cls._append_unique(matched_rules, f"{label} region: +{best_bonus}")
        return best_bonus

    @classmethod
    def _score_timezone(
        cls,
        job: JobDTO,
        filters: UserFilterDTO,
        matched_rules: list[str],
        penalties: list[str],
        warnings: list[str],
    ) -> int:
        user_offset = cls._get_user_timezone_offset(filters.timezone)
        vacancy_min = job.timezone_min_utc_offset
        vacancy_max = job.timezone_max_utc_offset

        if vacancy_min is None and vacancy_max is None:
            cls._append_unique(penalties, "Timezone is not specified: -2")
            cls._append_unique(warnings, "Timezone is not specified")
            return -2

        if user_offset is None:
            return 0

        if vacancy_min is not None and vacancy_max is not None:
            if vacancy_min <= user_offset <= vacancy_max:
                cls._append_unique(matched_rules, "Timezone compatible: +10")
                return 10

            distance = min(
                abs(user_offset - vacancy_min),
                abs(user_offset - vacancy_max),
            )
            if distance <= 1:
                cls._append_unique(
                    matched_rules, f"Timezone distance: {distance:g} hour(s): +7"
                )
                return 7
            if distance <= 2:
                cls._append_unique(
                    matched_rules, f"Timezone distance: {distance:g} hours: +4"
                )
                return 4
            if distance <= 3:
                cls._append_unique(
                    matched_rules, f"Timezone distance: {distance:g} hours: 0"
                )
                return 0
            if distance <= 4:
                cls._append_unique(
                    penalties, f"Timezone distance: {distance:g} hours: -10"
                )
                return -10
            cls._append_unique(penalties, "Timezone distance: 5+ hours: -20")
            return -20

        return 0

    @classmethod
    def _score_experience(
        cls,
        job: JobDTO,
        matched_rules: list[str],
        penalties: list[str],
        warnings: list[str],
    ) -> int:
        score = 0

        if job.experience_level is not None:
            level = cls._normalize_token(job.experience_level)
            if level in EXPERIENCE_LEVEL_BONUSES:
                bonus = EXPERIENCE_LEVEL_BONUSES[level]
                score += bonus
                cls._append_unique(matched_rules, f"{level.title()} level: +{bonus}")
            if level in EXPERIENCE_LEVEL_PENALTIES:
                penalty = EXPERIENCE_LEVEL_PENALTIES[level]
                score += penalty
                cls._append_unique(penalties, f"{level.title()} level: {penalty}")
            return score

        inferred_level = cls._infer_experience_level_from_title(job.title)
        if inferred_level is not None and inferred_level in TITLE_SENIORITY_PENALTIES:
            penalty = TITLE_SENIORITY_PENALTIES[inferred_level]
            score += penalty
            cls._append_unique(
                penalties,
                f"Title seniority: {inferred_level.title()}: {penalty}",
            )
            return score

        cls._append_unique(warnings, "Experience level is not specified")
        return 0

    @classmethod
    def _score_experience_years(
        cls,
        job: JobDTO,
        penalties: list[str],
    ) -> int:
        years = cls._infer_years_of_experience(job.description)
        if years is None:
            return 0

        if years <= 2:
            return 0
        if years == 3:
            penalty = -2
        elif years == 4:
            penalty = -5
        elif 5 <= years <= 6:
            penalty = -10
        else:
            penalty = -20

        cls._append_unique(
            penalties,
            f"Requires {years}+ years of experience: {penalty}",
        )
        return penalty

    @classmethod
    def _score_salary(
        cls,
        job: JobDTO,
        penalties: list[str],
        warnings: list[str],
    ) -> int:
        if job.salary_min is None and job.salary_max is None:
            cls._append_unique(penalties, "Salary is not specified: -2")
            cls._append_unique(warnings, "Salary is not specified")
            return -2
        return 0

    @classmethod
    def _score_employment_type(
        cls,
        job: JobDTO,
        matched_rules: list[str],
        warnings: list[str],
    ) -> int:
        if job.employment_type is None:
            cls._append_unique(warnings, "Employment type is not specified")
            return 0
        if job.employment_type == "full_time":
            cls._append_unique(matched_rules, "Full-time: +3")
            return 3
        return 0

    def calculate(self, job: JobDTO, filters: UserFilterDTO) -> ScoreResult:
        matched_rules: list[str] = ["Base score: +50"]
        penalties: list[str] = []
        warnings: list[str] = []

        score = BASE_SCORE
        score += self._score_technologies(job, filters, matched_rules, penalties)
        score += self._score_keywords(job, filters, matched_rules)
        if job.remote:
            self._append_unique(matched_rules, "Remote: +10")
            score += 10
        score += self._score_region(job, matched_rules, warnings, penalties)
        score += self._score_timezone(job, filters, matched_rules, penalties, warnings)
        score += self._score_experience(job, matched_rules, penalties, warnings)
        score += self._score_experience_years(job, penalties)
        score += self._score_salary(job, penalties, warnings)
        score += self._score_employment_type(job, matched_rules, warnings)

        if score < 0:
            score = 0
        elif score > 100:
            score = 100

        return ScoreResult(
            score=score,
            matched_rules=matched_rules,
            penalties=penalties,
            warnings=warnings,
        )
