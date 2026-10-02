from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def user_utc_offset(timezone_name: str, at: datetime | None = None) -> float | None:
    """Use the evaluation date (current UTC by default), including DST/fractions."""
    try:
        zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return None
    moment = at if at is not None else datetime.now(UTC)
    if moment.utcoffset() is None:
        raise ValueError("Timezone evaluation date must be aware")
    offset = moment.astimezone(zone).utcoffset()
    return offset.total_seconds() / 3600 if offset is not None else None
