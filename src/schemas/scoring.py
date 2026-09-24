from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ScoreResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    score: int
    matched_rules: list[str] = Field(default_factory=list)
    penalties: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
