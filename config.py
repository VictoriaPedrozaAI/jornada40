"""Legal and payroll parameters. Source of truth: docs/LFT_rules.md §9."""
from __future__ import annotations

from decimal import Decimal

# Art. 59 LFT + Transitorio Segundo (DOF 2026-05-01)
WEEKLY_MAX_ORDINARY: dict[int, int] = {2026: 48, 2027: 46, 2028: 44, 2029: 42, 2030: 40}

# Salario mínimo diario (CONASAMI). Add each year when published (usually December).
MIN_WAGE_DAILY: dict[int, dict[str, Decimal]] = {
    2026: {"general": Decimal("315.04"), "zlfn": Decimal("440.87")},
}

SALARY_ZONES = ("general", "zlfn")
DEFAULT_ZONE = "general"

# Days used to convert a period salary into salario diario (SD).
# Monthly divisor 30 is common payroll practice; some clients use 30.4. Keep configurable.
PERIOD_DAYS: dict[str, Decimal] = {
    "daily": Decimal("1"),
    "weekly": Decimal("7"),
    "biweekly": Decimal("15"),  # quincenal
    "monthly": Decimal("30"),
}

MINOR_AGE = 18


def weekly_max_ordinary(year: int) -> int:
    if year in WEEKLY_MAX_ORDINARY:
        return WEEKLY_MAX_ORDINARY[year]
    return WEEKLY_MAX_ORDINARY[max(WEEKLY_MAX_ORDINARY)] if year > max(WEEKLY_MAX_ORDINARY) else 48


def min_wage(year: int, zone: str) -> tuple[Decimal, int]:
    """Return (daily minimum wage, year actually used). Falls back to latest published year."""
    known = sorted(MIN_WAGE_DAILY)
    used = year if year in MIN_WAGE_DAILY else max((y for y in known if y <= year), default=known[0])
    return MIN_WAGE_DAILY[used][zone], used


# Art. 74 LFT días de descanso obligatorio (election days added per electoral calendar)
FERIADOS: set[str] = {
    "2026-01-01", "2026-02-02", "2026-03-16", "2026-05-01", "2026-09-16", "2026-11-16", "2026-12-25",
    "2027-01-01", "2027-02-01", "2027-03-15", "2027-05-01", "2027-06-06", "2027-09-16", "2027-11-15",
    "2027-12-25",
}

# Art. 66/68: weekly overtime paid at 2x, then up to 4 h at 3x
OVERTIME_CAP_2X: dict[int, int] = {2026: 9, 2027: 9, 2028: 10, 2029: 11, 2030: 12}
OVERTIME_BAND_3X_H = 4
OVERTIME_MAX_H_PER_DAY = 4
OVERTIME_MAX_DAYS_PER_WEEK = 4
MAX_CONTINUOUS_H = 12
MAX_CONSECUTIVE_WORK_DAYS = 6  # Art. 69: 1 rest day per 6 worked
MINOR_MAX_H_PER_DAY = 6


def overtime_cap_2x(year: int) -> int:
    return OVERTIME_CAP_2X.get(year, OVERTIME_CAP_2X[max(OVERTIME_CAP_2X)] if year > 2030 else 9)
