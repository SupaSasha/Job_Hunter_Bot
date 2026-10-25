import re

from src.i18n import DEFAULT_LANGUAGE, Language, resolve_language, t

STATIC_RULES = {
    "Base score: +50": "score.base",
    "Region is not specified: -2": "score.region_penalty",
    "Remote region is unknown": "score.region_unknown",
    "Timezone is not specified: -2": "score.timezone_penalty",
    "Timezone is not specified": "score.timezone_missing",
    "Experience level is unknown: -2": "score.experience_unknown",
    "Experience level is not specified": "score.experience_missing",
    "Salary is not specified: -2": "score.salary_penalty",
    "Salary is not specified": "score.salary_missing",
    "Salary currency is unknown: -2": "score.salary_currency_unknown",
    "Salary currency is not specified": "score.salary_currency_missing",
    "Employment type is unknown: -2": "score.employment_unknown",
    "Employment type is not specified": "score.employment_missing",
}
RULE_PATTERNS = (
    (
        r"Preferred skills matched \((?P<matched>\d+/\d+)\): \+(?P<points>\d+)",
        "score.preferred",
    ),
    (
        r"Required skills matched \((?P<matched>\d+/\d+)\): \+(?P<points>\d+)",
        "score.required",
    ),
    (
        r"Keywords matched \((?P<matched>\d+/\d+)\): \+(?P<points>\d+)",
        "score.keyword",
    ),
    (
        r"Region matches user preferences: \+(?P<points>\d+)",
        "score.region",
    ),
    (r"Timezone compatible: \+(?P<points>\d+)", "score.timezone_compatible"),
    (
        r"Timezone within (?P<distance>[12]) hours?: \+(?P<points>\d+)",
        "score.timezone_distance",
    ),
    (
        r"Timezone difference: (?P<distance>[\d.]+) hours: no adjustment",
        "score.timezone_no_adjustment",
    ),
    (
        r"Timezone differs by (?P<distance>[\d.]+)\+? hours: (?P<points>-\d+)",
        "score.timezone_far",
    ),
    (
        r"Experience matches user preferences: \+(?P<points>\d+)",
        "score.experience_match",
    ),
    (
        r"Inferred experience differs from user preferences: (?P<points>-\d+)",
        "score.experience_mismatch",
    ),
    (r"Salary meets user minimum: \+(?P<points>\d+)", "score.salary_match"),
    (
        r"Employment matches user preferences: \+(?P<points>\d+)",
        "score.employment_match",
    ),
    (
        r"Remote matches user preference: \+(?P<points>\d+)",
        "score.remote_match",
    ),
)


def format_score_rule(rule: str, language: Language = DEFAULT_LANGUAGE) -> str:
    """Localize generic user-relative score rules without altering their meaning."""
    if resolve_language(language) == DEFAULT_LANGUAGE:
        return rule
    if rule in STATIC_RULES:
        return t(STATIC_RULES[rule], language)
    for pattern, key in RULE_PATTERNS:
        match = re.fullmatch(pattern, rule)
        if match:
            params = match.groupdict()
            return t(key, language, **params)
    return rule
