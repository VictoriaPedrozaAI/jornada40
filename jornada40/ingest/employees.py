"""Load the client's employee roster (CSV) into validated Employee records.

Salary policy (see docs/employee_csv_schema.md):
- Salary given  -> normalized to salario diario (SD); must be >= minimum wage for its zone
  (pro-rated for part-time contracts). Below minimum is an ERROR, never silently fixed.
- Salary missing -> SD imputed as the minimum wage for the zone, flagged as WARNING and
  marked salary_source="imputed_min_wage" so cost reports can show how much was imputed.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

from jornada40 import config

# Canonical column -> accepted header aliases (compared after normalization).
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "employee_id": ("employee_id", "id_empleado", "numero_empleado", "no_empleado"),
    "store_id": ("store_id", "tienda", "id_tienda", "sucursal"),
    "salary_amount": ("salary_amount", "salario", "sueldo", "salary"),
    "salary_period": ("salary_period", "periodo_salario", "periodo"),
    "daily_salary": ("daily_salary", "salario_diario", "sd"),
    "salary_zone": ("salary_zone", "zona", "zona_salarial"),
    "contract_weekly_hours": ("contract_weekly_hours", "horas_contrato", "horas_semanales"),
    "birth_date": ("birth_date", "fecha_nacimiento"),
    "hire_date": ("hire_date", "fecha_ingreso"),
    "role": ("role", "puesto"),
    "rest_day_preference": ("rest_day_preference", "dia_descanso"),
}
REQUIRED = ("employee_id", "store_id")

PERIOD_ALIASES = {
    "daily": "daily", "diario": "daily",
    "weekly": "weekly", "semanal": "weekly",
    "biweekly": "biweekly", "quincenal": "biweekly",
    "monthly": "monthly", "mensual": "monthly",
    "hourly": "hourly", "por_hora": "hourly", "hora": "hourly",
}
ZONE_ALIASES = {"general": "general", "zlfn": "zlfn", "frontera": "zlfn", "frontera_norte": "zlfn"}
WEEKDAYS = {
    "mon": 0, "lun": 0, "tue": 1, "mar": 1, "wed": 2, "mie": 2, "mié": 2,
    "thu": 3, "jue": 3, "fri": 4, "vie": 4, "sat": 5, "sab": 5, "sáb": 5, "sun": 6, "dom": 6,
}
CENT = Decimal("0.01")


@dataclass(frozen=True)
class Issue:
    severity: str  # "ERROR" (row rejected) | "WARNING" (row accepted)
    row: int  # 1-based data row; 0 = file-level
    field: str
    message: str


@dataclass(frozen=True)
class Employee:
    employee_id: str
    store_id: str
    daily_salary: Decimal  # SD, MXN
    salary_source: str  # "csv" | "imputed_min_wage"
    salary_zone: str
    contract_weekly_hours: Decimal
    birth_date: date | None = None
    hire_date: date | None = None
    role: str | None = None
    rest_day_preference: int | None = None  # 0=Mon .. 6=Sun

    def is_minor(self, on: date) -> bool:
        if self.birth_date is None:
            return False
        b = self.birth_date
        age = on.year - b.year - ((on.month, on.day) < (b.month, b.day))
        return age < config.MINOR_AGE


@dataclass
class LoadResult:
    employees: list[Employee] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "ERROR"]

    @property
    def imputed_count(self) -> int:
        return sum(e.salary_source == "imputed_min_wage" for e in self.employees)


def _norm_header(h: str) -> str:
    return re.sub(r"[^a-z0-9_áéíóúñ]", "", h.strip().lower().replace(" ", "_"))


def _parse_money(raw: str) -> Decimal:
    s = raw.strip().replace("$", "").replace("MXN", "").replace(" ", "")
    if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", s):  # 1.234,56 (European style)
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d+,\d{1,2}", s):  # 315,04 (decimal comma, no thousands)
        s = s.replace(",", ".")
    else:  # 1,234.56 or 315.04
        s = s.replace(",", "")
    return Decimal(s)


def _parse_date(raw: str) -> date:
    raw = raw.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return date.fromisoformat(raw)
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", raw)  # dd/mm/yyyy (Mexican convention)
    if m:
        return date(int(m[3]), int(m[2]), int(m[1]))
    raise ValueError(f"unrecognized date '{raw}' (use YYYY-MM-DD or DD/MM/YYYY)")


def _sniff_dialect(sample: str) -> type[csv.Dialect] | csv.Dialect:
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        return csv.excel


def load_employees(path: str | Path, year: int) -> LoadResult:
    """Parse and validate an employee CSV for the given plan year."""
    result = LoadResult()
    weekly_max = Decimal(config.weekly_max_ordinary(year))
    wage_year_warned = False

    with open(path, newline="", encoding="utf-8-sig") as fh:  # utf-8-sig: Excel BOM
        sample = fh.read(4096)
        fh.seek(0)
        reader = csv.DictReader(fh, dialect=_sniff_dialect(sample))
        headers = reader.fieldnames or []

        alias_lookup = {a: canon for canon, aliases in COLUMN_ALIASES.items() for a in aliases}
        colmap: dict[str, str] = {}
        for h in headers:
            canon = alias_lookup.get(_norm_header(h))
            if canon and canon not in colmap:
                colmap[canon] = h
            elif not canon:
                result.issues.append(Issue("WARNING", 0, h, "unknown column ignored"))
        missing = [c for c in REQUIRED if c not in colmap]
        if missing:
            result.issues.append(Issue("ERROR", 0, ",".join(missing), "required column(s) missing"))
            return result

        seen: set[str] = set()
        for n, raw in enumerate(reader, start=1):
            row = {c: (raw.get(h) or "").strip() for c, h in colmap.items()}
            if not any(row.values()):
                continue
            row_issues: list[Issue] = []

            def err(f: str, msg: str) -> None:
                row_issues.append(Issue("ERROR", n, f, msg))

            def warn(f: str, msg: str) -> None:
                row_issues.append(Issue("WARNING", n, f, msg))

            emp_id, store = row.get("employee_id", ""), row.get("store_id", "")
            if not emp_id:
                err("employee_id", "empty")
            elif emp_id in seen:
                err("employee_id", f"duplicate '{emp_id}'")
            if not store:
                err("store_id", "empty")

            zone_raw = row.get("salary_zone", "").lower()
            zone = ZONE_ALIASES.get(zone_raw, config.DEFAULT_ZONE if not zone_raw else "")
            if not zone:
                err("salary_zone", f"'{zone_raw}' not in {config.SALARY_ZONES}")
                zone = config.DEFAULT_ZONE

            hours = weekly_max
            if row.get("contract_weekly_hours"):
                try:
                    hours = Decimal(row["contract_weekly_hours"].replace(",", "."))
                    if not (0 < hours <= weekly_max):
                        err("contract_weekly_hours", f"{hours} outside (0, {weekly_max}] for {year}")
                except InvalidOperation:
                    err("contract_weekly_hours", f"not a number: '{row['contract_weekly_hours']}'")

            mw, mw_year = config.min_wage(year, zone)
            if mw_year != year and not wage_year_warned:
                result.issues.append(Issue(
                    "WARNING", 0, "min_wage",
                    f"no published minimum wage for {year}; using {mw_year} values"))
                wage_year_warned = True

            # --- salary -> SD ---
            sd: Decimal | None = None
            source = "csv"
            amount_raw = row.get("daily_salary") or row.get("salary_amount", "")
            period_raw = "daily" if row.get("daily_salary") else row.get("salary_period", "").lower()
            if amount_raw:
                period = PERIOD_ALIASES.get(period_raw or "daily")
                try:
                    amount = _parse_money(amount_raw)
                    if period is None:
                        err("salary_period", f"unknown period '{period_raw}'")
                    elif amount <= 0:
                        err("salary_amount", "must be > 0")
                    elif period == "hourly":
                        # 6x1: contract hours are paid over 7 days (rest day is paid, Art. 69)
                        sd = amount * hours / 7
                    else:
                        sd = amount / config.PERIOD_DAYS[period]
                except InvalidOperation:
                    err("salary_amount", f"not a number: '{amount_raw}'")
            else:
                sd, source = mw, "imputed_min_wage"
                warn("salary_amount", f"missing; imputed minimum wage {mw} ({zone})")

            if sd is not None:
                sd = sd.quantize(CENT, ROUND_HALF_UP)
                floor = (mw * hours / weekly_max).quantize(CENT, ROUND_HALF_UP)
                if source == "csv" and sd < floor:
                    err("salary_amount",
                        f"SD {sd} below legal minimum {floor} ({zone}, {hours} h/week)")
                elif source == "csv" and sd > mw * 20:
                    warn("salary_amount", f"SD {sd} is >20x minimum wage; check period/units")

            births = hires = None
            for fname in ("birth_date", "hire_date"):
                if row.get(fname):
                    try:
                        d = _parse_date(row[fname])
                        births, hires = (d, hires) if fname == "birth_date" else (births, d)
                    except ValueError as e:
                        err(fname, str(e))

            rest = None
            if row.get("rest_day_preference"):
                rest = WEEKDAYS.get(row["rest_day_preference"].strip().lower()[:3])
                if rest is None:
                    warn("rest_day_preference", f"unrecognized '{row['rest_day_preference']}', ignored")

            result.issues.extend(row_issues)
            if any(i.severity == "ERROR" for i in row_issues):
                continue
            seen.add(emp_id)
            result.employees.append(Employee(
                employee_id=emp_id, store_id=store, daily_salary=sd, salary_source=source,
                salary_zone=zone, contract_weekly_hours=hours, birth_date=births,
                hire_date=hires, role=row.get("role") or None, rest_day_preference=rest,
            ))
    return result
