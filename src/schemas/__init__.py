"""Schema models for the project."""

from src.schemas.filters import FilterResult, UserFilterDTO
from src.schemas.job import JobDTO
from src.schemas.scoring import ScoreResult

__all__ = ["FilterResult", "JobDTO", "ScoreResult", "UserFilterDTO"]
