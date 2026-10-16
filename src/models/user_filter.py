from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base
from src.models.timestamps import Timestamps
from src.services.collector_policy import COLLECTOR_POLICIES

DEFAULT_REGIONS = ("worldwide", "latam", "south_america", "uruguay")
AVAILABLE_SOURCES = tuple(COLLECTOR_POLICIES)
DEFAULT_SOURCES = tuple(
    source for source, policy in COLLECTOR_POLICIES.items() if policy.default_enabled
)


def list_column(values: tuple[str, ...] = ()):
    literal = "{" + ",".join(values) + "}"
    return mapped_column(
        ARRAY(String),
        default=lambda: list(values),
        server_default=text(f"'{literal}'::varchar[]"),
    )


class UserFilterORM(Timestamps, Base):
    __tablename__ = "user_filters"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_user_filters_user_id"),
        CheckConstraint("min_salary >= 0", name="ck_user_filters_min_salary"),
        CheckConstraint(
            "timezone_tolerance_hours BETWEEN 0 AND 4",
            name="ck_user_filters_timezone_tolerance",
        ),
        CheckConstraint("cardinality(sources) > 0", name="ck_user_filters_sources"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    keywords: Mapped[list[str]] = list_column()
    required_technologies: Mapped[list[str]] = list_column()
    preferred_technologies: Mapped[list[str]] = list_column()
    excluded_technologies: Mapped[list[str]] = list_column()
    min_salary: Mapped[int | None]
    currency: Mapped[str | None] = mapped_column(String)
    allowed_regions: Mapped[list[str]] = list_column(DEFAULT_REGIONS)
    remote_only: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    exclude_us_only: Mapped[bool] = mapped_column(
        default=True, server_default=text("true")
    )
    employment_types: Mapped[list[str]] = list_column()
    experience_levels: Mapped[list[str]] = list_column()
    blacklisted_words: Mapped[list[str]] = list_column()
    blacklisted_companies: Mapped[list[str]] = list_column()
    sources: Mapped[list[str]] = list_column(DEFAULT_SOURCES)
    timezone_tolerance_hours: Mapped[int] = mapped_column(default=2, server_default="2")
