from datetime import date, datetime, time

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    String,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CollectorStateORM(Timestamps, Base):
    __tablename__ = "collector_states"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(64), unique=True)
    last_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_status: Mapped[str] = mapped_column(String(32), default="scheduled")
    last_error: Mapped[str | None] = mapped_column(String(512))


class UserNotificationSettingsORM(Timestamps, Base):
    __tablename__ = "user_notification_settings"
    __table_args__ = (
        CheckConstraint("min_score BETWEEN 0 AND 100", name="ck_settings_score"),
        CheckConstraint("max_jobs_per_digest >= 0", name="ck_settings_max_jobs"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    timezone: Mapped[str] = mapped_column(String(64), default="America/Montevideo")
    digest_time: Mapped[time] = mapped_column(Time(timezone=False), default=time(9))
    min_score: Mapped[int] = mapped_column(default=70)
    digest_enabled: Mapped[bool] = mapped_column(
        default=True, server_default=text("true")
    )
    max_jobs_per_digest: Mapped[int] = mapped_column(default=10)


class UserSubscriptionORM(Timestamps, Base):
    __tablename__ = "user_subscriptions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('trial', 'active', 'expired')", name="ck_subscription_status"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    status: Mapped[str] = mapped_column(String(16), default="trial")
    trial_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    subscription_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    subscription_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )


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
