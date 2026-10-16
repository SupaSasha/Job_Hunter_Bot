"""Conservative numeric salary parsing shared by text and structured feeds."""

import re
from decimal import Decimal

CURRENCIES = "USD|EUR|GBP|UAH|CAD|AUD|NZD|CHF|PLN|BRL|UYU"
AMOUNT = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
SALARY = re.compile(
    rf"(?<!\w)(?P<currency>USD|EUR|GBP|[$€£])\s*"
    rf"(?P<low>{AMOUNT})(?P<low_k>k)?"
    rf"(?:\s*(?:[-–—]|to)\s*[$€£]?\s*(?P<high>{AMOUNT})(?P<high_k>k)?)?"
    r"(?![\w,.])",
    re.IGNORECASE,
)


def parse_salary_text(
    text: str, *, exact: bool = False
) -> tuple[int | None, int | None, str | None, str | None]:
    pattern = SALARY
    if exact:
        text = text.strip()
        suffix_form = re.fullmatch(
            rf"(?P<amount>{AMOUNT}k?(?:\s*[-–—]\s*{AMOUNT}k?)?)\s+"
            rf"(?P<currency>{CURRENCIES})(?P<period>.*)",
            text,
            re.I,
        )
        if suffix_form:
            text = (
                suffix_form["currency"]
                + " "
                + suffix_form["amount"]
                + suffix_form["period"]
            )
        pattern = re.compile(SALARY.pattern.replace("USD|EUR|GBP", CURRENCIES), re.I)
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        return None, None, None, None
    match = matches[0]
    if exact and (
        match.start() != 0
        or not re.fullmatch(
            r"\s*(?:(?:/|per\s+)(?:h(?:ou)?r?s?|hour|year|yr|annum))?\s*",
            text[match.end() :],
            re.I,
        )
    ):
        return None, None, None, None
    if match["high"] and bool(match["low_k"]) != bool(match["high_k"]):
        return None, None, None, None

    def amount(name, suffix):
        value = Decimal(match[name].replace(",", "")) * (1000 if match[suffix] else 1)
        return int(value) if value == value.to_integral_value() else None

    low = amount("low", "low_k")
    high = amount("high", "high_k") if match["high"] else low
    if low is None or high is None or low > high or high > 2_147_483_647:
        return None, None, None, None
    currency = {"€": "EUR", "£": "GBP", "$": None}.get(
        match["currency"], match["currency"].upper()
    )
    if exact and currency is None:
        return None, None, None, None
    period = None
    suffix = text[match.end() : match.end() + 25]
    if re.match(r"\s*(?:/|per\s+)(?:h(?:ou)?r?s?|hour)\b", suffix, re.I):
        period = "hourly"
    elif re.match(r"\s*(?:/|per\s+)(?:year|yr|annum)\b", suffix, re.I):
        period = "yearly"
    return low, high, currency, period
