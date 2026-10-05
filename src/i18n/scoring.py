import re

from src.i18n import DEFAULT_LANGUAGE, Language, display_label, resolve_language, t

STATIC_RULES = {
    "Base score: +50": "score.base",
    "Remote: +10": "score.remote",
    "Full-time: +3": "score.full_time",
    "Region is not specified: -2": "score.region_penalty",
    "Remote region is unknown": "score.region_unknown",
    "Timezone is not specified: -2": "score.timezone_penalty",
    "Timezone is not specified": "score.timezone_missing",
    "Timezone compatible: +10": "score.timezone_compatible",
    "Timezone distance: 5+ hours: -20": "score.timezone_far",
    "Experience level is not specified": "score.experience_missing",
    "Salary is not specified: -2": "score.salary_penalty",
    "Salary is not specified": "score.salary_missing",
    "Employment type is not specified": "score.employment_missing",
}
RULE_PATTERNS = (
    (
        r"Preferred technology (?P<technology>.+): (?P<points>[+-]\d+)",
        "score.preferred",
    ),
    (r"Keyword: (?P<keyword>.+): \+3", "score.keyword"),
    (r"(?P<region>.+) region: (?P<points>[+-]\d+)", "score.region"),
    (
        r"Timezone distance: (?P<distance>[\d.]+) hour\(s\): (?P<points>[+-]?\d+)",
        "score.timezone_distance",
    ),
    (
        r"Timezone distance: (?P<distance>[\d.]+) hours: (?P<points>[+-]?\d+)",
        "score.timezone_distance",
    ),
    (r"(?P<level>.+) level: (?P<points>[+-]\d+)", "score.level"),
    (r"Title seniority: (?P<level>.+): (?P<points>[+-]\d+)", "score.title_seniority"),
    (
        r"Requires (?P<years>\d+)\+ years of experience: (?P<points>[+-]\d+)",
        "score.years",
    ),
)
REGION_VALUES = {
    "Worldwide": "worldwide",
    "LATAM": "latam",
    "Uruguay": "uruguay",
    "South America": "south_america",
    "Americas": "americas",
}


def format_score_rule(rule: str, language: Language = DEFAULT_LANGUAGE) -> str:
    """Localize presentation of legacy rule explanations, leaving scoring untouched.

    Technology names and keyword data remain unchanged. Unknown custom rule text
    is preserved rather than treated as a translation key or vacancy content.
    """
    if resolve_language(language) == DEFAULT_LANGUAGE:
        return rule
    if rule in STATIC_RULES:
        return t(STATIC_RULES[rule], language)
    for pattern, key in RULE_PATTERNS:
        match = re.fullmatch(pattern, rule)
        if match:
            params = match.groupdict()
            if "region" in params:
                params["region"] = display_label(
                    REGION_VALUES.get(params["region"], params["region"]), language
                )
            if "level" in params:
                params["level"] = display_label(params["level"].lower(), language)
            return t(key, language, **params)
    return rule
