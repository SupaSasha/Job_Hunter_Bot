from typing import Literal

from pydantic import BaseModel

DuplicateReason = Literal["source_external_id", "fingerprint"]


class DeduplicationResult(BaseModel):
    is_duplicate: bool
    cross_source_duplicate: bool = False
    reason: DuplicateReason | None = None
    existing_job_id: int | None = None
    fingerprint: str | None = None


class JobSaveResult(BaseModel):
    status: Literal["saved", "duplicate"]
    job_id: int
    cross_source_duplicate: bool = False
    reason: DuplicateReason | None = None
