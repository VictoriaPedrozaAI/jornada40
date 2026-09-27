"""Two flat CSV templates for many stores (D34).

1) programacion_actual.csv (required) — one row per shift worked, employee data repeated:
   tienda, empleado, puesto, salario_diario, en_piso, dias_descanso, zona, fecha, entrada, salida
2) requerimiento.csv (optional) — people needed per store and hour:
   tienda, fecha, hora, personas_requeridas, [es_pico]
   Without it, the tool keeps each store's CURRENT coverage hour by hour as the requirement.

English headers are accepted too (store_id, employee_id, role, daily_salary, is_floor, rest_days,
salary_zone, date, start_time, end_time / required_headcount, is_peak).
"""
from __future__ import annotations

import io
import math
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

import pandas as pd

from jornada40 import config
from jornada40.pipeline import StoreInput
from jornada40.shifts import Shift

SCHEDULE_COLS = ["tienda", "empleado", "puesto", "salario_diario", "en_piso", "dias_descanso", "zona",
                 "fecha", "entrada", "salida"]
REQ_COLS = ["tienda", "fecha", "hora", "personas_requeridas", "es_pico"]
ALIASES = {
    "store_id": "tienda", "store": "tienda", "sucursal": "tienda",
    "employee_id": "empleado", "id_empleado": "empleado",
    "role": "puesto", "daily_salary": "salario_diario", "salario": "salario_diario", "sd": "salario_diario",
    "monthly_salary": "salario_mensual",
    "is_floor": "en_piso", "rest_days": "dias_descanso", "descanso": "dias_descanso",
    "salary_zone": "zona", "date": "fecha", "start_time": "entrada", "hora_entrada": "entrada",
    "end_time": "salida", "hora_salida": "salida", "hour": "hora", "required_headcount": "personas_requeridas",
    "requeridos": "personas_requeridas", "is_peak": "es_pico",
}
WEEKDAYS = {"lun": 0, "mon": 0, "mar": 1, "tue": 1, "mie": 2, "mié": 2, "wed": 2, "jue": 3, "thu": 3,
            "vie": 4, "fri": 4, "sab": 5, "sáb": 5, "sat": 5, "dom": 6, "sun": 6}
WD_EN = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

FORMATO_MSG = ("El archivo de programación no tiene el formato esperado. Descarga la plantilla y súbela con las "
               "columnas: tienda, empleado, salario_diario, fecha, entrada, salida.")
REQ_BAD_MSG = ("No pudimos leer requerimiento.csv (formato o fechas fuera de la semana); se usará tu cobertura "
               "actual. Revisa que las columnas sean tienda, fecha, hora, personas_requeridas y que las fechas "
               "coincidan con tu programación.")


@dataclass
class ChainInput:
    stores: dict[str, StoreInput] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    requirement_source: str = ""  # "uploaded" | "current coverage"


def _read(buf) -> pd.DataFrame:
    raw = buf.getvalue() if hasattr(buf, "getvalue") else open(buf, "rb").read()
    text = raw.decode("utf-8-sig")
    head = text.splitlines()[0] if text else ""
    df = pd.read_csv(io.StringIO(text), sep=";" if head.count(";") > head.count(",") else ",", dtype=str)
    df.columns = [ALIASES.get(c.strip().lower(), c.strip().lower()) for c in df.columns]
    return df.apply(lambda c: c.str.strip() if c.dtype == object else c)


def _time(s: str) -> time:
    s = str(s).strip()
    h, m = (s.split(":") + ["0"])[:2]
    return time(int(h) % 24, int(m[:2]))


def _date(s: str) -> date:
    s = str(s).strip()[:10]
    if "/" in s:
        d, m, y = s.split("/")
        return date(int(y), int(m), int(d))
    return date.fromisoformat(s)


def _num(s) -> float:
    return float(str(s).replace("$", "").replace(",", "").strip())


