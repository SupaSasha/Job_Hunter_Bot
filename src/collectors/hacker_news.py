"""Monthly HN hiring threads through Algolia's public API, without scraping."""

import logging
import re
from datetime import UTC, datetime, timedelta

import httpx

from src.collectors.base import BaseJobCollector, CollectionError
from src.collectors.http import fetch_json
from src.collectors.salary import parse_salary_text
from src.collectors.skills import TECHNICAL_CATEGORIES
from src.collectors.text import html_to_text
from src.schemas.job import JobDTO
from src.services.normalization import NormalizationService
from src.services.tokens import TECHNOLOGY_ALIASES, normalize_technology

logger = logging.getLogger(__name__)
MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
ROLE = re.compile(
    r"\b(?:(?:senior|junior|mid|middle|staff|principal|lead|founding|full[- ]?stack|"
    r"back[- ]?end|front[- ]?end|software|platform|devops|data|machine learning|"
    r"ML|AI|security|infrastructure|product|mobile|site reliability|cloud|"
    r"research|systems|QA|R&D|intelligence|solutions|sales)\s+){0,4}"
    r"(?:engineers?|developers?|designers?|scientists?|architects?|"
    r"product managers?|engineering managers?|technical writers?|SWE|SRE)\b",
    re.IGNORECASE,
)
REGIONS = re.compile(
    r"\b(?:US(?:A)? only|Worldwide|Anywhere|LATAM|South America|Europe|EU|EMEA|"
    r"APAC|Canada|Uruguay)\b",
    re.IGNORECASE,
)
EMPLOYMENT = re.compile(
    r"\b(?:full[- ]time|part[- ]time|contract|freelance|internship)\b", re.IGNORECASE
)
EXPERIENCE = re.compile(
    r"\b(?:junior|mid|middle|senior|staff|lead|principal)\b", re.IGNORECASE
)
UTC_LABEL = re.compile(
    r"\b(?:UTC|GMT)\s*[+-]\s*\d{1,2}(?::\d{2})?(?![\d.:])", re.IGNORECASE
)


def _id(value: object) -> int:
    if type(value) is int and value > 0:
        return value
    if (
        isinstance(value, str)
        and value.isascii()
        and value.isdigit()
        and int(value) > 0
    ):
        return int(value)
    raise ValueError("Invalid HN item ID")


def _date(value: object) -> datetime | None:
    if isinstance(value, str):
        try:
            date = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return date.astimezone(UTC) if date.tzinfo else None
        except ValueError:
            pass
    return None


def thread_titles(now: datetime) -> tuple[str, str]:
    current = now.astimezone(UTC).replace(day=1)
    previous = current - timedelta(days=1)
    return tuple(
        f"Ask HN: Who is hiring? ({MONTHS[date.month - 1]} {date.year})"
        for date in (current, previous)
    )


def find_thread(payload: object, now: datetime) -> tuple[int, str]:
    if not isinstance(payload, dict) or not isinstance(payload.get("hits"), list):
        raise CollectionError("Hacker News returned invalid thread search")
    for title in thread_titles(now):
        for hit in payload["hits"]:
            if not isinstance(hit, dict):
                continue
            if hit.get("title") != title or hit.get("author") != "whoishiring":
                continue
            tags = hit.get("_tags")
            if not isinstance(tags, list) or "story" not in tags:
                continue
            published = _date(hit.get("created_at"))
            if published is None or title != (
                f"Ask HN: Who is hiring? "
                f"({MONTHS[published.month - 1]} {published.year})"
            ):
                continue
            try:
                return _id(hit.get("objectID")), title
            except ValueError:
                continue
    raise CollectionError("Hacker News current/previous hiring thread not found")


def _extract_title(lines: list[str]) -> str:
    header = lines[0]
    if not ROLE.search(header) and len(lines) > 1 and len(lines[1]) <= 180:
        if not re.match(r"(?:we|at|our|join|the|please|if|this)\b", lines[1], re.I):
            header += "\n" + lines[1]
    roles = list(
        dict.fromkeys(match.group().strip() for match in ROLE.finditer(header))
    )
    listed = {
        match.group().casefold()
        for line in lines[1:12]
        if (match := ROLE.fullmatch(line.lstrip("-*• ").strip()))
    }
    if (
        len({role.casefold() for role in roles}) > 1
        or re.search(r"\bmultiple\b.{0,45}\broles?\b", header, re.IGNORECASE)
        or len(listed) > 1
    ):
        return "Multiple roles"
    return roles[0][:120] if roles else "Job opening"


