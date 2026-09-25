"""Build the synthetic demo dataset: 50 stores, last 4 complete weeks of history + next week to plan.

    python -m jornada40.synth.build_dataset
Outputs in data/synthetic/: stores.csv, traffic_history.csv, traffic_plan_week_actual.csv,
traffic_plan_week_forecast.csv, staffing_requirement.csv, peak_summary.csv
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from jornada40.demand import calibrate_base_entries_peak, forecast_traffic, staffing_requirement
from jornada40.synth.traffic import Scenario
from jornada40.synth.traffic import generate_traffic
from jornada40.synth.traffic_profile import TrafficProfile, intraday_curves, profile_from_visits

ROOT = Path(__file__).resolve().parents[2]
N_STORES = 50
# Planning is anchored to "today": the plan week is next Monday-Sunday and the history is the
# last HISTORY_WEEKS complete weeks before the current (incomplete) week.
AS_OF = date(2026, 9, 24)  # Thursday; data available up to yesterday
HISTORY_WEEKS = 4  # 8 gives a steadier weekday-hour average
PLAN_START = AS_OF + timedelta(days=7 - AS_OF.weekday())  # Mon 28 Sep 2026
CURRENT_WEEK_START = PLAN_START - timedelta(weeks=1)  # Mon 21 Sep 2026 (incomplete, not used)
HISTORY_START = CURRENT_WEEK_START - timedelta(weeks=HISTORY_WEEKS)  # Mon 24 Aug 2026 (incl. feriado 16 Sep)
FTE_PER_STORE = 80
NON_SHIFT_FTE = 8  # managers/admin (MD_Proposal_Roster §1) — not floor coverage
WEEKLY_HOURS = 40
DAYS_PER_WEEK = 5  # full-time: 5 x 8 h = 40 h
PEAK_SHARE = 0.95  # the LARGEST store's 72 floor staff can cover 95% of its weekly peaks (D30, D33)
# Brief: 50 stores x ~80 FTE. Store traffic varies (file's relative size ^0.15 -> about +/-15%), but every
# store has the same 80 employees, so smaller stores carry more idle hours (D33).
SCENARIO = Scenario(store_size_compression=0.15)
K = 12  # customers in store per associate
MIN_HEADCOUNT = 4


def main() -> None:
    out = ROOT / "data" / "synthetic"
    out.mkdir(parents=True, exist_ok=True)
    prof_path = ROOT / "data" / "profiles" / "traffic_profile.json"
    if prof_path.exists():
        profile = TrafficProfile.load(prof_path)
    else:
        profile = profile_from_visits(ROOT / "data" / "customer_visit_sample.csv")
        profile.save(prof_path)
    curves = intraday_curves(profile)
    open_h, close_h = profile.open_minute // 60, profile.close_minute // 60
    from jornada40.synth.traffic import store_sizes
    ids = list(range(1, N_STORES + 1))
    max_size = max(store_sizes(profile, ids, SCENARIO).values())
    # calibrate the average store so that the largest one still fits its staff
    base = calibrate_base_entries_peak(profile, curves, FTE_PER_STORE - NON_SHIFT_FTE, DAYS_PER_WEEK, K,
                                       MIN_HEADCOUNT, open_h, close_h, SCENARIO.weekday_factor,
                                       PEAK_SHARE / max_size)

    stores = pd.DataFrame({
        "store_id": ids,
        "store_name": [f"Tienda {i:02d}" for i in ids],
        "salary_zone": ["zlfn" if i > 45 else "general" for i in ids],
        "state": ["Baja California" if i > 45 else "CDMX" for i in ids],
        "opening_time": f"{open_h:02d}:00", "closing_time": f"{close_h:02d}:00",
        "pre_open_minutes": 60, "post_close_minutes": 60,
        "min_headcount_open": MIN_HEADCOUNT, "customers_per_associate_hour": K,
        "peak_threshold_pct": 20,
    })
    stores.to_csv(out / "stores.csv", index=False)

    hist = generate_traffic(profile, ids, HISTORY_START, 7 * HISTORY_WEEKS, base, SCENARIO, seed=1)
    actual = generate_traffic(profile, ids, PLAN_START, 7, base, SCENARIO, seed=2)
    fc = forecast_traffic(hist, PLAN_START, 7)
    req = staffing_requirement(fc, stores)
    hist.to_csv(out / "traffic_history.csv", index=False)
    actual.to_csv(out / "traffic_plan_week_actual.csv", index=False)
    fc.round(2).to_csv(out / "traffic_plan_week_forecast.csv", index=False)
    req.to_csv(out / "staffing_requirement.csv", index=False)

    peaks = (req[req.is_peak == 1].groupby("hour").size() / req.groupby(["store_id", "date"]).ngroups)
    peaks.rename("share_of_store_days_peak").to_csv(out / "peak_summary.csv")
    weekly = req.groupby("store_id").required_headcount.sum()
    print(f"base daily entries (avg store): {base:.0f}")
    print(f"required person-hours/week per store: mean {weekly.mean():.0f}, "
          f"min {weekly.min()}, max {weekly.max()} (floor capacity {(FTE_PER_STORE - NON_SHIFT_FTE) * WEEKLY_HOURS})")
    print("peak hours (share of store-days):", peaks.round(2).to_dict())


if __name__ == "__main__":
    main()
