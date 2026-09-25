> **App (MVP) uses a simpler flat format** — one `programacion_actual.csv` (one row per shift with store, employee, salary) + optional `requerimiento.csv`; see `jornada40/ingest/flat.py` and the templates in `data/templates_app/` (decision D34). The multi-file spec below remains the integration contract.

# Input files — what the client uploads

Goal: from these files the tool (1) prices the **current** roster, (2) finds overtime, premiums, overstaffing and understaffing, (3) proposes a **new** roster without them, and (4) reports the saving in **MXN and %**.

Templates with example rows: `data/templates/`. All files: CSV, UTF-8 (Excel BOM ok), `,` or `;` delimiter, Spanish or English headers (aliases as in `docs/employee_csv_schema.md`). Dates `YYYY-MM-DD` or `DD/MM/YYYY`; times `HH:MM` 24 h.

## Minimum set (4 files)

| # | File | One row per | Why we need it |
|---|---|---|---|
| 1 | `stores.csv` | store | Opening hours bound the shifts; salary zone sets minimum wage; service standard converts traffic into headcount |
| 2 | `employees.csv` | employee | Salary (SD) prices every hour and premium; role matches requirement; birth date protects minors |
| 3 | `current_schedule.csv` | shift worked | The "before": what is actually paid today (overtime, Sundays, feriados) |
| 4a | `staffing_requirement.csv` **or** 4b `traffic.csv` | store × hour | Defines what "enough people" means → overstaffing and understaffing can only be measured against it |

Optional: `time_off.csv` (unavailability), `payroll_actuals.csv` (reconciliation, see §6).

---

## 1. `stores.csv`

| Column | Req. | Example | Notes |
|---|---|---|---|
| `store_id` | ✅ | T001 | Key used by all other files |
| `store_name` | – | Tienda Centro | |
| `salary_zone` | – | general / zlfn | Default `general` |
| `state` | – | CDMX | For state payroll tax (ISN) in the load factor |
| `opening_time`, `closing_time` | ✅ | 09:00, 22:00 | Same every day; weekday exceptions in a later version |
| `pre_open_minutes`, `post_close_minutes` | – | 60, 60 | Staff time before opening / after closing. Default 60 |
| `min_headcount_open` | – | 4 | Floor while open (security, cash). Default 2 |
| `customers_per_associate_hour` | only with 4b | 12 | Service standard to derive headcount from traffic |
| `peak_threshold_pct` | – | 20 | Top X% of demand hours = peak (zero understaffing allowed). Default 20 |

## 2. `employees.csv`
Already specified in `docs/employee_csv_schema.md`. Required: `employee_id`, `store_id`. Strongly recommended: salary (else minimum wage is imputed and flagged), `role` (needed if requirement is by role), `birth_date` (minors), `rest_day_preference`.

## 3. `current_schedule.csv` — shifts actually worked

| Column | Req. | Example | Notes |
|---|---|---|---|
| `employee_id` | ✅ | E0001 | Must exist in `employees.csv` |
| `date` | ✅ | 2027-01-04 | Day the shift **starts** |
| `start_time`, `end_time` | ✅ | 22:00, 06:00 | `end < start` = crosses midnight |
| `break_minutes` | – | 30 | Default 0. Breaks where the worker can leave are unpaid (Art. 64) |

- Cover **at least 1 full week** (ideally 4) matching the demand period.
- Use **worked** hours (time clock), not the planned roster, when available — overtime lives in the difference.
- Alternative: the Excel grid (employee × day with shift codes + legend), handled by `jornada40/ingest/shift_grid.py`.

## 4a. `staffing_requirement.csv` — if the client already knows how many people it needs

| Column | Req. | Example | Notes |
|---|---|---|---|
| `store_id` | ✅ | T001 | |
| `date` **or** `weekday` | ✅ | 2027-01-04 / mon | Weekday = same requirement every week |
| `hour` | ✅ | 13 | 0–23, hour starting at that time |
| `role` | – | cajero | Empty = any role |
| `required_headcount` | ✅ | 6 | People on the floor in that hour |
| `is_peak` | – | 1 | Override; else computed with `peak_threshold_pct` |

## 4b. `traffic.csv` — if not, we derive the requirement

| Column | Req. | Example | Notes |
|---|---|---|---|
| `store_id`, `date`, `hour` | ✅ | T001, 2026-12-07, 9 | |
| `customers` | ✅* | 62 | Footfall. *Or `tickets` if no door counter |
| `tickets` | – | 51 | Transactions (POS) |
| `sales_mxn` | – | 15320.50 | Historical sales; used for forecasting and ROI context |
| `occupancy` | – | 403.2 | Average customers **inside** during the hour (from entry/exit sensors or visit logs). Preferred driver: in-store peak lags entry peak by ~1 h (see `docs/traffic_data_assessment.md`) |

Rule: `required = max(min_headcount_open, ceil(forecast_driver / customers_per_associate_hour))`, driver = `occupancy` if provided else `customers`, where the forecast = average of the same weekday-hour over the last N weeks (≥ 4 recommended; 8 better; exclude feriados/Buen Fin or tag them).

## 5. Optional files

- `time_off.csv`: `employee_id, start_date, end_date, reason` — vacations or any unavailability. Keep `reason` generic (no medical detail needed).
- `payroll_actuals.csv`: `employee_id, week_start, ordinary_pay_mxn, overtime_hours_paid, overtime_pay_mxn, sunday_premium_mxn, feriado_pay_mxn` — see §6.

## 6. How the saving is computed (what the user sees)

Both rosters go through the **same** cost engine (so the difference is apples to apples):

```
saving_mxn = cost(current roster) − cost(proposed roster)
saving_pct = saving_mxn / cost(current roster)
```

Broken down into:

| Component | Current roster | Proposed roster |
|---|---|---|
| Overtime 2× / 3× (hours, MXN) | from shifts vs LFT limits for the chosen year | minimized |
| Sunday premium, feriado / rest-day work (MXN) | from dates | minimized |
| Overstaffing (person-hours above requirement × hourly cost) | measured | minimized |
| Understaffing (person-hours below requirement) | measured, peak hours flagged | 0 in peak hours |
| LFT violations (count, type) | listed | 0 |

`payroll_actuals.csv` lets us show "our model of your current cost matches your payroll within X%" before claiming any saving — the first question a CFO will ask.

**Important caveat to show in the report:** full-time salaried staff are paid their daily salary even when overstaffed. Overtime and premium savings are **cash** savings immediately. Overstaffing savings become cash only when the freed hours replace overtime elsewhere, avoid new hires as the legal week drops to 40 h, or allow headcount to adjust through attrition. The report will show them separately: **cash savings** vs **freed capacity (hours / FTE-equivalent, valued in MXN)**.


**Visit-level logs** (`visit_id, customer_id, store_id, date, entry_timestamp, exit_timestamp`) are also accepted as a traffic source: they are aggregated to hourly `customers` and `occupancy` (see `jornada40/synth/traffic_profile.py`).