def _extract_company(header: str) -> str | None:
    if "|" not in header:
        return None
    company = re.sub(r"\(https?://[^)\s]+\)", "", header.split("|", 1)[0])
    company = re.sub(r"https?://\S+", "", company).strip(" -–—")
    if (
        not company
        or len(company) > 100
        or ROLE.search(company)
        or re.search(
            r"\b(?:hiring|remote|onsite|on-site|seeking|full.time)\b", company, re.I
        )
    ):
        return None
    return company


def _extract_remote(metadata: str) -> bool | None:
    if re.search(
        r"\b(?:hybrid|on[- ]?site|not remote|no remote|non[- ]remote)\b"
        r"|\bremote not available\b",
        metadata,
        re.IGNORECASE,
    ):
        return False
    if re.search(r"\bremote\b", metadata, re.IGNORECASE):
        return True
    return None


def _extract_regions(metadata: str, remote: bool | None) -> list[str]:
    if remote is not True:
        return []
    result = []
    for part in metadata.split("|"):
        if ROLE.search(part) and not re.search(r"\bremote\b", part, re.I):
            continue
        if re.search(r"\b(?:office|headquarters|timezones?)\b", part, re.I):
            continue
        result.extend(
            match.group()
            for match in REGIONS.finditer(part)
            if not re.search(r"\b(?:not|no|without)\s*$", part[: match.start()], re.I)
        )
    return list(dict.fromkeys(result))


def _extract_one(pattern: re.Pattern, text: str) -> str | None:
    matches = {
        match.group().lower().replace("-", " ")
        for match in pattern.finditer(text)
        if not re.search(r"\b(?:not|no|non|without)\s*$", text[: match.start()], re.I)
    }
    return next(iter(matches)) if len(matches) == 1 else None


def _extract_timezone(text: str) -> str | None:
    matches = list(UTC_LABEL.finditer(text))
    labels = [match.group() for match in matches]
    for label in labels:
        low, high = NormalizationService._parse_utc_offsets(label)
        if any(value is not None and abs(value) > 14 for value in (low, high)):
            return None
    if labels:
        if len(labels) == 1:
            return labels[0]
        between = text[matches[0].end() : matches[1].start()].strip()
        if len(labels) == 2 and re.fullmatch(r"to|through|[-–—]", between, re.I):
            return " to ".join(labels)
        return "UTC offsets: [" + ", ".join(labels) + "]"
    abbreviations = list(
        dict.fromkeys(re.findall(r"\b(?:EST|PST|CET|EDT|PDT|CEST)\b", text))
    )
    return ", ".join(abbreviations) or None


def _extract_technologies(text: str) -> list[str]:
    # Reuse the project's vocabulary and aliases; do not turn general words into skills.
    text = re.sub(r"https?://\S+|\S+@\S+", " ", text)
    vocabulary = {label for label in TECHNICAL_CATEGORIES if " " not in label} - {
        "backend",
        "devops",
        "database",
    }
    vocabulary.update(TECHNOLOGY_ALIASES)
    result = set()
    for label in sorted(vocabulary):
        spelling = {"go": "Go", "c": "C", "js": "JS", "ts": "TS"}.get(label, label)
        flags = 0 if label in {"go", "c", "js", "ts"} else re.IGNORECASE
        if re.search(
            r"(?<![\w+#])" + re.escape(spelling) + r"(?![\w+#-])", text, flags
        ):
            result.add(normalize_technology(label))
    return sorted(result)


def parse_comment(
    raw: dict, *, thread_id: int, collected_at: datetime | None = None
) -> JobDTO | None:
    if not isinstance(raw, dict):
        raise ValueError("Invalid HN comment")
    if "type" not in raw or "parent_id" not in raw:
        raise ValueError("Missing HN comment structure")
    if raw.get("type") != "comment" or raw.get("parent_id") != thread_id:
        return None
    if raw.get("deleted") or raw.get("dead"):
        return None
    identity = _id(raw.get("id"))
    text = html_to_text(raw.get("text") if isinstance(raw.get("text"), str) else None)
    if not text or text.casefold() in {"[deleted]", "[dead]", "deleted", "dead"}:
        return None
    lines = text.splitlines()
    header = lines[0]
    if re.search(
        r"\b(?:seeking work|looking for (?:a job|work)|for hire|who is hiring|"
        r"please (?:mention|specify)|this thread)\b",
        header,
        re.I,
    ):
        return None
    company = _extract_company(header)
    title = _extract_title(lines)
    metadata = "|".join(header.split("|")[1:]) if company else header
    remote = _extract_remote(metadata)
    hiring = re.search(
        r"\b(?:we(?:'re| are)? hiring|we are looking for|join our team|"
        r"hiring (?:a|an))\b",
        text,
        re.I,
    )
    if (
        not company
        and not hiring
        and not (title != "Job opening" and ("|" in header or "—" in header))
    ):
        return None
    if title == "Job opening" and not (
        company and (remote is not None or EMPLOYMENT.search(metadata)) or hiring
    ):
        return None
    salary = (
        parse_salary_text(text)
        if title != "Multiple roles"
        else (None, None, None, None)
    )
    return JobDTO(
        source="hacker_news",
        external_id=str(identity),
        title=title,
        company=company,
        description=text,
        url=f"https://news.ycombinator.com/item?id={identity}",
        location=None,
        remote=remote is True,
        remote_regions=_extract_regions(metadata, remote),
        employment_type=_extract_one(EMPLOYMENT, metadata),
        experience_level=(
            _extract_one(EXPERIENCE, title)
            if title not in {"Multiple roles", "Job opening"}
            else None
        ),
        technologies=_extract_technologies(text),
        salary_min=salary[0],
        salary_max=salary[1],
        currency=salary[2],
        salary_period=salary[3],
        timezone_text=_extract_timezone(metadata),
        published_at=_date(raw.get("created_at")),
        collected_at=collected_at or datetime.now(UTC),
    )


