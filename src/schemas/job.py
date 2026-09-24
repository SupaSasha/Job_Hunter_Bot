from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field


class JobDTO(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source: str
    external_id: str
    title: str
    company: str | None = None
    description: str | None = None
    url: str
    location: str | None = None
    timezone_text: str | None = None
    timezone_min_utc_offset: int | None = None
    timezone_max_utc_offset: int | None = None
    remote: bool = False
    remote_regions: list[str] = Field(default_factory=list)
    employment_type: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    currency: str | None = None
    salary_period: str | None = None
    technologies: list[str] = Field(default_factory=list)
    experience_level: str | None = None
    published_at: datetime | None = None
    collected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
