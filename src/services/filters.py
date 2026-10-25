from __future__ import annotations

from src.collectors.text import html_to_text
from src.schemas.filters import FilterResult, UserFilterDTO
from src.schemas.job import JobDTO
from src.services.region_compatibility import regions_compatible
from src.services.timezones import user_utc_offset
from src.services.tokens import contains_term, normalize_technology


class FilterService:
    """Evaluate whether a job is acceptable for a user based on hard filters."""

    @staticmethod
    def _normalize_token(value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip().lower()
        return stripped or None

    @classmethod
    def _get_allowed_regions(cls, filters: UserFilterDTO) -> set[str]:
        allowed = set()
        for region in filters.allowed_regions:
            normalized = cls._normalize_token(region)
            if normalized:
                allowed.add(normalized)

        return allowed

    _get_user_timezone_offset = staticmethod(user_utc_offset)

    @staticmethod
    def _contains_word(haystack: str, term: str) -> bool:
        return contains_term(haystack, term)

    @staticmethod
    def _has_intersection(
        user_min: float,
        user_max: float,
        vacancy_min: int,
        vacancy_max: int,
    ) -> bool:
        return max(user_min, vacancy_min) <= min(user_max, vacancy_max)

    def evaluate(self, job: JobDTO, filters: UserFilterDTO) -> FilterResult:
        reasons: list[str] = []

        if filters.sources:
            allowed_sources = {
                self._normalize_token(item)
                for item in filters.sources
                if self._normalize_token(item)
            }
            if self._normalize_token(job.source) not in allowed_sources:
                reasons.append(f"Source is not allowed: {job.source}")

        if filters.remote_only and not job.remote:
            reasons.append("Vacancy is not remote")

        if filters.excluded_technologies:
            excluded = {
                normalize_technology(item)
                for item in filters.excluded_technologies
                if normalize_technology(item)
            }
            for technology in job.technologies:
                normalized = normalize_technology(technology)
                if normalized in excluded:
                    reasons.append(f"Excluded technology: {normalized}")

        if filters.required_technologies:
            required = {
                normalize_technology(item)
                for item in filters.required_technologies
                if normalize_technology(item)
            }
            job_technologies = {
                normalize_technology(item)
                for item in job.technologies
                if normalize_technology(item)
            }
            for technology in sorted(required):
                if technology not in job_technologies:
                    reasons.append(f"Missing required technology: {technology}")

        if filters.keywords:
            haystack = f"{job.title or ''} {html_to_text(job.description)}"
            matches = [
                keyword.lower()
                for keyword in filters.keywords
                if keyword and self._contains_word(haystack, keyword)
            ]
            if not matches:
                reasons.append("No keyword match")

        if filters.blacklisted_words:
            haystack = f"{job.title or ''} {html_to_text(job.description)}"
            for word in filters.blacklisted_words:
                normalized_word = self._normalize_token(word)
                if normalized_word and self._contains_word(haystack, normalized_word):
                    reasons.append(f"Blacklisted word: {word}")

        if filters.blacklisted_companies:
            company_name = self._normalize_token(job.company)
            for company in filters.blacklisted_companies:
                normalized_company = self._normalize_token(company)
                if (
                    company_name
                    and normalized_company
                    and company_name == normalized_company
                ):
                    reasons.append(f"Blacklisted company: {job.company}")

        if filters.employment_types and job.employment_type is not None:
            allowed_types = {
                self._normalize_token(item)
                for item in filters.employment_types
                if self._normalize_token(item)
            }
            current = self._normalize_token(job.employment_type)
            if current not in allowed_types:
                reasons.append(f"Employment type is not allowed: {job.employment_type}")

        if filters.experience_levels and job.experience_level in {
            "junior",
            "middle",
            "senior",
            "lead",
            "staff",
            "principal",
        }:
            allowed_levels = {
                self._normalize_token(item)
                for item in filters.experience_levels
                if self._normalize_token(item)
            }
            current = self._normalize_token(job.experience_level)
            if current not in allowed_levels:
                reasons.append(
                    f"Experience level is not allowed: {job.experience_level}"
                )

        same_currency = (
            filters.currency is None
            or job.currency is not None
            and self._normalize_token(job.currency)
            == self._normalize_token(filters.currency)
        )
        if filters.min_salary is not None and same_currency:
            salary_value = (
                job.salary_max if job.salary_max is not None else job.salary_min
            )
            if salary_value is not None and salary_value < filters.min_salary:
                reasons.append("Salary is below minimum")

        if filters.currency is not None and job.currency is not None:
            if self._normalize_token(job.currency) != self._normalize_token(
                filters.currency
            ):
                reasons.append(f"Currency mismatch: {job.currency}")

        regions = [
            self._normalize_token(value)
            for value in job.remote_regions
            if self._normalize_token(value)
        ]
        if filters.exclude_us_only and "us_only" in regions:
            reasons.append("US-only vacancy")

        if regions:
            allowed_regions = self._get_allowed_regions(filters)
            if allowed_regions and not any(
                regions_compatible(region, allowed_regions) for region in regions
            ):
                reasons.append("Region is not allowed")

        user_timezone_offset = (
            self._get_user_timezone_offset(filters.timezone)
            if filters.timezone is not None
            else None
        )
        if user_timezone_offset is not None:
            vacancy_min = job.timezone_min_utc_offset
            vacancy_max = job.timezone_max_utc_offset
            if vacancy_min is not None and vacancy_max is not None:
                user_min = user_timezone_offset - filters.timezone_tolerance_hours
                user_max = user_timezone_offset + filters.timezone_tolerance_hours
                if not self._has_intersection(
                    user_min, user_max, vacancy_min, vacancy_max
                ):
                    reasons.append("Timezone is not compatible")

        return FilterResult(accepted=not reasons, reasons=reasons)
