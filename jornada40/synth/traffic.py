"""Generate synthetic hourly store traffic in the `traffic.csv` format.

Intraday shape, opening window, dwell time and relative store size come from the learned
TrafficProfile. Volume and calendar effects are ASSUMPTIONS (documented in
docs/traffic_data_assessment.md) because the sample data is flat on them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

from jornada40 import config
from jornada40.synth.traffic_profile import TrafficProfile


@dataclass
class Scenario:
    # Mon..Sun, normalized to mean 1 at runtime. Mexican retail: weekend-heavy.
    weekday_factor: tuple[float, ...] = (0.90, 0.88, 0.92, 0.95, 1.08, 1.20, 1.12)
    # Quincena: paydays on the 15th and last day of month -> spending bump that day and next 2.
    payday_boost: float = 0.08
    month_factor: dict[int, float] = field(default_factory=lambda: {1: 0.92, 12: 1.20})
    feriado_factor: float = 1.05
    day_noise_sigma: float = 0.05  # lognormal day-level noise
    conversion: float = 0.75  # tickets / customers
    avg_ticket_mxn: float = 320.0
    ticket_sigma: float = 0.6  # lognormal spread of ticket value
    store_size_compression: float = 0.5  # size**c: keeps stores near the ~80 FTE brief


def _payday_window(d: date) -> bool:
    last = (date(d.year + (d.month == 12), d.month % 12 + 1, 1) - timedelta(days=1)).day
    return d.day in (15, 16, 17, 1, 2) or d.day == last


def day_factor(d: date, sc: Scenario) -> float:
    wf = np.array(sc.weekday_factor)
    f = wf[d.weekday()] / wf.mean()
    f *= sc.month_factor.get(d.month, 1.0)
    if _payday_window(d):
        f *= 1 + sc.payday_boost
    if d.isoformat() in config.FERIADOS:
        f *= sc.feriado_factor
    return float(f)


def store_sizes(profile: TrafficProfile, store_ids: list[int], sc: Scenario) -> dict[int, float]:
    raw = {s: profile.store_size.get(s, 1.0) ** sc.store_size_compression for s in store_ids}
    mean = np.mean(list(raw.values()))
    return {s: v / mean for s, v in raw.items()}  # average store = 1.0


def generate_traffic(
    profile: TrafficProfile,
    store_ids: list[int],
    start: date,
    n_days: int,
    base_daily_entries: float,
    scenario: Scenario | None = None,
    seed: int = 42,
) -> pd.DataFrame:
    """Rows: store_id, date, hour, customers, tickets, sales_mxn, occupancy.

    customers = entries in the hour; tickets = checkouts (exits x conversion);
    occupancy = average customers inside during the hour.
    """
    sc = scenario or Scenario()
    rng = np.random.default_rng(seed)
    sizes = store_sizes(profile, store_ids, sc)
    hours = np.array(list(profile.entry_share))
    probs = np.array(list(profile.entry_share.values()))
    probs = probs / probs.sum()
    dwell = np.array(profile.dwell_minutes)
    first_h, last_h = profile.open_minute // 60, (profile.close_minute - 1) // 60
    open_hours = np.arange(first_h, last_h + 1)
    rows = []
    for s in store_ids:
        for i in range(n_days):
            d = start + timedelta(days=i)
            lam = base_daily_entries * sizes[s] * day_factor(d, sc) * rng.lognormal(0, sc.day_noise_sigma)
            n = rng.poisson(lam)
            h = rng.choice(hours, size=n, p=probs)
            ent = np.minimum(h * 60 + rng.integers(0, 60, size=n), profile.last_entry_minute)
            ex = np.minimum(ent + rng.choice(dwell, size=n), profile.close_minute - 1)
            occ = np.zeros(24 * 60 + 1)
            np.add.at(occ, ent, 1)
            np.add.at(occ, ex, -1)
            occ_h = np.cumsum(occ)[:1440].reshape(24, 60).mean(1)
            cust = np.bincount(ent // 60, minlength=24)
            exits = np.bincount(ex // 60, minlength=24)
            tickets = rng.binomial(exits, sc.conversion)
            mu = np.log(sc.avg_ticket_mxn) - sc.ticket_sigma**2 / 2
            for hr in open_hours:
                t = int(tickets[hr])
                sales = float(rng.lognormal(mu, sc.ticket_sigma, size=t).sum()) if t else 0.0
                rows.append((s, d.isoformat(), int(hr), int(cust[hr]), t, round(sales, 2),
                             round(float(occ_h[hr]), 2)))
    return pd.DataFrame(rows, columns=["store_id", "date", "hour", "customers", "tickets",
                                       "sales_mxn", "occupancy"])
