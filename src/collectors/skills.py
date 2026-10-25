"""Preserve structured professional skills; keep source categories separate."""

import re

from src.services.tokens import normalize_technology

# A small vocabulary for deterministic text extraction only, never an input whitelist.
EXPLICIT_SKILL_TERMS = {
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
EXPLICIT_SKILL_TERMS.update(
    {
        "figma",
        "excel",
        "salesforce",
        "sap",
        "seo",
        "google ads",
        "google adsense",
        "accounting",
        "recruiting",
        "customer support",
        "autocad",
        "quickbooks",
        "hubspot",
        "power bi",
        "tableau",
        "ux research",
        "b2b sales",
        "talent acquisition",
    }
)
NOISE = {"communication", "team player", "motivated", "responsible", "leadership"}
# Only category labels are checked here; structured skills are profession-neutral.
PROFESSION_CATEGORIES = {
    "engineering",
    "marketing",
    "sales",
    "sales and marketing",
    "finance",
    "design",
    "programming",
    "product",
    "operations",
    "human resources",
    "legal",
    "data",
    "support",
    "customer service",
    "management",
    "product management",
    "project management",
    "back end programming",
    "front end programming",
    "full stack programming",
    "devops and sysadmin",
    "go to market",
    "c level executive",
}


def source_skills(values: list[str]) -> list[str]:
    found, seen = [], set()
    for value in values:
        canonical = normalize_technology(value)
        if canonical and canonical not in NOISE and canonical not in seen:
            found.append(value.strip())
            seen.add(canonical)
    return found


def category_skills(values: list[str]) -> list[str]:
    """Keep specific labels; profession/category/role names stay out of skills."""
    result = []
    for value in values:
        canonical = normalize_technology(value)
        if canonical in PROFESSION_CATEGORIES:
            continue
        if re.search(
            r"\b(?:engineers?|developers?|designers?|managers?|specialists?|"
            r"instructors?|trainers?|tutors?|teachers?|executives?|analysts?)$",
            canonical,
        ):
            continue
        result.append(value)
    return source_skills(result)
