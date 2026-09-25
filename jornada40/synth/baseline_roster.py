"""Baseline ("current") roster for one store, built from docs/baseline_roster_review.md
(client proposal MD_Proposal_Roster.md) plus explicit bad-planning adjustments.

Structure kept from the proposal (Excel-style planning):
- 8 non-shift staff, Mon-Fri 09:00-17:00.
- 3 fixed turns, identical every day: T1 09-17 (17 people), T2 13-21 (17), T3 14-22 (16).
- Each shift employee belongs to one turn and has 2 fixed consecutive rest days.

Bad-planning adjustments (each one is a parameter):
A1 Pre-open 07-09 and closing 22-23 are covered by extending the SAME turn workers' days
   (5 T1 start 07:00, 4 T1 start 08:00, 5 T3 stay to 23:00) -> daily overtime, >4 OT days.
A2 Rest days are granted by preference -> too many weekends off -> Saturday/Sunday short of
   the 50 turn slots -> people are called in on their rest day (Art. 73: paid triple).
A3 Weekday surplus is not re-planned: extra people just work their turn (overstaffing).
A4 Demand is ignored: same headcount every hour/day of the week (weekends, paydays, feriados).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time, timedelta
from decimal import Decimal

import math

import numpy as np
import pandas as pd

from jornada40.shifts import Shift, ShiftDef

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

TURNS = {
    "T1": ShiftDef("T1", time(9), time(17), "Turn 1 09-17"),
    "T2": ShiftDef("T2", time(13), time(21), "Turn 2 13-21"),
    "T3": ShiftDef("T3", time(14), time(22), "Turn 3 14-22"),
}
# Roles per turn per day (proposal §3)
TURN_ROLES = {
    "T1": {"supervisor": 2, "cashier": 6, "warehouse": 3, "security": 2, "sales": 2, "customer_service": 2},
    "T2": {"supervisor": 2, "cashier": 5, "warehouse": 3, "security": 2, "sales": 3, "customer_service": 2},
    "T3": {"supervisor": 2, "cashier": 5, "warehouse": 3, "security": 2, "sales": 2, "customer_service": 2},
}
# Roles of members beyond the daily slots (cover rest days): floor roles, not extra supervisors
EXTRA_ROLES = ["cashier", "sales", "customer_service", "warehouse", "cashier", "security", "cashier", "sales"]
NON_SHIFT = ["general_manager", "assistant_manager", "hr_admin", "finance_cash_office", "maintenance",
             "receiving_logistics", "loss_prevention_manager", "training_admin"]

# Daily salary (SD, MXN) — ASSUMPTIONS, override with the client's employees.csv.
# Floor roles at or near the 2026 general minimum wage (315.04).
SALARY_SD = {
    "cashier": 315.04, "sales": 315.04, "customer_service": 330.00, "warehouse": 330.00,
    "security": 350.00, "supervisor": 480.00,
    "general_manager": 1600.00, "assistant_manager": 950.00, "hr_admin": 650.00,
    "finance_cash_office": 650.00, "maintenance": 420.00, "receiving_logistics": 420.00,
    "loss_prevention_manager": 700.00, "training_admin": 500.00,
}

# A2: share of rest-day pairs (first weekday index of the pair) — weekend-skewed.
REST_PAIR_SHARE = {5: 0.25, 6: 0.14, 4: 0.08, 0: 0.11, 1: 0.14, 2: 0.14, 3: 0.14}  # sat-sun, sun-mon, ...


@dataclass
class BaselineParams:
    turn_members: dict[str, int] = field(default_factory=lambda: {"T1": 25, "T2": 24, "T3": 23})
    preopen_start: time = time(7)  # A1
    preopen_people: int = 5
    setup_people: int = 4  # start 08:00
    close_end: time = time(23)
    close_people: int = 5
    rest_pair_share: dict[int, float] = field(default_factory=lambda: dict(REST_PAIR_SHARE))
    scale: float = 1.0  # store size vs the 80-FTE proposal (floor staff, slots and crews scale)


def _allocate(n: int, shares: dict[int, float]) -> list[int]:
    """Largest-remainder allocation of n employees to rest-pair start days."""
    raw = {k: n * v / sum(shares.values()) for k, v in shares.items()}
    alloc = {k: int(v) for k, v in raw.items()}
    for k in sorted(raw, key=lambda k: raw[k] - alloc[k], reverse=True)[: n - sum(alloc.values())]:
        alloc[k] += 1
    return [k for k in sorted(alloc) for _ in range(alloc[k])]


@dataclass
class Baseline:
    employees: pd.DataFrame
    shifts: list[Shift]
    rest_days: dict[str, set[int]]
    notes: list[str]

    def shift_rows(self) -> pd.DataFrame:
        rows = []
        for s in sorted(self.shifts, key=lambda s: (s.employee_id, s.start)):
            rows.append({
                "employee_id": s.employee_id, "date": s.day.isoformat(), "code": s.code,
                "start_time": s.start.strftime("%H:%M"), "end_time": s.end.strftime("%H:%M"),
                "hours": s.hours, "jornada_code": s.jornada_code,
                "on_rest_day": int(s.day.weekday() in self.rest_days.get(s.employee_id, set())),
            })
        return pd.DataFrame(rows)


def build_baseline(store_id: int, week_start: date, salary_zone: str = "general",
                   params: BaselineParams | None = None) -> Baseline:
    assert week_start.weekday() == 0, "week_start must be a Monday"
    p = params or BaselineParams()
    f = p.scale
    turn_roles = {t: {r: max(1, round(k * f)) for r, k in rr.items()} for t, rr in TURN_ROLES.items()}
    turn_members = {t: max(sum(turn_roles[t].values()) + 1, round(n * f)) for t, n in p.turn_members.items()}
    pre_n, setup_n, close_n = (max(1, round(v * f)) for v in (p.preopen_people, p.setup_people, p.close_people))
    emps, shifts, rest, notes = [], [], {}, []
    days = [week_start + timedelta(days=i) for i in range(7)]

    # Non-shift staff: Mon-Fri 09-17, rest Sat+Sun
    admin = ShiftDef("ADM", time(9), time(17), "Admin 09-17")
    for i, role in enumerate(NON_SHIFT, start=1):
        eid = f"S{store_id:02d}-A{i:02d}"
        emps.append((eid, store_id, role, "ADM", SALARY_SD[role], "sat|sun"))
        rest[eid] = {5, 6}
        shifts += [Shift.from_def(eid, d, admin) for d in days[:5]]

    for turn, n in turn_members.items():
        roles = [r for r, k in turn_roles[turn].items() for _ in range(k)]
        roles += [EXTRA_ROLES[i % len(EXTRA_ROLES)] for i in range(n - len(roles))]  # members above slots
        slots = sum(turn_roles[turn].values())
        starts = _allocate(n, p.rest_pair_share)
        # Shuffle rest days (fixed seed) so each role is spread over the week; otherwise one role
        # takes all weekends off and weekends are staffed by a single role.
        starts = [int(x) for x in np.random.default_rng(store_id * 10 + len(turn)).permutation(starts)]
        members = []
        for j in range(n):
            eid = f"S{store_id:02d}-{turn}-{j + 1:02d}"
            role = roles[j]
            rd = {starts[j], (starts[j] + 1) % 7}
            rest[eid] = rd
            members.append(eid)
            emps.append((eid, store_id, role, turn, SALARY_SD[role],
                         "|".join(WEEKDAYS[k] for k in sorted(rd))))
        called_week: set[str] = set()
        for d in days:
            on = [e for e in members if d.weekday() not in rest[e]]
            short = slots - len(on)
            if short > 0:  # A2: call in people on their rest day (lowest id first — same people every week)
                # never the same person twice in a week (keeps one real rest day, Art. 69)
                called = [e for e in members if e not in on and e not in called_week][:short]
                called_week.update(called)
                on += called
                notes.append(f"{d:%a %d %b} {turn}: {len(called)} called in on rest day")
            for k, e in enumerate(on):  # A3: everyone on duty works, even above slots
                start, end = TURNS[turn].start, TURNS[turn].end
                if turn == "T1" and k < pre_n:  # A1 pre-open
                    start = p.preopen_start
                elif turn == "T1" and k < pre_n + setup_n:  # A1 setup
                    start = time(8)
                if turn == "T3" and k < close_n:  # A1 closing
                    end = p.close_end
                shifts.append(Shift.from_def(e, d, ShiftDef(turn, start, end)))

    df = pd.DataFrame(emps, columns=["employee_id", "store_id", "role", "turn", "salary_amount", "rest_days"])
    df.insert(4, "salary_period", "daily")
    df["salary_zone"] = salary_zone
    df["is_floor"] = (df["turn"] != "ADM").astype(int)
    return Baseline(df, shifts, rest, notes)


def floor_fte_needed(requirement: pd.DataFrame, crew: int = 4, days_per_week: int = 5,
                     peak_share: float = 0.95) -> int:
    """Full-time floor staff a store needs so its people can cover each day's peak + opening crew
    (same sizing rule as the synthetic calibration, D30)."""
    peaks = requirement.groupby("date")["required_headcount"].max().sum() + crew * requirement["date"].nunique()
    return int(math.ceil(peaks / (days_per_week * peak_share)))


def daily_salaries(b: Baseline) -> dict[str, Decimal]:
    return {e: Decimal(str(v)) for e, v in zip(b.employees.employee_id, b.employees.salary_amount)}


def main(store_id: int = 20, week_start: date | None = None, year: int = 2030) -> None:
    """python -m jornada40.synth.baseline_roster -> data/synthetic/baseline/"""
    from pathlib import Path

    from jornada40.compliance import evaluate
    from jornada40.cost import coverage_table, price

    from jornada40.synth.build_dataset import PLAN_START

    week_start = week_start or PLAN_START
    root = Path(__file__).resolve().parents[2]
    out = root / "data" / "synthetic" / "baseline"
    out.mkdir(parents=True, exist_ok=True)
    b = build_baseline(store_id, week_start)
    b.employees.to_csv(out / f"employees_store{store_id:02d}.csv", index=False)
    b.shift_rows().to_csv(out / f"current_schedule_store{store_id:02d}.csv", index=False)
    req = pd.read_csv(root / "data" / "synthetic" / "staffing_requirement.csv").query("store_id == @store_id")
    floor = [s for s in b.shifts if s.code != "ADM"]
    rep = evaluate(b.shifts, week_start, 7, year, rest_days=b.rest_days)
    cov = coverage_table(floor, req)
    cost = price(rep, daily_salaries(b), coverage=cov, floor_ids={s.employee_id for s in floor})
    pd.Series({k: str(v) for k, v in cost.as_dict().items()}).to_csv(out / f"cost_summary_store{store_id:02d}.csv",
                                                                     header=["value"])
    cov.assign(gap=cov.have - cov.need).to_csv(out / f"coverage_store{store_id:02d}.csv", index=False)
    for k, v in cost.as_dict().items():
        print(f"{k:26} {v}")


if __name__ == "__main__":
    main()
