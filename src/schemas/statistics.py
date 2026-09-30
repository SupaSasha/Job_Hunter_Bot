from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from src.schemas.digest_metrics import DigestMetrics

StatsPeriod = Literal["24h", "7d", "30d"]


class DataQualityStats(BaseModel):
    job_count: int = 0
    salary_known_count: int = 0
    region_known_count: int = 0
    timezone_known_count: int = 0
    technologies_known_count: int = 0
    salary_known_percent: float | None = None
    region_known_percent: float | None = None
    timezone_known_percent: float | None = None
    technologies_known_percent: float | None = None


class CollectorStats(BaseModel):
    source: str
    runs: int = 0
    successful_runs: int = 0
    failed_runs: int = 0
    skipped_runs: int = 0
    running_runs: int = 0
    received_count: int = 0
    new_count: int = 0
    duplicate_count: int = 0
    cross_source_duplicate_count: int = 0
    failed_count: int = 0
    duration_ms: int = 0
    duplicate_rate: float | None = None
    new_jobs_per_run: float | None = None
    quality: DataQualityStats = Field(default_factory=DataQualityStats)


class DigestStats(DigestMetrics):
    runs: int = 0
    measured_runs: int = 0
    unmeasured_runs: int = 0
    failed_runs: int = 0
    pending_runs: int = 0
    selected_count: int = 0
    sent_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0


class FeedbackStats(BaseModel):
    saved_count: int = 0
    rejected_count: int = 0


class NotificationStats(BaseModel):
    sent_count: int = 0
    failed_count: int = 0
    pending_count: int = 0


class UserStats(BaseModel):
    total_users: int = 0
    active_users: int = 0
    trial_users: int = 0
    premium_users: int = 0
    free_users: int = 0


class BotStats(BaseModel):
    period: StatsPeriod
    since: datetime
    until: datetime
    collectors: list[CollectorStats] = Field(default_factory=list)
    digest: DigestStats = Field(default_factory=DigestStats)
    feedback: FeedbackStats = Field(default_factory=FeedbackStats)
    notifications: NotificationStats = Field(default_factory=NotificationStats)
    users: UserStats = Field(default_factory=UserStats)
    quality: DataQualityStats = Field(default_factory=DataQualityStats)
    duplicate_rate: float | None = None
    filter_rejection_rate: float | None = None
    notification_success_rate: float | None = None
    save_rate: float | None = None
    reject_rate: float | None = None
