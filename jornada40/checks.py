"""Pre-solve checks: fast necessary conditions, run before the optimizer (D37).

With one shift per person per day, a store's floor staff limit how many people can be present
at the same time. Demand points that are at least one shift apart cannot be covered by the same person, so each
day needs at least the sum of their needs in different people (longest chain of such points). Summed over the
week this is a lower bound on person-days, compared with what the staff can give:
    floor staff x working days per week (5 or 6).
If the bound computed on peak hours is larger than the capacity, peak understaffing is
unavoidable with that week type; if only the all-hours bound is larger, some off-peak shortfall
is unavoidable. The checks never block the solve; they explain the result in advance.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from jornada40.optimizer import SLOT, week_types


@dataclass
class Check:
    severity: str  # "error" | "warning" | "ok"
    policy: str  # "5" | "6"
    message: str
    need_person_days: int
    capacity_person_days: int


def _slot_needs(requirement, week_start: date, peak_only: bool) -> dict[int, dict[int, int]]:
    out: dict[int, dict[int, int]] = {}
    for d_str, hr, n, pk in requirement[["date", "hour", "required_headcount", "is_peak"]].itertuples(index=False):
        if peak_only and not int(pk):
            continue
        di = (date.fromisoformat(str(d_str)) - week_start).days
        if 0 <= di < 7 and int(n) > 0:
            for k in range(60 // SLOT):
                out.setdefault(di, {})[(int(hr) * 60 + k * SLOT) // SLOT] = int(n)
    return out


def daily_lower_bound(needs: dict[int, int], shift_min: int) -> int:
    """Min distinct people for one day. Slots t1 < t2 can share a person only if t2 - t1 < shift
    length, so any chain of slots pairwise at least one shift apart needs the SUM of their needs
    (different people). Longest-chain dynamic programme over the day's slots."""
    if not needs:
        return 0
    gap = shift_min // SLOT
    items = sorted(needs.items())
    best: list[int] = []
    for i, (t, n) in enumerate(items):
        prev = [best[j] for j, (t2, _) in enumerate(items[:i]) if t - t2 >= gap]
        best.append(n + (max(prev) if prev else 0))
    return max(best)


def presolve_checks(requirement, week_start: date, floor_staff: int, year: int) -> list[Check]:
    out = []
    for policy, days in (("5", 5), ("6", 6)):
        wt = week_types(year, True, False, policy)[0]
        shift = max(wt.diurna_len, wt.mixta_len)
        cap = floor_staff * days
        peak = sum(daily_lower_bound(v, shift) for v in _slot_needs(requirement, week_start, True).values())
        allh = sum(daily_lower_bound(v, shift) for v in _slot_needs(requirement, week_start, False).values())
        label = f"semana de {days} días (turnos de {shift / 60:g} h)"
        if peak > cap:
            out.append(Check("error", policy, f"{label}: las horas pico necesitan al menos {peak} persona-días y "
                                              f"el personal da {cap}. Habrá faltante en pico.", peak, cap))
        elif allh > cap:
            out.append(Check("warning", policy, f"{label}: los picos se cubren, pero cubrir todas las horas "
                                                f"necesita al menos {allh} persona-días (hay {cap}). Quedará "
                                                "faltante fuera de pico.", allh, cap))
        else:
            out.append(Check("ok", policy, f"{label}: sin problemas detectados ({allh} de {cap} persona-días como mínimo).",
                             allh, cap))
    return out
