from __future__ import annotations

import re

from src.schemas.job import JobDTO


class NormalizationService:
    """Normalize job data into a stable project-wide canonical form."""

    TECHNOLOGY_ALIASES = {
        "python": "python",
        "fast api": "fastapi",
        "fastapi": "fastapi",
        "postgres": "postgresql",
        "postgresql": "postgresql",
        "postgre sql": "postgresql",
        "redis": "redis",
        "celery": "celery",
        "docker": "docker",
        "kubernetes": "kubernetes",
        "k8s": "kubernetes",
        "javascript": "javascript",
        "js": "javascript",
        "typescript": "typescript",
        "ts": "typescript",
        "nodejs": "nodejs",
        "node js": "nodejs",
        "node.js": "nodejs",
        "node": "nodejs",
    }

    REMOTE_REGION_ALIASES = {
        "worldwide": "worldwide",
        "anywhere": "worldwide",
        "global": "worldwide",
        "remote worldwide": "worldwide",
        "latam": "latam",
        "latin america": "latam",
        "latin-america": "latam",
        "south america": "south_america",
        "americas": "americas",
        "the americas": "americas",
        "north america": "north_america",
        "united states": "us",
        "usa": "us",
        "us": "us",
        "u.s.": "us",
        "us only": "us_only",
        "usa only": "us_only",
        "united states only": "us_only",
        "canada": "canada",
        "europe": "europe",
        "european union": "eu",
        "eu": "eu",
        "emea": "emea",
        "apac": "apac",
        "asia pacific": "apac",
        "uruguay": "uruguay",
    }

    EMPLOYMENT_TYPE_ALIASES = {
        "full time": "full_time",
        "full-time": "full_time",
        "fulltime": "full_time",
        "part time": "part_time",
        "part-time": "part_time",
        "contract": "contract",
        "contractor": "contract",
        "freelance": "freelance",
        "internship": "internship",
        "intern": "internship",
    }

    EXPERIENCE_LEVEL_ALIASES = {
        "junior": "junior",
        "jr": "junior",
        "entry level": "junior",
        "entry-level": "junior",
        "middle": "middle",
        "mid": "middle",
        "mid-level": "middle",
        "senior": "senior",
        "sr": "senior",
        "staff": "staff",
        "principal": "principal",
        "lead": "lead",
    }

    @staticmethod
    def _collapse_spaces(value: str | None) -> str | None:
        if value is None:
            return None
        collapsed = re.sub(r"\s+", " ", value.strip())
        return collapsed or None

    @classmethod
    def _canonicalize_technology(cls, value: str) -> str:
        normalized = cls._collapse_spaces(value)
        if normalized is None:
            return ""

        lowered = normalized.lower().replace("_", " ")
        lowered = lowered.replace(".", " ")
        lowered = lowered.replace("-", " ")
        lowered = re.sub(r"[^a-z0-9\s]+", " ", lowered)
        lowered = re.sub(r"\s+", " ", lowered).strip()
        if not lowered:
            return ""
        if lowered in cls.TECHNOLOGY_ALIASES:
            return cls.TECHNOLOGY_ALIASES[lowered]
        return lowered.replace(" ", "")

    @classmethod
    def _normalize_technologies(cls, technologies: list[str] | None) -> list[str]:
        if not technologies:
            return []

        normalized: list[str] = []
        seen: set[str] = set()
        for item in technologies:
            canonical = cls._canonicalize_technology(str(item))
            if not canonical or canonical in seen:
                continue
            normalized.append(canonical)
            seen.add(canonical)
        return normalized

    @classmethod
    def _normalize_remote_regions(cls, remote_regions: list[str] | None) -> list[str]:
        if not remote_regions:
            return []

        normalized: list[str] = []
        seen: set[str] = set()
        for item in remote_regions:
            value = cls._collapse_spaces(str(item))
            if value is None:
                continue
            lowered = value.lower().strip()
            canonical = cls.REMOTE_REGION_ALIASES.get(lowered, lowered)
            if canonical in seen:
                continue
            normalized.append(canonical)
            seen.add(canonical)
        return normalized

    @classmethod
    def _normalize_employment_type(cls, employment_type: str | None) -> str | None:
        if employment_type is None:
            return None

        value = cls._collapse_spaces(employment_type)
        if value is None:
            return None

        lowered = value.lower()
        if lowered in cls.EMPLOYMENT_TYPE_ALIASES:
            return cls.EMPLOYMENT_TYPE_ALIASES[lowered]
        if " or " in lowered or " and " in lowered:
            return lowered.replace(" ", "_")
        return lowered.replace(" ", "_")

    @classmethod
    def _normalize_experience_level(cls, experience_level: str | None) -> str | None:
        if experience_level is None:
            return None

        value = cls._collapse_spaces(experience_level)
        if value is None:
            return None

        lowered = value.lower()
        return cls.EXPERIENCE_LEVEL_ALIASES.get(lowered, lowered.replace(" ", "_"))

    @staticmethod
    def _normalize_location(value: str | None) -> str | None:
        return NormalizationService._collapse_spaces(value)

    @staticmethod
    def _normalize_text_value(value: str | None) -> str | None:
        return NormalizationService._collapse_spaces(value)

    @classmethod
    def _parse_utc_offsets(cls, value: str | None) -> tuple[int | None, int | None]:
        if value is None:
            return None, None

        text = value.strip()
        if not text:
            return None, None

        matches = re.findall(
            r"(?:UTC|GMT)\s*([+-])\s*(\d{1,2})(?::?(\d{2}))?",
            text,
            flags=re.IGNORECASE,
        )
        if not matches:
            return None, None

        offsets: list[int] = []
        for sign, hours_str, minutes_str in matches:
            if minutes_str not in (None, "", "00", "0"):
                return None, None
            hours = int(hours_str)
            if sign == "-":
                offset = -hours
            else:
                offset = hours
            offsets.append(offset)

        if len(offsets) == 1:
            return offsets[0], offsets[0]
        if len(offsets) >= 2:
            return min(offsets), max(offsets)
        return None, None

    def normalize(self, job: JobDTO) -> JobDTO:
        normalized = job.model_copy(deep=True)

        normalized.title = self._normalize_text_value(normalized.title) or ""
        normalized.company = self._normalize_text_value(normalized.company)
        normalized.location = self._normalize_location(normalized.location)
        normalized.remote_regions = self._normalize_remote_regions(
            normalized.remote_regions
        )
        normalized.technologies = self._normalize_technologies(normalized.technologies)
        normalized.employment_type = self._normalize_employment_type(
            normalized.employment_type
        )
        normalized.experience_level = self._normalize_experience_level(
            normalized.experience_level
        )

        timezone_text = self._normalize_text_value(normalized.timezone_text)
        normalized.timezone_text = timezone_text
        if timezone_text is not None:
            min_offset, max_offset = self._parse_utc_offsets(timezone_text)
            normalized.timezone_min_utc_offset = min_offset
            normalized.timezone_max_utc_offset = max_offset
        else:
            normalized.timezone_min_utc_offset = None
            normalized.timezone_max_utc_offset = None

        return normalized