def load_chain(schedule_f, requirement_f=None, year: int = 2030, pre_post_min: int = 60,
               peak_pct: float = 20, day_hours: dict[int, tuple[str, str] | None] | None = None) -> ChainInput:
    out = ChainInput()
    try:
        df = _read(schedule_f)
    except Exception:  # noqa: BLE001  (empty, not a CSV, bad encoding…)
        out.errors.append(FORMATO_MSG)
        return out
    if df.shape[1] < 2:  # wrong delimiter or single-column junk
        out.errors.append(FORMATO_MSG)
        return out
    if "salario_mensual" in df and "salario_diario" not in df:
        df["salario_diario"] = [str(_num(x) / 30) for x in df["salario_mensual"]]
    missing = [c for c in ("tienda", "empleado", "salario_diario", "fecha", "entrada", "salida") if c not in df]
    if missing:
        out.errors.append(FORMATO_MSG + f" Faltan: {', '.join(missing)}.")
        return out

    min_w = {z: config.min_wage(2026, z)[0] for z in config.SALARY_ZONES}
    bad_rows = 0
    shifts_by_store: dict[str, list[Shift]] = {}
    emp_rows: dict[tuple[str, str], dict] = {}
    for i, r in enumerate(df.to_dict("records"), start=2):
        try:
            st, e = str(r["tienda"]), str(r["empleado"])
            d = _date(r["fecha"])
            s, en = datetime.combine(d, _time(r["entrada"])), datetime.combine(d, _time(r["salida"]))
            if en <= s:
                en += timedelta(days=1)
            sd = _num(r["salario_diario"])
        except Exception:  # noqa: BLE001
            bad_rows += 1
            continue
        shifts_by_store.setdefault(st, []).append(Shift(e, d, "CUR", s, en))
        if (st, e) not in emp_rows:
            zone = str(r.get("zona") or "general").lower()
            zone = "zlfn" if zone.startswith(("zlfn", "front")) else "general"
            floor = str(r.get("en_piso", "1")).strip().lower() not in ("0", "no", "false", "n")
            emp_rows[(st, e)] = {"employee_id": e, "role": r.get("puesto") or "", "daily_salary": sd,
                                 "is_floor": int(floor), "zone": zone,
                                 "rest_days": "|".join(WD_EN[WEEKDAYS[x[:3]]] for x in
                                                       str(r.get("dias_descanso") or "").lower().replace(",", "|")
                                                       .split("|") if x[:3] in WEEKDAYS) or None}
    if bad_rows:
        out.warnings.append(f"{bad_rows} filas de programación ignoradas (fecha, hora o salario ilegibles).")
    if not shifts_by_store:
        out.errors.append(FORMATO_MSG)
        return out

    below = [(st, e) for (st, e), v in emp_rows.items() if v["daily_salary"] < float(min_w[v["zone"]]) - 0.005]
    if below:
        out.errors.append(f"{len(below)} empleados con salario diario debajo del mínimo 2026 "
                          f"(p. ej. tienda {below[0][0]}, {below[0][1]}). Corrige el archivo: no ajustamos "
                          "salarios ilegales automáticamente.")
        return out

    req_all = None
    if requirement_f is not None:
        try:
            req_all = _read(requirement_f)
            need = [c for c in ("tienda", "hora", "personas_requeridas") if c not in req_all]
            assert not need and ({"fecha"} & set(req_all) or {"dia"} & set(req_all))
            out.requirement_source = "uploaded"
        except Exception:  # noqa: BLE001  (bad format -> fall back to current coverage)
            req_all = None
            out.warnings.append(REQ_BAD_MSG)
    if req_all is None:
        out.requirement_source = "current coverage"
        if requirement_f is None:
            out.warnings.append("Sin archivo de requerimiento: se usa la cobertura actual de cada tienda (personas "
                                "en piso por hora) como requerimiento. El ahorro sale de las horas extra, primas y "
                                "descansos trabajados; no mide sobre- ni subdotación reales.")

    for st, shifts in sorted(shifts_by_store.items(), key=lambda kv: (len(kv[0]), kv[0])):
        first = min(s.day for s in shifts)
        wk = first - timedelta(days=first.weekday())
        wshifts = [s for s in shifts if 0 <= (s.day - wk).days < 7]
        if len(wshifts) < len(shifts):
            out.warnings.append(f"Tienda {st}: solo se evalúa la semana del {wk:%d/%m/%Y}.")
        emp = pd.DataFrame([v for (s_, _), v in emp_rows.items() if s_ == st])
        floor_ids = set(emp.loc[emp.is_floor == 1, "employee_id"])
        floor_shifts = [s for s in wshifts if s.employee_id in floor_ids]
        if not floor_shifts:
            out.warnings.append(f"Tienda {st}: sin personal en piso; se omite.")
            continue

        req = None
        if req_all is not None:
            rq = req_all[req_all["tienda"].astype(str) == st].copy()
            try:
                if "fecha" not in rq:
                    rq["fecha"] = [(wk + timedelta(days=WEEKDAYS[str(x)[:3].lower()])).isoformat() for x in rq["dia"]]
                rq = pd.DataFrame({"date": [_date(x).isoformat() for x in rq["fecha"]],
                                   "hour": rq["hora"].astype(float).astype(int),
                                   "required_headcount": rq["personas_requeridas"].astype(float).round().astype(int),
                                   "is_peak": rq.get("es_pico", pd.Series([None] * len(rq), index=rq.index))})
                rq = rq[(pd.to_datetime(rq["date"]).dt.date >= wk)
                        & (pd.to_datetime(rq["date"]).dt.date < wk + timedelta(days=7))]
                req = rq.groupby(["date", "hour"], as_index=False).agg(
                    required_headcount=("required_headcount", "sum"), is_peak=("is_peak", "first")) if len(rq) else None
            except Exception:  # noqa: BLE001  (unparseable rows -> fall back below)
                req = None
        if req is None or req.empty:
            if req_all is not None:
                out.warnings.append(f"Tienda {st}: el requerimiento no coincide con la semana de la programación "
                                    "(fechas fuera de rango); se usa la cobertura actual.")
                out.requirement_source = "current coverage"
            req = _coverage_as_requirement(floor_shifts, wk)
        if "is_peak" not in req or req["is_peak"].isna().any():
            req = _mark_peaks(req, peak_pct)
        req["is_peak"] = req["is_peak"].astype(float).fillna(0).astype(int)
        req = req[(pd.to_datetime(req["date"]).dt.date >= wk) & (pd.to_datetime(req["date"]).dt.date < wk + timedelta(days=7))]

        # store window from the requirement (open hours) or, if absent, from the current shifts
        first_h, last_h = int(req.loc[req.required_headcount > 0, "hour"].min()), int(req["hour"].max()) + 1
        if day_hours:  # v3: one opening schedule for the whole chain; None = store closed that day
            open_ = [v for v in day_hours.values() if v]
            closed_dates = {(wk + timedelta(days=i)).isoformat() for i in range(7)
                            if day_hours.get((wk + timedelta(days=i)).weekday()) is None}
            req = req[~req["date"].isin(closed_dates)]
            on_closed = sum(1 for s_ in wshifts if s_.day.isoformat() in closed_dates)
            if on_closed:
                out.warnings.append(f"Tienda {st}: {on_closed} turnos actuales caen en días marcados como cerrados; "
                                    "se cuentan en el diagnóstico, pero la nueva programación no asigna esos días.")
            first_h, last_h = int(min(o for o, _ in open_)[:2]) - 1, int(max(c for _, c in open_)[:2]) + 1
        store = {"store_id": st, "opening_time": f"{first_h + 1:02d}:00", "closing_time": f"{last_h - 1:02d}:00",
                 "pre_open_minutes": pre_post_min, "post_close_minutes": pre_post_min,
                 "salary_zone": emp["zone"].mode().iat[0]}
        emp = emp.drop(columns="zone")
        if day_hours:
            store["day_hours"] = dict(day_hours)
        out.stores[st] = StoreInput(store, emp, wshifts, req.reset_index(drop=True), wk)
    if not out.stores and not out.errors:
        out.errors.append("No se encontró ninguna tienda utilizable.")
    return out


