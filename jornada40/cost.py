"""Price an evaluated roster in MXN (docs/LFT_rules.md §8).

Per employee-week, on top of the weekly salary (7 x SD, rest days are paid):
  overtime 2x / 3x at hourly rate h = SD / 8           (assumption §5.2, configurable)
  prima dominical 0.25 x SD per Sunday worked          (Art. 71)
  feriado worked: +2 x SD                               (Art. 75)
  rest day worked: +2 x SD                              (Art. 73; a feriado on a rest day is priced once)
Overstaffing is reported separately as capacity (person-hours above requirement x average
floor hourly rate), not as cash (decision D22).
Amounts are rounded to centavos; the optimizer will use integer centavos (D19).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from jornada40.compliance import Report

CENT = Decimal("0.01")


def _d(x: float | Decimal) -> Decimal:
    return Decimal(str(x)).quantize(CENT, ROUND_HALF_UP)


@dataclass
class CostSummary:
    base_salary: Decimal = Decimal(0)
    overtime_2x: Decimal = Decimal(0)
    overtime_3x: Decimal = Decimal(0)
    prima_dominical: Decimal = Decimal(0)
    feriado_extra: Decimal = Decimal(0)
    restday_extra: Decimal = Decimal(0)
    overtime_hours: float = 0.0
    restdays_worked: int = 0
    overstaff_person_h: float = 0.0
    overstaff_value: Decimal = Decimal(0)
    understaff_person_h: float = 0.0
    understaff_peak_person_h: float = 0.0
    by_employee: dict[str, Decimal] = field(default_factory=dict)

    @property
    def premiums(self) -> Decimal:
        return (self.overtime_2x + self.overtime_3x + self.prima_dominical
                + self.feriado_extra + self.restday_extra)

    @property
    def total_cash(self) -> Decimal:
        return self.base_salary + self.premiums

    def as_dict(self) -> dict[str, str | float | int]:
        keys = ["base_salary", "overtime_2x", "overtime_3x", "prima_dominical", "feriado_extra",
                "restday_extra", "premiums", "total_cash", "overtime_hours", "restdays_worked",
                "overstaff_person_h", "overstaff_value", "understaff_person_h", "understaff_peak_person_h"]
        return {k: getattr(self, k) for k in keys}


def coverage_table(shifts, requirement, slot_minutes: int = 60) -> "pd.DataFrame":
    """Have vs need per slot. requirement: DataFrame(date, hour, required_headcount, is_peak).
    Each requirement hour is split into 60/slot_minutes slots; a person counts in a slot if on shift
    at its start. Slots outside the requirement where someone is on shift get need = 0.
    Column slot_h = slot length in hours (person-hours = headcount x slot_h)."""
    import pandas as pd
    from datetime import datetime, timedelta

    step = timedelta(minutes=slot_minutes)
    rows = {}
    for d, h, n, p in zip(requirement["date"], requirement["hour"], requirement["required_headcount"],
                          requirement["is_peak"]):
        t0 = datetime.fromisoformat(str(d)) + timedelta(hours=int(h))
        for k in range(60 // slot_minutes):
            rows[t0 + k * step] = (int(n), int(p))
    for s in shifts:
        t = s.start.replace(minute=(s.start.minute // slot_minutes) * slot_minutes, second=0)
        while t < s.end:
            rows.setdefault(t, (0, 0))
            t += step
    import numpy as np

    out = pd.DataFrame([(t, n, p) for t, (n, p) in rows.items()], columns=["t", "need", "is_peak"]).sort_values("t")
    starts = np.sort(np.array([s.start for s in shifts], dtype="datetime64[m]"))
    ends = np.sort(np.array([s.end for s in shifts], dtype="datetime64[m]"))
    ts = out["t"].to_numpy(dtype="datetime64[m]")
    # on shift at t  <=>  start <= t < end  ->  #starts <= t  -  #ends <= t
    out["have"] = np.searchsorted(starts, ts, side="right") - np.searchsorted(ends, ts, side="right")
    out["slot_h"] = slot_minutes / 60
    return out.reset_index(drop=True)


def price(report: Report, daily_salary: dict[str, Decimal], weeks_in_horizon: int = 1,
          coverage: "pd.DataFrame | None" = None, floor_ids: set[str] | None = None,
          hourly_divisor: Decimal = Decimal(8)) -> CostSummary:
    c = CostSummary()
    for eid, sd in daily_salary.items():
        c.base_salary += _d(sd * 7 * weeks_in_horizon)
        c.by_employee[eid] = _d(sd * 7 * weeks_in_horizon)
    for w in report.weeks:
        sd = Decimal(str(daily_salary[w.employee_id]))
        h = sd / hourly_divisor
        extra = {
            "overtime_2x": _d(Decimal(str(w.ot_2x_h)) * 2 * h),
            "overtime_3x": _d(Decimal(str(w.ot_3x_h)) * 3 * h),
            "prima_dominical": _d(Decimal("0.25") * sd * w.sundays),
            "feriado_extra": _d(2 * sd * w.feriados),
            "restday_extra": _d(2 * sd * w.restdays_worked),
        }
        for k, v in extra.items():
            setattr(c, k, getattr(c, k) + v)
        c.by_employee[w.employee_id] += sum(extra.values())
        c.overtime_hours += w.ot_2x_h + w.ot_3x_h
        c.restdays_worked += w.restdays_worked

    ids = floor_ids or set(daily_salary)
    avg_h = sum(Decimal(str(daily_salary[i])) for i in ids) / len(ids) / hourly_divisor
    if coverage is not None:
        diff = coverage["have"] - coverage["need"]
        w = coverage["slot_h"] if "slot_h" in coverage else 1.0
        c.overstaff_person_h = float((diff.clip(lower=0) * w).sum())
        c.understaff_person_h = float(((-diff).clip(lower=0) * w).sum())
        c.understaff_peak_person_h = float(((-diff).clip(lower=0) * w)[coverage["is_peak"] == 1].sum())
    c.overstaff_value = _d(Decimal(str(c.overstaff_person_h)) * avg_h)
    return c
