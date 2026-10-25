"""ISO country input and CLDR region membership, without runtime geo services."""

import json
import re
import unicodedata
from pathlib import Path

_DATA = json.loads(
    (Path(__file__).resolve().parents[1] / "data" / "countries.json").read_text()
)


def _key(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[^\w]+", "_", value).strip("_")


COUNTRIES: dict[str, str] = {}
COUNTRY_LABELS: dict[str, str] = {}
COUNTRY_CODES: dict[str, str] = {}
for _row in _DATA["countries"]:
    _canonical = (
        "us" if _row["alpha_2"] == "US" else _key(_row.get("common_name", _row["name"]))
    )
    COUNTRY_LABELS[_canonical] = _row.get("common_name", _row["name"])
    COUNTRY_CODES[_canonical] = _row["alpha_2"]
    for _value in _row.values():
        COUNTRIES[_key(_value)] = _canonical

for _alias, _code in {
    "UK": "GB",
    "United Kingdom": "GB",
    "South Korea": "KR",
    "North Korea": "KP",
    "Russia": "RU",
    "Vietnam": "VN",
    "Turkey": "TR",
    "Taiwan": "TW",
    "Bolivia": "BO",
    "Venezuela": "VE",
    "Iran": "IR",
    "Tanzania": "TZ",
    "Moldova": "MD",
    "Syria": "SY",
    "Laos": "LA",
    "Czech Republic": "CZ",
    "UAE": "AE",
    "España": "ES",
    "Brasil": "BR",
    "México": "MX",
    "Estados Unidos": "US",
}.items():
    COUNTRIES[_key(_alias)] = COUNTRIES[_key(_code)]

REGION_MEMBERS = {
    region: frozenset(codes) for region, codes in _DATA["regions"].items()
}
REGION_ALIASES = {
    "anywhere": "worldwide",
    "global": "worldwide",
    "remote_worldwide": "worldwide",
    "anywhere_in_the_world": "worldwide",
    "latin_america": "latam",
    "latin_america_and_the_caribbean": "latam",
    "the_americas": "americas",
    "european_union": "eu",
    "asia_pacific": "apac",
    "us_only": "us_only",
    "usa_only": "us_only",
    "united_states_only": "us_only",
    "u_s": "us",
}


def normalize_country(value: str) -> str | None:
    return COUNTRIES.get(_key(value))


def normalize_region(value: str) -> str:
    key = _key(value)
    return (
        REGION_ALIASES.get(key)
        or normalize_country(value)
        or (key if key in REGION_MEMBERS else value.strip().casefold())
    )


def region_members(value: str) -> frozenset[str]:
    value = normalize_region(value)
    if value == "us_only":
        return frozenset({"US"})
    if value in COUNTRY_CODES:
        return frozenset({COUNTRY_CODES[value]})
    return REGION_MEMBERS.get(value, frozenset())


def country_label(value: str) -> str:
    return COUNTRY_LABELS.get(normalize_country(value) or value, value)
