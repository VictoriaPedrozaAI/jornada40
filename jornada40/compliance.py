"""Evaluate a schedule (current or proposed) against the LFT and a coverage requirement.

Weeks are 7-day blocks from plan_start. Overtime = hours above the Art. 61 daily max of each shift
type + ordinary hours above the Art. 59 weekly max. Output feeds the cost engine and the UI.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Callable

from jornada40 import config
from jornada40.ingest.employees import Employee
from jornada40.shifts import Shift

Requirement = Callable[[datetime], int]  # required headcount for the hour starting at dt


@dataclass(frozen=True)
class Finding:
    kind: str  # "VIOLATION" | "OVERTIME" (legal but paid) | "RESTDAY" | "GAP" | "OVERSTAFF"
    rule: str
    employee_id: str | None
    start: datetime | date
    detail: str
    hours: float = 0.0


@dataclass
class EmployeeWeek:
    employee_id: str
    week: int
    worked_h: float = 0.0
    ordinary_h: float = 0.0
    ot_2x_h: float = 0.0
    ot_3x_h: float = 0.0
    shifts_by_type: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    sundays: int = 0
    feriados: int = 0
    restdays_worked: int = 0  # Art. 73: shifts on the employee's designated rest day
    restday_h: float = 0.0


@dataclass
class Report:
    weeks: list[EmployeeWeek]
    findings: list[Finding]

    def by_kind(self, kind: str) -> list[Finding]:
        return [f for f in self.findings if f.kind == kind]

    @property
    def total_ot_h(self) -> float:
        return sum(w.ot_2x_h + w.ot_3x_h for w in self.weeks)


def evaluate(
    shifts: list[Shift],
    plan_start: date,
    n_days: int,
    year: int,
    requirement: Requirement | None = None,
    employees: dict[str, Employee] | None = None,
    cyclic: bool = False,
    rest_days: dict[str, set[int]] | None = None,
) -> Report:
    """cyclic=True treats the horizon as a repeating rotation (e.g. a 4-week template), so the
    last night shift also covers the first morning. Only affects coverage.

    rest_days: designated weekly rest days per employee (0=Mon..6=Sun). A shift on one of them is
    priced under Art. 73 (paid day + 2x) and is excluded from ordinary/overtime hours, to avoid
    paying the same hours twice."""
    weekly_max = config.weekly_max_ordinary(year)
    cap2 = config.overtime_cap_2x(year)
    findings: list[Finding] = []
    weeks: list[EmployeeWeek] = []

    by_emp: dict[str, list[Shift]] = defaultdict(list)
    for s in shifts:
        by_emp[s.employee_id].append(s)

    for emp_id, emp_shifts in sorted(by_emp.items()):
        emp_shifts.sort(key=lambda s: s.start)
        emp = (employees or {}).get(emp_id)

        # --- per week: hours, overtime bands, OT caps ---
        for wk in range((n_days + 6) // 7):
            w_start = plan_start + timedelta(days=7 * wk)
            ws = [s for s in emp_shifts if w_start <= s.day < w_start + timedelta(days=7)]
            if not ws:
                continue
            ew = EmployeeWeek(emp_id, wk + 1)
            daily_excess = 0.0
            ot_days = 0
            emp_rest = (rest_days or {}).get(emp_id, set())
            for s in ws:
                ew.sundays += s.day.weekday() == 6
                if s.day.weekday() in emp_rest:
                    ew.restdays_worked += 1
                    ew.restday_h += s.hours
                    findings.append(Finding("RESTDAY", "Art. 73 work on rest day", emp_id, s.start,
                                            f"{s.hours:g} h on designated rest day", s.hours))
                    continue
                ew.worked_h += s.hours
                ew.ordinary_h += s.ordinary_hours
                ew.shifts_by_type[s.jornada_type] += 1
                ew.feriados += s.day.isoformat() in config.FERIADOS
                if s.daily_excess_hours > 0:
                    daily_excess += s.daily_excess_hours
                    ot_days += 1
                    if s.daily_excess_hours > config.OVERTIME_MAX_H_PER_DAY:
                        findings.append(Finding("VIOLATION", "Art. 66 max 4 h OT/day", emp_id, s.start,
                                                f"{s.daily_excess_hours:g} h OT in one shift", s.daily_excess_hours))
            weekly_excess = max(0.0, ew.ordinary_h - weekly_max)
            ew.ordinary_h -= weekly_excess
            ot = daily_excess + weekly_excess
            ew.ot_2x_h = min(ot, cap2)
            ew.ot_3x_h = max(0.0, ot - cap2)
            if weekly_excess:
                findings.append(Finding("OVERTIME", "Art. 59 weekly max", emp_id,
                                        w_start, f"{ew.worked_h:g} h worked vs {weekly_max} h ordinary max",
                                        weekly_excess))
            if ew.ot_3x_h > config.OVERTIME_BAND_3X_H:
                findings.append(Finding("VIOLATION", "Art. 68 OT above absolute cap", emp_id, w_start,
                                        f"{ot:g} h OT > {cap2 + config.OVERTIME_BAND_3X_H} h", ot))
            if ot_days > config.OVERTIME_MAX_DAYS_PER_WEEK:
                findings.append(Finding("VIOLATION", "Art. 66 OT on max 4 days/week", emp_id, w_start,
                                        f"overtime on {ot_days} days (shift-type excess)", 0))
            weeks.append(ew)

        # --- continuous work blocks (back-to-back shifts) > 12 h ---
        block_start, block_end = emp_shifts[0].start, emp_shifts[0].end
        for s in emp_shifts[1:] + [None]:
            if s is not None and s.start <= block_end:
                block_end = max(block_end, s.end)
                continue
            h = (block_end - block_start).total_seconds() / 3600
            if h > config.MAX_CONTINUOUS_H:
                findings.append(Finding("VIOLATION", "Art. 68 max 12 h/day", emp_id, block_start,
                                        f"{h:g} h continuous (back-to-back shifts)", h))
            if s is not None:
                block_start, block_end = s.start, s.end

        # --- 6x1 rest rule ---
        worked_days = sorted({s.day for s in emp_shifts})
        run, run_start = 1, worked_days[0]
        for prev, cur in zip(worked_days, worked_days[1:] + [None]):
            if cur is not None and cur - prev == timedelta(days=1):
                run += 1
                continue
            if run > config.MAX_CONSECUTIVE_WORK_DAYS:
                findings.append(Finding("VIOLATION", "Art. 69 rest day per 6 worked", emp_id, run_start,
                                        f"{run} consecutive days worked", 0))
            if cur is not None:
                run, run_start = 1, cur

        # --- minors ---
        if emp is not None:
            for s in emp_shifts:
                if not emp.is_minor(s.day):
                    continue
                if s.hours > config.MINOR_MAX_H_PER_DAY:
                    findings.append(Finding("VIOLATION", "Art. 177 minor max 6 h/day", emp_id, s.start,
                                            f"{s.hours:g} h shift", s.hours))
                if s.day.weekday() == 6 or s.day.isoformat() in config.FERIADOS:
                    findings.append(Finding("VIOLATION", "Art. 178 minor on Sunday/feriado", emp_id, s.start,
                                            "minor scheduled on Sunday or feriado", s.hours))

    # --- coverage vs requirement, hourly ---
    if requirement is not None:
        t0 = datetime.combine(plan_start, datetime.min.time())
        runs: dict[str, list] = {"GAP": [], "OVERSTAFF": []}
        cov_shifts = list(shifts)
        if cyclic:
            wrap = timedelta(days=n_days)
            cov_shifts += [Shift(s.employee_id, s.day - wrap, s.code, s.start - wrap, s.end - wrap)
                           for s in shifts if s.end > t0 + wrap]
        for i in range(n_days * 24):
            t = t0 + timedelta(hours=i)
            have = sum(1 for s in cov_shifts if s.start <= t < s.end)
            need = requirement(t)
            for kind, delta in (("GAP", need - have), ("OVERSTAFF", have - need)):
                r = runs[kind]
                if delta > 0 and r and r[-1][1] == t:
                    r[-1][1] = t + timedelta(hours=1)
                    r[-1][2] += delta
                elif delta > 0:
                    r.append([t, t + timedelta(hours=1), delta])
        for kind, rs in runs.items():
            for a, b, person_h in rs:
                findings.append(Finding(kind, "coverage", None, a, f"{a:%a %d %b %H:%M} -> {b:%a %d %b %H:%M}",
                                        float(person_h)))
    return Report(weeks, findings)
