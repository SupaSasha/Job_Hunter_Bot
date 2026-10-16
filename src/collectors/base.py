from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from src.schemas.job import JobDTO


class CollectionError(RuntimeError):
    """Source unavailable or returned an invalid response."""

    def __init__(self, message: str, *, retry_at: datetime | None = None):
        super().__init__(message)
        self.retry_at = retry_at


class CollectorConfigurationError(CollectionError):
    """Required source credentials or market settings are missing."""


class BaseJobCollector(ABC):
    """Shared contract for all job collectors."""

    source_name: str = "base"
    timeout: float = 20.0
    max_pages: int = 1

    def __init__(self, *, timeout: float | None = None) -> None:
        self.timeout = timeout if timeout is not None else self.timeout

    @property
    def request_headers(self) -> dict[str, str]:
        return {
            "User-Agent": "JobHunterBot/0.1 (+https://github.com/SupaSasha/Job_Hunter_Bot)",
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "en-US,en;q=0.9",
        }

    @abstractmethod
    async def collect(self) -> list[JobDTO]:
        """Fetch source jobs and convert them into JobDTO instances."""