def parse_thread(
    payload: object, *, thread_id: int, title: str
) -> tuple[list[JobDTO], dict]:
    if (
        not isinstance(payload, dict)
        or payload.get("id") != thread_id
        or payload.get("title") != title
        or payload.get("author") != "whoishiring"
        or payload.get("type") != "story"
        or payload.get("parent_id") is not None
        or payload.get("deleted")
        or payload.get("dead")
        or not isinstance(payload.get("children"), list)
    ):
        raise CollectionError("Hacker News returned an invalid hiring thread")
    jobs, seen, malformed = [], set(), 0
    report = {
        "thread_id": thread_id,
        "thread_title": title,
        "top_level_received": len(payload["children"]),
        "parsed": 0,
        "ignored": 0,
        "multi_role": 0,
        "ambiguous": 0,
        "remote_known": 0,
    }
    now = datetime.now(UTC)
    for raw in payload["children"]:
        try:
            job = parse_comment(raw, thread_id=thread_id, collected_at=now)
        except (ValueError, TypeError) as exc:
            malformed += 1
            safe_id = (
                raw.get("id")
                if isinstance(raw, dict) and type(raw.get("id")) is int
                else None
            )
            logger.warning(
                "Hacker News skipped comment id=%s error=%s",
                safe_id,
                type(exc).__name__,
            )
            job = None
        if job is None or job.external_id in seen:
            report["ignored"] += 1
            continue
        seen.add(job.external_id)
        jobs.append(job)
        header = job.description.splitlines()[0]
        metadata = "|".join(header.split("|")[1:]) if job.company else header
        remote_known = _extract_remote(metadata) is not None
        report["remote_known"] += int(remote_known)
        report["multi_role"] += int(job.title == "Multiple roles")
        report["ambiguous"] += int(
            not remote_known or not job.company or job.title == "Job opening"
        )
    report["parsed"] = len(jobs)
    if payload["children"] and malformed == len(payload["children"]):
        raise CollectionError("Hacker News thread has no valid comment structures")
    return jobs, report


class HackerNewsCollector(BaseJobCollector):
    source_name = "hacker_news"
    api_url = "https://hn.algolia.com/api/v1"
    max_response_bytes = 8 * 1024 * 1024

    def __init__(self, *, timeout: float | None = None):
        super().__init__(timeout=timeout)
        self.last_report: dict = {}

    async def collect(self) -> list[JobDTO]:
        self.last_report = {}
        async with httpx.AsyncClient(
            timeout=self.timeout, headers=self.request_headers, follow_redirects=False
        ) as client:
            now = datetime.now(UTC)
            oldest = (now.replace(day=1) - timedelta(days=1)).replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )
            search = await fetch_json(
                client,
                self.api_url + "/search_by_date",
                source="Hacker News",
                params={
                    "query": "Ask HN: Who is hiring?",
                    "tags": "story,author_whoishiring",
                    "hitsPerPage": "10",
                    "numericFilters": f"created_at_i>={int(oldest.timestamp())}",
                },
                max_response_bytes=self.max_response_bytes,
            )
            identity, title = find_thread(search, now)
            payload = await fetch_json(
                client,
                self.api_url + f"/items/{identity}",
                source="Hacker News",
                params={},
                max_response_bytes=self.max_response_bytes,
            )
        jobs, self.last_report = parse_thread(payload, thread_id=identity, title=title)
        logger.info("Hacker News collection: %s", self.last_report)
        return jobs
