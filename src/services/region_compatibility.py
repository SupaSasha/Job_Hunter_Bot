from collections.abc import Iterable

from src.services.regions import normalize_region, region_members


def regions_compatible(job_region: str, allowed_regions: Iterable[str]) -> bool:
    job_value = normalize_region(job_region)
    allowed = {normalize_region(region) for region in allowed_regions if region.strip()}
    if not allowed or "worldwide" in allowed or job_value == "worldwide":
        return True
    if job_value in allowed:
        return True
    members = region_members(job_value)
    return any(members & region_members(region) for region in allowed)
