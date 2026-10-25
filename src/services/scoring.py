from __future__ import annotations

import re

from src.collectors.text import html_to_text
from src.schemas.filters import UserFilterDTO
from src.schemas.job import JobDTO
from src.schemas.scoring import ScoreResult
from src.services.region_compatibility import regions_compatible
from src.services.timezones import user_utc_offset
from src.services.tokens import contains_term, normalize_technology

BASE_SCORE = 50
KEYWORD_WEIGHT = 15
PREFERRED_SKILL_WEIGHT = 20
REQUIRED_SKILL_WEIGHT = 10
REGION_WEIGHT = 10
TIMEZONE_WEIGHT = 10
EMPLOYMENT_WEIGHT = 5
EXPERIENCE_WEIGHT = 10
SALARY_WEIGHT = 5
REMOTE_WEIGHT = 5


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
        if re.search(r"\b(?:senior\b|sr\.)", normalized):
            return "senior"
        if re.search(r"\bprincipal\b", normalized):
            return "principal"
        if re.search(r"\blead\b", normalized):
            return "lead"
        if re.search(r"\b(?:junior|entry[- ]level)\b", normalized):
            return "junior"
        if re.search(r"\bmid[- ]level\b", normalized):
            return "middle"
        return None

    @classmethod
    def _score_skill_preferences(
        cls,
        job: JobDTO,
        filters: UserFilterDTO,
        matched_rules: list[str],
    ) -> int:
        skills = list(
            dict.fromkeys(
                canonical
                for item in job.technologies
                if (canonical := normalize_technology(item))
            )
        )
        haystack = cls._normalize_text(
            f"{job.title or ''} {html_to_text(job.description)}"
        )

        def matches(item: str) -> bool:
            canonical = normalize_technology(item)
            if canonical is None:
                return False
            if canonical in skills:
                return True
            return contains_term(haystack, canonical)

        preferred = list(
            dict.fromkeys(
                canonical
                for item in filters.preferred_technologies
                if (canonical := normalize_technology(item))
            )
        )
        preferred_matches = [item for item in preferred if matches(item)]
        score = (
            round(PREFERRED_SKILL_WEIGHT * len(preferred_matches) / len(preferred))
            if preferred
            else 0
        )
        if score:
            cls._append_unique(
                matched_rules,
                "Preferred skills matched "
                f"({len(preferred_matches)}/{len(preferred)}): +{score}",
            )

        required = list(
            dict.fromkeys(
                canonical
                for item in filters.required_technologies
                if (canonical := normalize_technology(item))
            )
        )
        required_matches = [item for item in required if item in skills]
        required_score = (
            round(REQUIRED_SKILL_WEIGHT * len(required_matches) / len(required))
            if required
            else 0
        )
        if required_score:
            cls._append_unique(
                matched_rules,
                "Required skills matched "
                f"({len(required_matches)}/{len(required)}): +{required_score}",
            )
        return score + required_score

    @classmethod
    def _score_keywords(
        cls,
        job: JobDTO,
        filters: UserFilterDTO,
        matched_rules: list[str],
    ) -> int:
        haystack = f"{job.title or ''} {html_to_text(job.description)}".lower()
        matched_keywords = []

        for keyword in filters.keywords:
            normalized_keyword = cls._normalize_text(keyword)
            if not normalized_keyword:
                continue
            if contains_term(haystack, normalized_keyword):
                matched_keywords.append(normalized_keyword)

        unique_keywords = []
        for keyword in matched_keywords:
            if keyword not in unique_keywords:
                unique_keywords.append(keyword)

        keywords = list(
            dict.fromkeys(
                normalized
                for keyword in filters.keywords
                if (normalized := cls._normalize_text(keyword))
            )
        )
        score = (
            round(KEYWORD_WEIGHT * len(unique_keywords) / len(keywords))
            if keywords
            else 0
        )
        if score:
            cls._append_unique(
                matched_rules,
                f"Keywords matched ({len(unique_keywords)}/{len(keywords)}): +{score}",
            )
        return score

    @classmethod
    def _score_region(
        cls,
        job: JobDTO,
        filters: UserFilterDTO,
        matched_rules: list[str],
        warnings: list[str],
        penalties: list[str],
    ) -> int:
        allowed = list(filters.allowed_regions)
        if not allowed:
            return 0
        if not job.remote_regions:
            cls._append_unique(penalties, "Region is not specified: -2")
            cls._append_unique(warnings, "Remote region is unknown")
            return -2
        if any(regions_compatible(region, allowed) for region in job.remote_regions):
            cls._append_unique(
                matched_rules, f"Region matches user preferences: +{REGION_WEIGHT}"
            )
            return REGION_WEIGHT
        return 0

    @classmethod
    def _score_timezone(
        cls,
        job: JobDTO,
        filters: UserFilterDTO,
        matched_rules: list[str],
        penalties: list[str],
        warnings: list[str],
    ) -> int:
        timezone = filters.timezone
        if timezone is None:
            return 0
        user_offset = cls._get_user_timezone_offset(timezone)
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
                cls._append_unique(
                    matched_rules, f"Timezone compatible: +{TIMEZONE_WEIGHT}"
                )
                return TIMEZONE_WEIGHT

            distance = min(
                abs(user_offset - vacancy_min),
                abs(user_offset - vacancy_max),
            )
            if distance <= 1:
                cls._append_unique(matched_rules, "Timezone within 1 hour: +7")
                return 7
            if distance <= 2:
                cls._append_unique(matched_rules, "Timezone within 2 hours: +4")
                return 4
            if distance <= 3:
                cls._append_unique(
                    matched_rules,
                    f"Timezone difference: {distance:g} hours: no adjustment",
                )
                return 0
            if distance <= 4:
                cls._append_unique(
                    penalties, f"Timezone differs by {distance:g} hours: -5"
                )
                return -5
            cls._append_unique(
                penalties, f"Timezone differs by {distance:g}+ hours: -10"
            )
            return -10

        return 0

    @classmethod
    def _score_experience(
        cls,
        job: JobDTO,
        filters: UserFilterDTO,
        matched_rules: list[str],
        penalties: list[str],
        warnings: list[str],
    ) -> int:
        preferred = {
            value.strip().casefold()
            for value in filters.experience_levels
            if value.strip()
        }
        if not preferred:
            return 0
        comparable = {"junior", "middle", "senior", "lead", "staff", "principal"}
        explicit = cls._normalize_token(job.experience_level)
        inferred_level = explicit not in comparable
        level = (
            explicit
            if explicit in comparable
            else cls._infer_experience_level_from_title(job.title)
        )
        if level is None:
            cls._append_unique(penalties, "Experience level is unknown: -2")
            cls._append_unique(warnings, "Experience level is not specified")
            return -2
        if level in preferred:
            cls._append_unique(
                matched_rules,
                f"Experience matches user preferences: +{EXPERIENCE_WEIGHT}",
            )
            return EXPERIENCE_WEIGHT
        if inferred_level:
            cls._append_unique(
                penalties, "Inferred experience differs from user preferences: -5"
            )
            return -5
        return 0

    @classmethod
    def _score_salary(
        cls,
        job: JobDTO,
        filters: UserFilterDTO,
        matched_rules: list[str],
        penalties: list[str],
        warnings: list[str],
    ) -> int:
        if filters.min_salary is None and filters.currency is None:
            return 0
        if job.salary_min is None and job.salary_max is None:
            cls._append_unique(penalties, "Salary is not specified: -2")
            cls._append_unique(warnings, "Salary is not specified")
            return -2
        if filters.currency:
            if not job.currency:
                cls._append_unique(penalties, "Salary currency is unknown: -2")
                cls._append_unique(warnings, "Salary currency is not specified")
                return -2
            if job.currency.casefold() != filters.currency.casefold():
                return 0
        salary_value = job.salary_min
        if filters.min_salary is None or (
            salary_value is not None and salary_value >= filters.min_salary
        ):
            cls._append_unique(
                matched_rules, f"Salary meets user minimum: +{SALARY_WEIGHT}"
            )
            return SALARY_WEIGHT
        return 0

    @classmethod
    def _score_employment_type(
        cls,
        job: JobDTO,
        filters: UserFilterDTO,
        matched_rules: list[str],
        penalties: list[str],
        warnings: list[str],
    ) -> int:
        preferred = {value.casefold() for value in filters.employment_types}
        if not preferred:
            return 0
        if job.employment_type is None:
            cls._append_unique(penalties, "Employment type is unknown: -2")
            cls._append_unique(warnings, "Employment type is not specified")
            return -2
        if job.employment_type.casefold() in preferred:
            cls._append_unique(
                matched_rules,
                f"Employment matches user preferences: +{EMPLOYMENT_WEIGHT}",
            )
            return EMPLOYMENT_WEIGHT
        return 0

    def calculate(
        self,
        job: JobDTO,
        filters: UserFilterDTO,
    ) -> ScoreResult:
        matched_rules: list[str] = ["Base score: +50"]
        penalties: list[str] = []
        warnings: list[str] = []

        score = BASE_SCORE
        score += self._score_skill_preferences(job, filters, matched_rules)
        score += self._score_keywords(job, filters, matched_rules)
        if filters.remote_only and job.remote:
            self._append_unique(
                matched_rules, f"Remote matches user preference: +{REMOTE_WEIGHT}"
            )
            score += REMOTE_WEIGHT
        score += self._score_region(job, filters, matched_rules, warnings, penalties)
        score += self._score_timezone(job, filters, matched_rules, penalties, warnings)
        score += self._score_experience(
            job, filters, matched_rules, penalties, warnings
        )
        score += self._score_salary(job, filters, matched_rules, penalties, warnings)
        score += self._score_employment_type(
            job, filters, matched_rules, penalties, warnings
        )

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