def _coverage_as_requirement(shifts: list[Shift], wk: date) -> pd.DataFrame:
    rows = []
    for d in range(7):
        day = wk + timedelta(days=d)
        for h in range(24):
            t = datetime.combine(day, time(h))
            n = sum(1 for s in shifts if s.start <= t < s.end)
            n2 = sum(1 for s in shifts if s.start <= t + timedelta(minutes=30) < s.end)
            if n or n2:
                rows.append((day.isoformat(), h, int(math.ceil((n + n2) / 2)), None))
    return pd.DataFrame(rows, columns=["date", "hour", "required_headcount", "is_peak"])


def _mark_peaks(req: pd.DataFrame, pct: float) -> pd.DataFrame:
    req = req.copy()
    req["is_peak"] = 0
    for _, g in req.groupby("date"):
        vals = sorted(g["required_headcount"], reverse=True)
        cut = vals[max(1, math.ceil(len(vals) * pct / 100)) - 1]
        req.loc[g.index, "is_peak"] = (g["required_headcount"] >= max(cut, 1)).astype(int)
    return req


def template_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Empty-ish templates with 3 example rows each (for download)."""
    sch = pd.DataFrame([
        ["T001", "E0001", "cajero", 315.04, 1, "mar|mie", "general", "2026-09-28", "09:00", "17:00"],
        ["T001", "E0002", "piso", 330.00, 1, "sab|dom", "general", "2026-09-28", "14:00", "22:00"],
        ["T001", "A0001", "gerente", 1600.00, 0, "sab|dom", "general", "2026-09-28", "09:00", "17:00"],
    ], columns=SCHEDULE_COLS)
    req = pd.DataFrame([["T001", "2026-09-28", 9, 18, ""], ["T001", "2026-09-28", 13, 33, 1],
                        ["T001", "2026-09-28", 18, 39, 1]], columns=REQ_COLS)
    return sch, req


def to_flat(inp: StoreInput) -> pd.DataFrame:
    """StoreInput -> rows in the programacion_actual.csv format (used to export the demo)."""
    emp = inp.employees.set_index("employee_id")
    wd_es = {"mon": "lun", "tue": "mar", "wed": "mie", "thu": "jue", "fri": "vie", "sat": "sab", "sun": "dom"}
    rows = []
    for s in sorted(inp.current_shifts, key=lambda s: (s.employee_id, s.start)):
        e = emp.loc[s.employee_id]
        rd = e.get("rest_days")
        rows.append([inp.store["store_id"], s.employee_id, e.get("role", ""), float(e["daily_salary"]),
                     int(e.get("is_floor", 1)),
                     "|".join(wd_es[x] for x in str(rd).split("|") if x in wd_es) if isinstance(rd, str) else "",
                     inp.store.get("salary_zone", "general"), s.day.isoformat(),
                     s.start.strftime("%H:%M"), s.end.strftime("%H:%M")])
    return pd.DataFrame(rows, columns=SCHEDULE_COLS)
