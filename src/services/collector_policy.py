import random
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class CollectorPolicy:
    source: str
    task_name: str
    windows: tuple[tuple[time, time], ...]
    retry_delay: timedelta = timedelta(hours=1)


COLLECTOR_POLICIES = {
    "remoteok": CollectorPolicy(
        "remoteok",
        "jobs.collect_remoteok",
        ((time(2), time(4)), (time(10), time(12)), (time(18), time(20))),
    )
}


def next_collection(
    now: datetime,
    policy: CollectorPolicy,
    timezone: str,
    *,
    initial: bool = False,
    rng: random.Random | None = None,
) -> datetime:
    """Pick once in the next window; initial bootstrap can use its remainder."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    zone = ZoneInfo(timezone)
    local = now.astimezone(zone)
    chooser = rng or random
    for day_offset in range(3):
        day = local.date() + timedelta(days=day_offset)
        for start_time, end_time in policy.windows:
            start = datetime.combine(day, start_time, zone).astimezone(UTC)
            end = datetime.combine(day, end_time, zone).astimezone(UTC)
            if end <= now:
                continue
            if start <= now:
                if not initial:
                    continue
                start = now.astimezone(UTC)
            # randrange excludes the end of the window.
            seconds = max(1, int((end - start).total_seconds()))
            return start + timedelta(seconds=chooser.randrange(seconds))
    raise ValueError("Policy has no future window")
