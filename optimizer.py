"""Weekly roster optimizer for one store (OR-Tools CP-SAT). Decisions D17-D20.

Model (30-minute slots):
- Candidate shifts = legal templates generated from store hours: diurna 8 h ending by 20:00,
  mixta 7.5 h ending by closing crew time with < 3.5 h after 20:00. Every template is within
  its Art. 61 daily max, so no daily overtime exists by construction.
- Full-time week types within the weekly max, all with >= 1 rest day (Art. 69: 1 per 6 worked):
  5 days x 8 h (2 rest days) or 6 days x 6.5 h (1 rest day) under 40 h; optionally a 6th full
  day as priced overtime (Art. 66). 7 days never. 5 x 2 is NOT a legal requirement (D35).
- Coverage per slot: people on shift + under - over = need. Peak shortfall has a prohibitive
  penalty, off-peak shortfall a high one, overstaffing a small one (capacity value).
- Objective (integer centavos, D19): overtime + prima dominical + feriado 2x SD + penalties.
- Formulated on counts (people per template per day, employees per weekly pattern) instead of
  one boolean per employee x day x shift: interchangeable employees make the per-employee model
  highly symmetric (first version: 38% gap after 30 s); the count model solves to optimality.
Non-floor staff (admin) are not optimized; they keep their schedule.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pandas as pd
from ortools.sat.python import cp_model

from jornada40 import config
from jornada40.shifts import Shift, ShiftDef

SLOT = 30  # minutes


@dataclass
class OptimizerSettings:
    year: int = 2030
    time_limit_s: float = 30.0
    # CP-SAT search workers = available CPUs (HF CPU Basic has 2 vCPU; more threads than cores only adds overhead)
    workers: int = field(default_factory=lambda: max(1, min(8, os.cpu_count() or 1)))
    days_per_week: int = 5  # legacy: patterns are built from week types below
    # Art. 69: only 1 rest day per 6 worked is required. 6-day weeks with shorter shifts are legal
    # within the weekly max (e.g. 6 x 6.5 h = 39 h under 40 h). D35.
    allow_six_day_weeks: bool = True
    allow_sixth_day: bool = True  # 6th day with full-length shifts = paid overtime
    # "5": everyone 5 days (2 rest), "6": everyone 6 days (1 rest), "mixed": model decides (D36)
    week_policy: str = "mixed"
    peak_under_penalty_mxn: float = 5_000.0  # per person-hour short at peak
    # per person-hour short off-peak: service-level knob. 150 MXN (~3.5x the average hourly wage)
    # means a 6th day with overtime is only used to fix big off-peak gaps (sensitivity: HANDOVER D31)
    offpeak_under_penalty_mxn: float = 150.0
    overstaff_weight: float = 1.0  # x avg hourly rate per person-hour above need
    start_step_min: int = 30


# Objective components (key -> label). Cash items are estimates at average salary; the exact cash
# cost is recomputed by cost.price() on the final roster. Penalties are weights, not money paid.
OBJECTIVE_COMPONENTS = {
    "overtime": "Horas extra (6.º día completo)",
    "sunday": "Prima dominical",
    "feriado": "Feriados trabajados",
    "peak_short": "Penalización: faltante en hora pico",
    "offpeak_short": "Penalización: faltante fuera de pico",
    "overstaff": "Penalización: horas sobre lo requerido",
    "tiebreak": "Desempate: descansos no consecutivos",
}


@dataclass
class OptimizerResult:
    shifts: list[Shift]
    status: str
    objective_mxn: float
    best_bound_mxn: float
    wall_time_s: float
    templates: list[ShiftDef] = field(default_factory=list)
    # objective broken down by component, MXN (penalties are decision weights, not cash)
    components: dict[str, float] = field(default_factory=dict)

    @property
    def gap_pct(self) -> float:
        if not self.objective_mxn:
            return 0.0
        return max(0.0, (self.objective_mxn - self.best_bound_mxn) / abs(self.objective_mxn) * 100)


def _t(minutes: int) -> time:
    return time((minutes // 60) % 24, minutes % 60)


def generate_templates(open_min: int, close_min: int, pre_min: int, post_min: int,
                       step: int = 30, diurna_len: int = 480, mixta_len: int = 450,
                       tag: str = "") -> list[ShiftDef]:
    """Legal shift templates inside [open - pre, close + post] with the given lengths (minutes).
    diurna: no minute after 20:00; mixta: crosses 20:00 with < 3.5 h of night (Art. 60-61)."""
    first, last = open_min - pre_min, close_min + post_min
    night_start = 20 * 60
    out = []
    for start in range(first, last, step):
        if start + diurna_len <= min(last, night_start):
            out.append(ShiftDef(f"D{_t(start):%H%M}{tag}", _t(start), _t(start + diurna_len),
                                f"diurna {diurna_len / 60:g} h"))
        end = start + mixta_len
        if start < night_start < end <= last and end - night_start < 210:
            out.append(ShiftDef(f"M{_t(start):%H%M}{tag}", _t(start), _t(end), f"mixta {mixta_len / 60:g} h"))
    return out


@dataclass(frozen=True)
class WeekType:
    name: str
    days: int
    diurna_len: int  # minutes
    mixta_len: int
    overtime_h: float  # weekly overtime per employee (upper bound, priced exactly afterwards)


def week_types(year: int, allow_six_day_weeks: bool, allow_sixth_day: bool,
               policy: str = "mixed") -> list[WeekType]:
    """Full-time week types within the legal weekly max. Shift length = weekly max / days, rounded
    down to 30 min and capped by the daily max of the jornada (8 h diurna, 7.5 h mixta)."""
    wmax = config.weekly_max_ordinary(year) * 60

    def length(days: int, cap: int) -> int:
        return min(cap, (wmax // days) // SLOT * SLOT)

    five = WeekType("5d", 5, length(5, 480), length(5, 450), 0.0)
    six = WeekType("6d", 6, length(6, 480), length(6, 450), 0.0)
    if policy == "6":
        return [six]  # a 6th day is already worked: no overtime variant
    out = [five]
    if policy == "mixed" and allow_six_day_weeks:
        out.append(six)
    if allow_sixth_day and six.diurna_len < 480:  # 6th full-length day -> overtime
        out.append(WeekType("6d+ot", 6, 480, 450, max(0.0, 6 * 8 - wmax / 60)))
    return out


def work_patterns(days: int) -> list[tuple[int, ...]]:
    """All weekly patterns with exactly `days` working days (1 = works)."""
    from itertools import combinations
    return [tuple(int(d in on) for d in range(7)) for on in combinations(range(7), days)]


def _consecutive_rest(p: tuple[int, ...]) -> bool:
    off = [d for d in range(7) if not p[d]]
    return len(off) != 2 or (off[1] - off[0]) in (1, 6)


def optimize_store(employees: pd.DataFrame, requirement: pd.DataFrame, store: dict,
                   week_start: date, settings: OptimizerSettings | None = None) -> OptimizerResult:
    """Two stages.
    1) Aggregate CP-SAT (optimal in about a second): for each week type (5 days x 8 h, 6 days x 6.5 h, ...)
       how many people work each shift template each day, and how many employees follow each weekly
       work pattern. Every week type keeps the weekly hours <= legal max and >= 1 rest day (Art. 69).
    2) Assignment: cheapest employees to the costliest patterns (Sunday / overtime / feriado), then each
       day's shifts of a week type to its on-duty employees in a stable order.

    employees: employee_id, daily_salary, [is_minor] - floor staff only (minors excluded in the MVP).
    requirement: date, hour, required_headcount, is_peak (one store, 7 days from week_start).
    store: opening_time, closing_time, pre_open_minutes, post_close_minutes, [day_hours]."""
    st = settings or OptimizerSettings()
    hm = lambda s: int(str(s)[:2]) * 60 + int(str(s)[3:5])  # noqa: E731
    pre, post = int(store.get("pre_open_minutes", 60)), int(store.get("post_close_minutes", 60))
    days = [week_start + timedelta(days=i) for i in range(7)]
    # opening hours per day (v3): store["day_hours"] = {weekday: (open, close) | None (closed)};
    # without it every day uses opening_time / closing_time
    dh = store.get("day_hours")
    window = {d: (dh.get(days[d].weekday()) if dh else (store["opening_time"], store["closing_time"]))
              for d in range(7)}
    open_days = [d for d in range(7) if window[d]]
    wts = [w for w in week_types(st.year, st.allow_six_day_weeks, st.allow_sixth_day, st.week_policy)
           if w.days <= len(open_days)]
    if not wts:  # e.g. 6-day weeks with a store closed 2 days, or fewer than 5 open days
        return OptimizerResult([], "NO_APLICA", math.nan, math.nan, 0.0, [])
    tpl = {(w.name, d): (generate_templates(hm(window[d][0]), hm(window[d][1]), pre, post, st.start_step_min,
                                            w.diurna_len, w.mixta_len) if window[d] else [])
           for w in wts for d in range(7)}
    emp = employees.copy()
    if "is_minor" in emp:
        emp = emp[~emp["is_minor"].astype(bool)]
    sd = dict(zip(emp["employee_id"], emp["daily_salary"].astype(float)))
    n_emp = len(sd)
    avg_sd_c = int(round(sum(sd.values()) / n_emp * 100))
    avg_h_c = avg_sd_c / 8

    need: dict[tuple[int, int], tuple[int, int]] = {}
    for d_str, hr, n, pk in requirement[["date", "hour", "required_headcount", "is_peak"]].itertuples(index=False):
        di = (date.fromisoformat(str(d_str)) - week_start).days
        if 0 <= di < 7:
            for k in range(60 // SLOT):
                need[(di, (int(hr) * 60 + k * SLOT) // SLOT)] = (int(n), int(pk))

    def slots_of(t: ShiftDef) -> range:
        s0 = t.start.hour * 60 + t.start.minute
        return range(s0 // SLOT, (s0 + int(round(t.hours * 60))) // SLOT)

    m = cp_model.CpModel()
    n = {(w.name, d, t): m.new_int_var(0, n_emp, f"n_{w.name}_{d}_{t}")
         for w in wts for d in range(7) for t in range(len(tpl[w.name, d]))}
    # weekly patterns never include a day the store is closed
    y = {(w.name, p): m.new_int_var(0, n_emp, f"y_{w.name}_{i}")
         for w in wts for i, p in enumerate(work_patterns(w.days)) if all(window[d] for d in range(7) if p[d])}
    m.add(sum(y.values()) == n_emp)
    for w in wts:
        for d in range(7):
            m.add(sum(n[w.name, d, t] for t in range(len(tpl[w.name, d])))
                  == sum(v for (wn, p), v in y.items() if wn == w.name and p[d]))

    cover: dict[tuple[int, int], list] = {}
    for (wn, d, t), v in n.items():
        for sl in slots_of(tpl[wn, d][t]):
            cover.setdefault((d, sl), []).append(v)
    groups: dict[str, list] = {k: [] for k in OBJECTIVE_COMPONENTS}
    for key in set(cover) | set(need):
        req, pk = need.get(key, (0, 0))
        under = m.new_int_var(0, max(req, 0), f"u_{key[0]}_{key[1]}")
        over = m.new_int_var(0, n_emp, f"o_{key[0]}_{key[1]}")
        m.add(sum(cover.get(key, [])) + under - over == req)
        pen = st.peak_under_penalty_mxn if pk else st.offpeak_under_penalty_mxn
        groups["peak_short" if pk else "offpeak_short"].append(under * int(pen * 100 * SLOT / 60))
        groups["overstaff"].append(over * int(avg_h_c * st.overstaff_weight * SLOT / 60))
    wt_by_name = {w.name: w for w in wts}
    for (wn, p), v in y.items():
        w = wt_by_name[wn]
        if w.overtime_h:
            groups["overtime"].append(v * int(round(w.overtime_h * 2 * avg_h_c)))
        if w.days == 5 and not _consecutive_rest(p):
            groups["tiebreak"].append(v * 100)  # 1 MXN: prefer consecutive rest days when cost is equal
    for d in range(7):
        on_d = sum(v for (wn, dd, t), v in n.items() if dd == d)
        if days[d].weekday() == 6:
            groups["sunday"].append(on_d * int(round(avg_sd_c * 0.25)))
        if days[d].isoformat() in config.FERIADOS:
            groups["feriado"].append(on_d * 2 * avg_sd_c)
    m.minimize(sum(t for g in groups.values() for t in g))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = st.time_limit_s
    solver.parameters.num_workers = st.workers
    status = solver.solve(m)
    name = solver.status_name(status)
    all_tpl = [t for ts in tpl.values() for t in ts]
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return OptimizerResult([], name, math.nan, math.nan, solver.wall_time, all_tpl)

    # Stage 2: (week type, pattern) -> employees (cheapest to costliest), shifts -> on-duty employees
    sun = [d.weekday() for d in days].index(6)
    fer = [i for i in range(7) if days[i].isoformat() in config.FERIADOS]

    def cost_key(wp: tuple[str, tuple[int, ...]]) -> float:
        w, p = wt_by_name[wp[0]], wp[1]
        return w.overtime_h * 16 + p[sun] * 0.25 + sum(p[i] for i in fer) * 2

    slots_p = sorted((wp for wp, v in y.items() for _ in range(solver.value(v))), key=cost_key, reverse=True)
    by_cost = sorted(sd, key=lambda e: (sd[e], e))
    plan = dict(zip(by_cost, slots_p))
    shifts: list[Shift] = []
    for w in wts:
        members = sorted(e for e, (wn, _) in plan.items() if wn == w.name)
        for d in range(7):
            on = [e for e in members if plan[e][1][d]]
            ts = tpl[w.name, d]
            todo = [t for t in range(len(ts)) for _ in range(solver.value(n[w.name, d, t]))]
            todo.sort(key=lambda t: (ts[t].start, ts[t].code))
            for e, t in zip(on, todo):
                shifts.append(Shift.from_def(e, days[d], ts[t]))
    comps = {k: (solver.value(sum(g)) / 100 if g else 0.0) for k, g in groups.items()}
    return OptimizerResult(shifts, name, solver.objective_value / 100, solver.best_objective_bound / 100,
                           solver.wall_time, all_tpl, comps)


def to_datetime(d: date, minutes: int) -> datetime:
    return datetime.combine(d, time()) + timedelta(minutes=minutes)


def employees_frame(ids: list[str], daily_salary: dict[str, Decimal]) -> pd.DataFrame:
    return pd.DataFrame({"employee_id": ids, "daily_salary": [float(daily_salary[i]) for i in ids]})
