from src.models.user_filter import DEFAULT_SOURCES
from src.schemas.filters import UserFilterDTO


def default_user_filters() -> UserFilterDTO:
    """Neutral filters; user preferences are added explicitly."""
    return UserFilterDTO(sources=list(DEFAULT_SOURCES))
