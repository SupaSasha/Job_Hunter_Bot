from __future__ import annotations

import re

from src.schemas.job import JobDTO
from src.services.regions import normalize_region
from src.services.tokens import SKILL_NOISE, normalize_technology

COMPARABLE_EXPERIENCE_LEVELS = frozenset(
    {"junior", "middle", "senior", "lead", "staff", "principal"}
)


def split_job_values(value: str | None) -> set[str]:
    # Strip underscores left after commas by the previous normalizer, too.
    return {
        item
        for part in (value or "").split(",")
        if (item := part.strip(" _").casefold())
    }


class NormalizationService:
    """Normalize job data into a stable project-wide canonical form."""

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
        "mid level": "middle",
        "midweight": "middle",
        "entry-level, junior": "junior",
        "any": None,
        "semi senior": "middle",
        "semi-senior": "middle",
        "semi_senior": "middle",
        "senior": "senior",
        "senior level": "senior",
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

    _canonicalize_technology = staticmethod(normalize_technology)

    @classmethod
    def _normalize_technologies(cls, technologies: list[str] | None) -> list[str]:
        if not technologies:
            return []

        normalized: list[str] = []
        seen: set[str] = set()
        for item in technologies:
            canonical = cls._canonicalize_technology(str(item))
            if not canonical or canonical in SKILL_NOISE or canonical in seen:
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
            canonical = normalize_region(
                cls.REMOTE_REGION_ALIASES.get(lowered, lowered)
            )
            if canonical in seen:
                continue
            normalized.append(canonical)
            seen.add(canonical)
        return normalized

    @classmethod
    def _normalize_job_values(
        cls, value: str | None, aliases: dict[str, str | None]
    ) -> str | None:
        normalized = []
        for part in (value or "").split(","):
            item = cls._collapse_spaces(part.strip(" _"))
            if not item:
                continue
            lowered = item.lower()
            canonical = aliases.get(lowered, lowered.replace(" ", "_"))
            if canonical and canonical not in normalized:
                normalized.append(canonical)
        return ", ".join(normalized) or None

    @classmethod
    def _normalize_employment_type(cls, employment_type: str | None) -> str | None:
        return cls._normalize_job_values(employment_type, cls.EMPLOYMENT_TYPE_ALIASES)

    @classmethod
    def _normalize_experience_level(cls, experience_level: str | None) -> str | None:
        return cls._normalize_job_values(experience_level, cls.EXPERIENCE_LEVEL_ALIASES)

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

        if text.startswith("UTC offsets: ["):
            labels = text.removeprefix("UTC offsets: [").removesuffix("]").split(", ")
            if len(labels) != len(matches) or any(
                not re.fullmatch(
                    r"(?:UTC|GMT)\s*[+-]\s*\d{1,2}(?::\d{2})?", label, re.IGNORECASE
                )
                for label in labels
            ):
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
            if text.startswith("UTC offsets: ["):
                if len(set(offsets)) != max(offsets) - min(offsets) + 1:
                    # A discrete set with gaps cannot fit an integer interval.
                    return None, None
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
