"""Shared filtering of explicit source skill/category labels."""

import re

# Explicit technical skills/categories only; never search job descriptions.
TECHNICAL_CATEGORIES = {
    "python",
    "django",
    "fastapi",
    "postgresql",
    "redis",
    "celery",
    "docker",
    "javascript",
    "typescript",
    "node.js",
    "nest.js",
    "react",
    "vue",
    "angular",
    "java",
    "spring",
    "go",
    "golang",
    "rust",
    "ruby",
    "rails",
    "php",
    "laravel",
    "c",
    "c++",
    "c#",
    ".net",
    "sql",
    "mysql",
    "mongodb",
    "kubernetes",
    "aws",
    "azure",
    "gcp",
    "devops",
    "backend",
    "back-end dev",
    "front-end dev",
    "full stack dev",
    "api development",
    "database",
    "mobile app dev",
    "cross-browser development",
    "ai model development",
    "artificial intelligence (ai)",
    "back-end programming",
    "front-end programming",
    "full-stack programming",
    "devops and sysadmin",
}


def technical_categories(values: list[str], *, role_labels: bool = False) -> list[str]:
    found = list(
        dict.fromkeys(
            value.strip()
            for value in values
            if value.strip().lower() in TECHNICAL_CATEGORIES
        )
    )
    if role_labels:
        # Some APIs label categories Python-Developer rather than Python.
        # Match only explicit category tokens; short ambiguous skills such as
        # Go and C are accepted only as complete labels, never as role fragments.
        for value in values:
            category = re.sub(r"[-_]+", " ", value.lower())
            for skill in sorted(TECHNICAL_CATEGORIES):
                if (
                    len(skill) >= 4
                    and re.search(r"(?<!\w)" + re.escape(skill) + r"(?!\w)", category)
                    and skill not in found
                ):
                    found.append(skill)
    return found
