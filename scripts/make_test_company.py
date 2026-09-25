"""Simulated test company for the Jornada40 app — independent from the demo generator.

"Súper Palma" — 24 supermarkets (4 in Tijuana, northern border zone), ~65-95 employees each,
store open 08:00-21:00, regular week Mon 23 - Sun 29 Nov 2026.
They are mid-transition to the 40 h week: floor staff already moved to 6 days x 7 h = 42 h
(1 rest day) with morning / afternoon / closing shifts, but some shifts are still stretched
to cover gaps, a few people are called in on their rest day, and 2 night security guards
(22:00-05:00, 6 x 7 h nocturna) per store are not floor staff. Evaluated under the 40 h rules.

Writes, in the exact app template format (see data/templates_app/):
  data/test_company/programacion_actual.csv   (required file)
  data/test_company/requerimiento.csv         (optional file)

    python scripts/make_test_company.py
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "test_company"
WEEK = date(2026, 11, 23)  # Monday; regular week (no feriado, no quincena payday)
DAYS = [WEEK + timedelta(days=i) for i in range(7)]
WD = ["lun", "mar", "mie", "jue", "vie", "sab", "dom"]
N_STORES, BORDER = 24, {21, 22, 23, 24}
rng = np.random.default_rng(2026_11_16)

# floor shifts (their current habit): 7 h x 6 days = 42 h
SHIFTS = {"MAN": ("07:00", "14:00"), "TAR": ("14:00", "21:00"), "CIE": ("15:00", "22:00")}
SHIFT_MIX = {"MAN": 0.45, "TAR": 0.30, "CIE": 0.25}
ROLES = {"cajero": (0.38, 330, 365), "piso": (0.30, 330, 370), "almacen": (0.14, 350, 390),
         "seguridad": (0.08, 380, 420), "supervisor": (0.10, 500, 560)}
ADMIN = [("gerente", 1450, 1650), ("subgerente", 850, 980), ("administrativo", 520, 600),
         ("administrativo", 520, 600)]
NIGHT = [("vigilante_nocturno", 400, 440)] * 2
REST_P = np.array([0.10, 0.22, 0.24, 0.20, 0.12, 0.06, 0.06])  # rest mostly Tue-Thu; few weekends
ZLFN_MIN = 440.87


def sd(lo: float, hi: float, border: bool) -> float:
    v = rng.uniform(lo, hi)
    if border:
        v = max(v * 1.35, ZLFN_MIN + rng.uniform(5, 60))
    return round(v, 2)


def hhmm(t: str, add_min: int = 0) -> str:
    m = int(t[:2]) * 60 + int(t[3:]) + add_min
    return f"{(m // 60) % 24:02d}:{m % 60:02d}"


def store_rows(i: int) -> tuple[list, list]:
    store, border = f"SP-{i:02d}", i in BORDER
    zone = "zlfn" if border else "general"
    n_floor = int(rng.integers(58, 90))
    rows, floor = [], []
    # admin: Mon-Fri 09-17
    for k, (role, lo, hi) in enumerate(ADMIN, start=1):
        e, s = f"{store}-A{k:02d}", sd(lo, hi, border)
        for d in DAYS[:5]:
            rows.append([store, e, role, s, 0, "sab|dom", zone, d.isoformat(), "09:00", "17:00"])
    # night guards: 6 nights x 7 h (nocturna max) = 42 h, not floor staff
    for k, (role, lo, hi) in enumerate(NIGHT, start=1):
        e, rest = f"{store}-N{k:02d}", k  # rest Tue / Wed
        s = sd(lo, hi, border)
        for j, d in enumerate(DAYS):
            if j != rest:
                rows.append([store, e, role, s, 0, WD[rest], zone, d.isoformat(), "22:00", "05:00"])
    # floor staff: 6 days x 7 h = 42 h, fixed shift group, one rest day
    names = list(ROLES)
    p_role = np.array([ROLES[r][0] for r in names])
    for k in range(1, n_floor + 1):
        role = names[rng.choice(len(names), p=p_role / p_role.sum())]
        _, lo, hi = ROLES[role]
        grp = rng.choice(list(SHIFT_MIX), p=list(SHIFT_MIX.values()))
        rest = int(rng.choice(7, p=REST_P))
        floor.append((f"{store}-E{k:03d}", role, sd(lo, hi, border), grp, rest))
    called_in = set(rng.choice(len(floor), size=int(rng.integers(2, 6)), replace=False))
    for idx, (e, role, s, grp, rest) in enumerate(floor):
        start, end = SHIFTS[grp]
        for j, d in enumerate(DAYS):
            works = j != rest or (idx in called_in and j >= 5)  # called in on a weekend rest day
            if not works:
                continue
            ext = 60 if rng.random() < 0.08 else 0  # stayed 1 h longer to cover a gap
            rows.append([store, e, role, s, 1, WD[rest], zone, d.isoformat(), start, hhmm(end, ext)])

    # requirement: people needed on the floor per hour (07 opening crew ... 21 closing crew)
    size = n_floor / 74
    shape = {8: 0.35, 9: 0.45, 10: 0.55, 11: 0.65, 12: 0.85, 13: 1.00, 14: 0.95, 15: 0.62, 16: 0.58,
             17: 0.72, 18: 0.92, 19: 0.95, 20: 0.60}
    day_f = [0.92, 0.88, 0.90, 0.93, 1.05, 1.18, 1.10]  # Mon ... Sun
    req = []
    for j, d in enumerate(DAYS):
        peak = 40 * size * day_f[j] * rng.uniform(0.97, 1.03)
        for h in range(7, 22):
            if h in (7, 21):
                n = max(3, round(4 * size))
            else:
                n = max(4, math.ceil(peak * shape[h] * rng.uniform(0.95, 1.05)))
            req.append([store, d.isoformat(), h, n, ""])
    return rows, req


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    sched, req = [], []
    for i in range(1, N_STORES + 1):
        a, b = store_rows(i)
        sched += a
        req += b
    cols = ["tienda", "empleado", "puesto", "salario_diario", "en_piso", "dias_descanso", "zona", "fecha",
            "entrada", "salida"]
    s = pd.DataFrame(sched, columns=cols)
    r = pd.DataFrame(req, columns=["tienda", "fecha", "hora", "personas_requeridas", "es_pico"])
    s.to_csv(OUT / "programacion_actual.csv", index=False)
    r.to_csv(OUT / "requerimiento.csv", index=False)
    print(f"{len(s):,} shifts · {s.empleado.nunique():,} employees · {s.tienda.nunique()} stores · "
          f"{len(r):,} requirement rows")


if __name__ == "__main__":
    main()
