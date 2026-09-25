"""Learn an intraday traffic profile from visit-level data (visit_id, customer_id, store_id,
date, entry_timestamp, exit_timestamp).

What we take from the data: opening window, entry share per hour, dwell-time distribution,
and relative store size. What we do NOT take: absolute volume, weekday/seasonal effects
(the sample is itself synthetic and flat on those — see docs/traffic_data_assessment.md).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass
class TrafficProfile:
    open_minute: int  # first entry, minutes from midnight
    last_entry_minute: int
    close_minute: int  # last exit
    entry_share: dict[int, float]  # hour -> share of daily entries (sums to 1)
    dwell_minutes: list[int]  # empirical dwell sample (for resampling)
    store_size: dict[int, float]  # store_id -> visits / median store
    source_rows: int

    def save(self, path: str | Path) -> None:
        d = asdict(self)
        d["dwell_minutes"] = sorted(d["dwell_minutes"])
        Path(path).write_text(json.dumps(d, indent=1))

    @classmethod
    def load(cls, path: str | Path) -> "TrafficProfile":
        d = json.loads(Path(path).read_text())
        d["entry_share"] = {int(k): v for k, v in d["entry_share"].items()}
        d["store_size"] = {int(k): v for k, v in d["store_size"].items()}
        return cls(**d)


def _to_min(s: pd.Series) -> np.ndarray:
    hm = s.str.split(":", expand=True).astype(int)
    return (hm[0] * 60 + hm[1]).to_numpy()


def profile_from_visits(path: str | Path, dwell_sample: int = 2000, seed: int = 0) -> TrafficProfile:
    df = pd.read_csv(path)
    entry, exit_ = _to_min(df["entry_timestamp"]), _to_min(df["exit_timestamp"])
    dwell = exit_ - entry
    valid = dwell > 0
    entry, exit_, dwell = entry[valid], exit_[valid], dwell[valid]
    last_entry = int(entry.max())
    # visits entering in the last hour are truncated by closing -> use earlier ones for dwell
    unbiased = dwell[entry < last_entry - 120]
    rng = np.random.default_rng(seed)
    sample = rng.choice(unbiased, size=min(dwell_sample, len(unbiased)), replace=False)

    hours = entry // 60
    counts = pd.Series(hours).value_counts().sort_index()
    size = df[valid].groupby("store_id").size()
    return TrafficProfile(
        open_minute=int(entry.min()),
        last_entry_minute=last_entry,
        close_minute=int(exit_.max()) + 1,
        entry_share={int(h): float(c / counts.sum()) for h, c in counts.items()},
        dwell_minutes=[int(x) for x in sample],
        store_size={int(k): float(v / size.median()) for k, v in size.items()},
        source_rows=int(valid.sum()),
    )


def intraday_curves(profile: TrafficProfile, n: int = 200_000, seed: int = 0) -> pd.DataFrame:
    """Expected share per hour of entries, exits and in-store occupancy (person-minutes)."""
    rng = np.random.default_rng(seed)
    hours = np.array(list(profile.entry_share))
    probs = np.array(list(profile.entry_share.values()))
    h = rng.choice(hours, size=n, p=probs / probs.sum())
    ent = h * 60 + rng.integers(0, 60, size=n)
    ent = np.minimum(ent, profile.last_entry_minute)
    ex = np.minimum(ent + rng.choice(profile.dwell_minutes, size=n), profile.close_minute - 1)
    occ = np.zeros(24 * 60)
    np.add.at(occ, ent, 1)
    np.add.at(occ, ex, -1)
    occ = np.cumsum(occ).reshape(24, 60).sum(1)
    out = pd.DataFrame({
        "entries": np.bincount(ent // 60, minlength=24) / n,
        "exits": np.bincount(ex // 60, minlength=24) / n,
        "occupancy": occ / occ.sum(),
    })
    out.index.name = "hour"
    first, last = profile.open_minute // 60, (profile.close_minute - 1) // 60
    return out.loc[first:last]
