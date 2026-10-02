import re

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
}


def normalize_technology(value: str | None) -> str:
    if value is None:
        return ""
    cleaned = re.sub(r"[^a-z0-9+#]+", " ", str(value).lower()).strip()
    cleaned = " ".join(cleaned.split())
    return TECHNOLOGY_ALIASES.get(cleaned, cleaned.replace(" ", ""))
