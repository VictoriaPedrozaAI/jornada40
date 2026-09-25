"""Traffic -> forecast -> staffing requirement -> peak hours.

Requirement per open hour = max(min_headcount_open, ceil(driver / customers_per_associate_hour)),
driver = `occupancy` (customers inside) when present, else `customers` (entries).
Occupancy is preferred: staff serve people who are in the store, and with ~1 h dwell the
in-store peak lags the entry peak by about an hour.
Pre-open / post-close hours require `min_headcount_open` (opening and closing crew).
Peak = top `peak_threshold_pct`% of open hours per store-day by requirement (ties included).
"""
from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import pandas as pd

from jornada40 import config


def forecast_traffic(history: pd.DataFrame, plan_start: date, n_days: int = 7,
                     exclude_feriados: bool = True) -> pd.DataFrame:
    """Average of the same weekday-hour over the history, per store."""
    h = history.copy()
    h["date"] = pd.to_datetime(h["date"])
    if exclude_feriados:
        h = h[~h["date"].dt.strftime("%Y-%m-%d").isin(config.FERIADOS)]
    h["wd"] = h["date"].dt.dayofweek
    cols = [c for c in ("customers", "tickets", "sales_mxn", "occupancy") if c in h]
    avg = h.groupby(["store_id", "wd", "hour"])[cols].mean().reset_index()
    out = []
    for i in range(n_days):
        d = plan_start + timedelta(days=i)
        day = avg[avg["wd"] == d.weekday()].drop(columns="wd").assign(date=d.isoformat())
        out.append(day)
    return pd.concat(out)[["store_id", "date", "hour", *cols]].reset_index(drop=True)


def staffing_requirement(traffic: pd.DataFrame, stores: pd.DataFrame) -> pd.DataFrame:
    """stores columns: store_id, opening_time, closing_time, pre_open_minutes, post_close_minutes,
    min_headcount_open, customers_per_associate_hour, peak_threshold_pct."""
    driver = "occupancy" if "occupancy" in traffic else "customers"
    st = stores.set_index("store_id")
    rows = []
    for (sid, d), g in traffic.groupby(["store_id", "date"], sort=True):
        s = st.loc[sid]
        k = float(s["customers_per_associate_hour"])
        floor = int(s.get("min_headcount_open", 2))
        open_h = int(str(s["opening_time"])[:2])
        close_h = int(str(s["closing_time"])[:2])  # store closes at close_h:00
        pre = math.ceil(int(s.get("pre_open_minutes", 60)) / 60)
        post = math.ceil(int(s.get("post_close_minutes", 60)) / 60)
        by_hour = dict(zip(g["hour"], g[driver]))
        day = []
        for hr in range(open_h - pre, close_h + post):
            if open_h <= hr < close_h:
                req = max(floor, math.ceil(float(by_hour.get(hr, 0)) / k))
                day.append([sid, d, hr, "", req, 0, True])
            else:
                day.append([sid, d, hr, "", floor, 0, False])
        open_reqs = sorted((r[4] for r in day if r[6]), reverse=True)
        n_peak = max(1, math.ceil(len(open_reqs) * float(s.get("peak_threshold_pct", 20)) / 100))
        cutoff = open_reqs[n_peak - 1]
        for r in day:
            r[5] = int(r[6] and r[4] >= cutoff)
        rows += [r[:6] for r in day]
    return pd.DataFrame(rows, columns=["store_id", "date", "hour", "role", "required_headcount", "is_peak"])


def calibrate_base_entries(profile, curves: pd.DataFrame, target_weekly_person_hours: float,
                           customers_per_associate_hour: float, min_headcount: int,
                           open_h: int, close_h: int, pre_post_hours: int = 2) -> float:
    """Median-store daily entries such that expected weekly required person-hours hits the target
    (weekday factors average to 1, so a 'mean day' x 7 is used). Bisection on the expected curve."""
    mean_dwell_h = float(np.mean(profile.dwell_minutes)) / 60
    occ_share = curves["occupancy"]
    hours = [h for h in range(open_h, close_h) if h in occ_share.index]

    def weekly_hours(base: float) -> float:
        occ_hours = base * mean_dwell_h  # person-hours of customers in store per day
        day = sum(max(min_headcount, math.ceil(occ_hours * occ_share[h] / customers_per_associate_hour))
                  for h in hours)
        return 7 * (day + pre_post_hours * min_headcount)

    lo, hi = 1.0, 1e6
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if weekly_hours(mid) < target_weekly_person_hours else (lo, mid)
    return hi


def calibrate_base_entries_peak(profile, curves: pd.DataFrame, floor_fte: int, days_per_week: int,
                                customers_per_associate_hour: float, min_headcount: int,
                                open_h: int, close_h: int, weekday_factors: tuple[float, ...],
                                peak_share: float = 0.95) -> float:
    """Median-store daily entries such that the store's full-time staff can cover every daily peak:
    sum over the week of the daily peak headcount = peak_share x floor_fte x days_per_week.

    Why peaks and not hours: with one shift per person per day, the binding constraint is the peak
    of each day, not total hours. A store sized on hours alone cannot cover its peaks without
    overtime (found when the optimizer was first run, see HANDOVER D30).
    """
    mean_dwell_h = float(np.mean(profile.dwell_minutes)) / 60
    occ = curves["occupancy"]
    hours = [h for h in range(open_h, close_h) if h in occ.index]
    wf = np.array(weekday_factors) / np.mean(weekday_factors)

    def peak_days(base: float) -> float:
        # + opening crew: an 8 h shift starting before opening ends before the evening peak
        return sum(max(max(min_headcount, math.ceil(base * f * mean_dwell_h * occ[h] / customers_per_associate_hour))
                       for h in hours) + min_headcount for f in wf)

    target = peak_share * floor_fte * days_per_week
    lo, hi = 1.0, 1e6
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if peak_days(mid) < target else (lo, mid)
    return lo
