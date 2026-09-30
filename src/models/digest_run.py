from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, synonym

from src.db.base import Base
from src.models.timestamps import Timestamps


class DigestRunORM(Timestamps, Base):
    """A committed reservation is final for this date, including failed/empty runs."""

    __tablename__ = "digest_runs"
    __table_args__ = (
        UniqueConstraint("user_id", "local_date", name="uq_digest_user_date"),
        CheckConstraint(
            "status IN ('pending', 'empty', 'sent', 'partial', 'failed')",
            name="ck_digest_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    local_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary_message_id: Mapped[int | None] = mapped_column(BigInteger)
    selected: Mapped[int] = mapped_column(default=0)
    sent: Mapped[int] = mapped_column(default=0)
    failed: Mapped[int] = mapped_column(default=0)
    skipped: Mapped[int] = mapped_column(default=0)
    last_error: Mapped[str | None] = mapped_column(String(512))

    # False for historical runs without selection telemetry.
    metrics_recorded: Mapped[bool] = mapped_column(
        default=False, server_default=text("false")
    )
    candidate_count: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    filter_rejected_count: Mapped[int] = mapped_column(
        default=0, server_default=text("0")
    )
    accepted_count: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    score_0_49_count: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    score_50_59_count: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    score_60_69_count: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    score_70_79_count: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    score_80_89_count: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    score_90_100_count: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    below_threshold_count: Mapped[int] = mapped_column(
        default=0, server_default=text("0")
    )

    # Preserve the existing database columns and reservation contract.
    selected_count = synonym("selected")
    sent_count = synonym("sent")
    failed_count = synonym("failed")
