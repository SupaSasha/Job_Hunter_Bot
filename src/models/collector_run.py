from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base


class CollectorRunORM(Base):
    """One invocation; an interrupted process remains visibly running."""

    __tablename__ = "collector_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'success', 'failed', 'skipped')",
            name="ck_collector_run_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(64), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="running")
    received_count: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    new_count: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    duplicate_count: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    cross_source_duplicate_count: Mapped[int] = mapped_column(
        default=0, server_default=text("0")
    )
    failed_count: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    duration_ms: Mapped[int | None]
    error: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
