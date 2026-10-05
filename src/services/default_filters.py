from src.schemas.filters import UserFilterDTO


def default_user_filters(timezone: str = "America/Montevideo") -> UserFilterDTO:
    """Legacy owner profile, used only when bootstrapping missing saved filters."""
    return UserFilterDTO(
        required_technologies=["python"],
        preferred_technologies=["fastapi", "postgresql", "redis", "celery", "docker"],
        remote_only=True,
        worldwide_allowed=True,
        latam_allowed=True,
        south_america_allowed=True,
        uruguay_allowed=True,
        exclude_us_only=True,
        timezone=timezone,
        timezone_tolerance_hours=2,
    )
