from src.models.user_filter import DEFAULT_REGIONS, DEFAULT_SOURCES
from src.schemas.filters import UserFilterDTO


def default_user_filters(timezone: str = "America/Montevideo") -> UserFilterDTO:
    """Legacy owner defaults kept for the primary user bootstrap."""
    return UserFilterDTO(
        keywords=["python"],
        required_technologies=["python"],
        preferred_technologies=["fastapi", "postgresql", "redis", "celery", "docker"],
        allowed_regions=list(DEFAULT_REGIONS),
        sources=list(DEFAULT_SOURCES),
        remote_only=True,
        worldwide_allowed=True,
        latam_allowed=True,
        south_america_allowed=True,
        uruguay_allowed=True,
        exclude_us_only=True,
        timezone=timezone,
        timezone_tolerance_hours=2,
    )
