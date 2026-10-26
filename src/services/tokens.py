import re
from collections.abc import Iterable

SKILL_NOISE = {"communication", "team player", "motivated", "responsible"}

TECHNOLOGY_ALIASES = {
    "python": "python",
    "fast api": "fastapi",
    "fastapi": "fastapi",
    "postgres": "postgresql",
    "postgresql": "postgresql",
    "postgre sql": "postgresql",
    "redis": "redis",
    "celery": "celery",
    "docker": "docker",
    "kubernetes": "kubernetes",
    "k8s": "kubernetes",
    "javascript": "javascript",
    "js": "javascript",
    "typescript": "typescript",
    "ts": "typescript",
    "nodejs": "nodejs",
    "node js": "nodejs",
    "node.js": "nodejs",
    "node": "nodejs",
    "ms excel": "excel",
    "microsoft excel": "excel",
    # Accept compact tokens saved by the old normalizer without rewriting rows.
    "msexcel": "excel",
    "microsoftexcel": "excel",
    "uxresearch": "ux research",
    "b2bsales": "b2b sales",
    "talentacquisition": "talent acquisition",
    "customersupport": "customer support",
    "powerbi": "power bi",
    "googleads": "google ads",
    "googleadsense": "google adsense",
}


def normalize_technology(value: str | None) -> str:
    if value is None:
        return ""
    cleaned = re.sub(r"[^\w+#]+", " ", str(value).casefold()).replace("_", " ").strip()
    cleaned = " ".join(cleaned.split())
    return TECHNOLOGY_ALIASES.get(cleaned, cleaned)


def contains_term(text: str, term: str) -> bool:
    """Literal Unicode word boundaries, preserving multiword skills and symbols."""
    term = " ".join(term.casefold().split())
    text = " ".join(text.casefold().split())
    return bool(term and re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text))


def matches_skill(skill: str, tags: Iterable[str], text: str) -> bool:
    """Use the same aliases and word boundaries for every skill preference."""
    canonical = normalize_technology(skill)
    if not canonical:
        return False
    if any(normalize_technology(tag) == canonical for tag in tags):
        return True
    spellings = {
        canonical,
        *(alias for alias, target in TECHNOLOGY_ALIASES.items() if target == canonical),
    }
    text = " ".join(text.casefold().split())
    return any(
        re.search(r"(?<![\w+#])" + re.escape(spelling) + r"(?![\w+#])", text)
        is not None
        for spelling in spellings
    )
