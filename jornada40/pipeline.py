"""End-to-end: price the current roster, optimize, price the proposal, compute savings.

Used by the Streamlit app (app.py) and by `python -m jornada40.pipeline` (all demo stores).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd

from jornada40.compliance import Report, evaluate
from jornada40.cost import CostSummary, coverage_table, price
from jornada40.optimizer import OptimizerResult, OptimizerSettings, optimize_store
from jornada40.shifts import Shift

ROOT = Path(__file__).resolve().parents[1]
SYN = ROOT / "data" / "synthetic"


@dataclass
class StoreInput:
    store: dict  # one stores.csv row
    employees: pd.DataFrame  # employee_id, role, daily_salary, is_floor, [rest_days "sat|sun"]
    current_shifts: list[Shift]
    requirement: pd.DataFrame  # date, hour, required_headcount, is_peak
    week_start: date

    @property
    def rest_days(self) -> dict[str, set[int]]:
        wd = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
        if "rest_days" not in self.employees:
            return {}
        return {e: {wd[x] for x in str(r).split("|") if x in wd}
                for e, r in zip(self.employees.employee_id, self.employees.rest_days) if isinstance(r, str)}

    @property
    def salaries(self) -> dict[str, Decimal]:
        return {e: Decimal(str(v)) for e, v in zip(self.employees.employee_id, self.employees.daily_salary)}

    @property
    def floor_ids(self) -> set[str]:
        f = self.employees.get("is_floor", pd.Series(1, index=self.employees.index)).astype(int) == 1
        return set(self.employees.loc[f, "employee_id"])


@dataclass
class Evaluation:
    shifts: list[Shift]
    report: Report
    cost: CostSummary
    coverage: pd.DataFrame


@dataclass
class StoreResult:
    inp: StoreInput
    current: Evaluation
    proposed: Evaluation
    opt: OptimizerResult
    year: int

    @property
    def saving_mxn(self) -> Decimal:
        return self.current.cost.total_cash - self.proposed.cost.total_cash

    @property
    def saving_pct(self) -> float:
        return float(self.saving_mxn / self.current.cost.total_cash * 100)

    def summary(self) -> dict:
        c, p = self.current.cost, self.proposed.cost
        v = lambda r, k: sum(1 for f in r.findings if f.kind == k)  # noqa: E731
        return {
            "store_id": self.inp.store["store_id"], "employees": len(self.inp.employees),
            "current_total": float(c.total_cash), "proposed_total": float(p.total_cash),
            "saving_mxn": float(self.saving_mxn), "saving_pct": round(self.saving_pct, 2),
            "current_premiums": float(c.premiums), "proposed_premiums": float(p.premiums),
            "current_ot_h": c.overtime_hours, "proposed_ot_h": p.overtime_hours,
            "current_restday_calls": c.restdays_worked, "proposed_restday_calls": p.restdays_worked,
            "current_peak_short_h": c.understaff_peak_person_h, "proposed_peak_short_h": p.understaff_peak_person_h,
            "current_overstaff_h": c.overstaff_person_h, "proposed_overstaff_h": p.overstaff_person_h,
            "current_violations": v(self.current.report, "VIOLATION"),
            "proposed_violations": v(self.proposed.report, "VIOLATION"),
            "solver_status": self.opt.status, "solver_s": round(self.opt.wall_time_s, 2),
        }


def _evaluate(inp: StoreInput, shifts: list[Shift], rest_days: dict, year: int) -> Evaluation:
    fids = inp.floor_ids
    floor = [s for s in shifts if s.employee_id in fids]
    rep = evaluate(shifts, inp.week_start, 7, year, rest_days=rest_days)
    cov = coverage_table(floor, inp.requirement, slot_minutes=30)
    cost = price(rep, inp.salaries, coverage=cov, floor_ids=fids)
    return Evaluation(shifts, rep, cost, cov)


def assess_store(inp: StoreInput, year: int = 2030) -> Evaluation:
    """Diagnosis of the current roster: overtime (2x from hour weekly_max+1, 3x beyond the cap),
    premiums, rest-day and feriado work, coverage vs requirement."""
    return _evaluate(inp, inp.current_shifts, inp.rest_days, year)


def run_store(inp: StoreInput, year: int = 2030, settings: OptimizerSettings | None = None,
              current: Evaluation | None = None) -> StoreResult:
    st = settings or OptimizerSettings(year=year)
    st.year = year
    current = current or assess_store(inp, year)
    floor_emp = inp.employees[inp.employees.employee_id.isin(inp.floor_ids)][["employee_id", "daily_salary"]]
    opt = optimize_store(floor_emp, inp.requirement, inp.store, inp.week_start, st)
    fids = inp.floor_ids
    non_floor = [s for s in inp.current_shifts if s.employee_id not in fids]
    proposed_shifts = opt.shifts + non_floor
    # proposed rest days = days each employee does not work (no call-ins by construction)
    proposed = _evaluate(inp, proposed_shifts, {}, year)
    return StoreResult(inp, current, proposed, opt, year)


def demo_input(store_id: int = 20) -> StoreInput:
    """Synthetic demo: bad-planning baseline (client proposal) scaled to the store's size."""
    from jornada40.synth.baseline_roster import BaselineParams, build_baseline
    from jornada40.synth.build_dataset import PLAN_START

    stores = pd.read_csv(SYN / "stores.csv")
    store = stores[stores.store_id == store_id].iloc[0].to_dict()
    req = pd.read_csv(SYN / "staffing_requirement.csv").query("store_id == @store_id")
    # brief: every store has ~80 FTE (8 admin + 72 floor) planned with the same client proposal (D33);
    # each store manager applies it a bit differently (crew sizes, weekend preference) -> varied waste
    import numpy as np
    rng = np.random.default_rng(1000 + store_id)
    share = dict(BaselineParams().rest_pair_share)
    share[5] = float(rng.uniform(0.15, 0.32))  # Sat-Sun rest pairs
    params = BaselineParams(preopen_people=int(rng.integers(3, 7)), setup_people=int(rng.integers(2, 6)),
                            close_people=int(rng.integers(3, 7)), rest_pair_share=share)
    b = build_baseline(store_id, PLAN_START, salary_zone=store["salary_zone"], params=params)
    emp = b.employees.rename(columns={"salary_amount": "daily_salary"})
    if store["salary_zone"] == "zlfn":  # border zone: floor at the ZLFN minimum wage
        emp["daily_salary"] = emp["daily_salary"].clip(lower=440.87)
    return StoreInput(store, emp, b.shifts, req.reset_index(drop=True), PLAN_START)


