import hashlib
import json
import re

from src.repositories.jobs import JobRepository
from src.schemas.deduplication import DeduplicationResult
from src.schemas.job import JobDTO


class DeduplicationService:
    def __init__(self, repository: JobRepository) -> None:
        self.repository = repository

    @staticmethod
    def _canonicalize(value: str | None) -> str:
        value = (value or "").lower().replace("&", " and ")
        value = value.translate(str.maketrans("", "", ".,'’"))
        # Preserve meaningful technology symbols, e.g. C++, C#.
        value = re.sub(r"[^\w\s+#]|_", " ", value)
        return " ".join(value.split())

    @classmethod
    def calculate_fingerprint(cls, job: JobDTO) -> str:
        # Structured encoding avoids ambiguity at the company/title boundary.
        payload = json.dumps(
            [cls._canonicalize(job.company), cls._canonicalize(job.title)],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    async def check(self, job: JobDTO) -> DeduplicationResult:
        existing = await self.repository.get_by_source_external_id(
            job.source, job.external_id
        )
        if existing is not None:
            return DeduplicationResult(
                is_duplicate=True,
                reason="source_external_id",
                existing_job_id=existing.id,
            )

        fingerprint = self.calculate_fingerprint(job)
        existing = await self.repository.get_by_fingerprint(fingerprint)
        if existing is not None:
            return DeduplicationResult(
                is_duplicate=True,
                reason="fingerprint",
                existing_job_id=existing.id,
                fingerprint=fingerprint,
                cross_source_duplicate=existing.source != job.source,
            )
        return DeduplicationResult(is_duplicate=False, fingerprint=fingerprint)
