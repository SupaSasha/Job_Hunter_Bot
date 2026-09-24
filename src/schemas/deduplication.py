from typing import Literal

from pydantic import BaseModel

DuplicateReason = Literal["source_external_id", "fingerprint"]


class DeduplicationResult(BaseModel):
    is_duplicate: bool
    reason: DuplicateReason | None = None
    existing_job_id: int | None = None
    fingerprint: str | None = None


class JobSaveResult(BaseModel):
    status: Literal["saved", "duplicate"]
    job_id: int
    reason: DuplicateReason | None = None
