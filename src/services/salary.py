"""Compare user monthly minimums only with known comparable salary periods."""

from decimal import Decimal


def monthly_salary(amount: int | None, period: str | None) -> Decimal | None:
    if amount is None or period is None:
        return None
    period = period.strip().casefold()
    if period in {"month", "monthly"}:
        return Decimal(amount)
    if period in {"year", "yearly", "annual", "annually"}:
        return Decimal(amount) / 12
    # Hourly/daily/weekly pay needs a work schedule; never invent one.
    return None
