from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class UserFilterDTO(BaseModel):
    model_config = ConfigDict(extra="ignore")

    keywords: list[str] = Field(default_factory=list)
    required_technologies: list[str] = Field(default_factory=list)
    preferred_technologies: list[str] = Field(default_factory=list)
    excluded_technologies: list[str] = Field(default_factory=list)

    min_salary: int | None = None
    currency: str | None = None

    allowed_regions: list[str] = Field(default_factory=lambda: ["worldwide"])

    remote_only: bool = True
    exclude_us_only: bool = False

    employment_types: list[str] = Field(default_factory=list)
    experience_levels: list[str] = Field(default_factory=list)

    blacklisted_words: list[str] = Field(default_factory=list)
    blacklisted_companies: list[str] = Field(default_factory=list)

    sources: list[str] = Field(default_factory=list)

    timezone: str | None = None
    timezone_tolerance_hours: int = 2


class FilterResult(BaseModel):
    accepted: bool
    reasons: list[str] = Field(default_factory=list)