def shift_rows(shifts: list[Shift], employees: pd.DataFrame | None = None) -> pd.DataFrame:
    rows = [{"employee_id": s.employee_id, "date": s.day.isoformat(), "weekday": s.day.strftime("%a"),
             "start_time": s.start.strftime("%H:%M"), "end_time": s.end.strftime("%H:%M"),
             "hours": s.hours, "jornada_code": s.jornada_code} for s in shifts]
    df = pd.DataFrame(rows).sort_values(["employee_id", "date"]) if rows else pd.DataFrame(rows)
    if employees is not None and len(df):
        df = df.merge(employees[["employee_id", "role"]], on="employee_id", how="left")
    return df


def assessment_row(store_id, inp: StoreInput, ev: Evaluation, year: int) -> dict:
    from jornada40 import config
    c = ev.cost
    return {"tienda": store_id, "empleados": len(inp.employees), "semana": inp.week_start.isoformat(),
            "costo_semanal": float(c.total_cash), "horas_dobles": sum(w.ot_2x_h for w in ev.report.weeks),
            "costo_horas_dobles": float(c.overtime_2x), "horas_triples": sum(w.ot_3x_h for w in ev.report.weeks),
            "costo_horas_triples": float(c.overtime_3x), "descansos_trabajados": c.restdays_worked,
            "costo_descansos": float(c.restday_extra), "costo_feriados": float(c.feriado_extra),
            "prima_dominical": float(c.prima_dominical), "primas_total": float(c.premiums),
            "faltante_pico_h": c.understaff_peak_person_h, "sobredotacion_h": c.overstaff_person_h,
            "subdotacion_h": c.understaff_person_h,
            "violaciones": sum(1 for f in ev.report.findings if f.kind == "VIOLATION"),
            "tope_semanal_h": config.weekly_max_ordinary(year)}


def demo_chain() -> dict:
    """All 50 demo stores as StoreInputs keyed by store id (string)."""
    return {str(sid): demo_input(int(sid)) for sid in pd.read_csv(SYN / "stores.csv").store_id}


def main() -> None:
    """Run all demo stores and write data/synthetic/results/chain_summary.csv."""
    out = SYN / "results"
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for sid in pd.read_csv(SYN / "stores.csv").store_id:
        r = run_store(demo_input(int(sid)))
        rows.append(r.summary())
        print(f"store {sid:>2}: saving {r.saving_pct:5.1f}%  {float(r.saving_mxn):>10,.0f} MXN  "
              f"peak short {r.proposed.cost.understaff_peak_person_h:g} h  {r.opt.status}")
    df = pd.DataFrame(rows)
    df.to_csv(out / "chain_summary.csv", index=False)
    tot_c, tot_p = df.current_total.sum(), df.proposed_total.sum()
    print(f"CHAIN: current {tot_c:,.0f}  proposed {tot_p:,.0f}  saving {tot_c - tot_p:,.0f} MXN "
          f"({(tot_c - tot_p) / tot_c * 100:.1f}%) per week")


if __name__ == "__main__":
    main()
