from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base


class JobORM(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_jobs_source_external_id"),
        Index("ix_jobs_collected_at", "collected_at"),
        Index("ix_jobs_fingerprint_collected_at", "fingerprint", "collected_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String)
    external_id: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String)
    company: Mapped[str | None] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(String)
    remote: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    remote_regions: Mapped[list[str]] = mapped_column(
        ARRAY(String), default=list, server_default=text("'{}'::varchar[]")
    )
    employment_type: Mapped[str | None] = mapped_column(String)
    salary_min: Mapped[int | None]
    salary_max: Mapped[int | None]
    currency: Mapped[str | None] = mapped_column(String)
    salary_period: Mapped[str | None] = mapped_column(String)
    technologies: Mapped[list[str]] = mapped_column(
        ARRAY(String), default=list, server_default=text("'{}'::varchar[]")
    )
    experience_level: Mapped[str | None] = mapped_column(String)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    timezone_text: Mapped[str | None] = mapped_column(String)
    timezone_min_utc_offset: Mapped[int | None]
    timezone_max_utc_offset: Mapped[int | None]
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
