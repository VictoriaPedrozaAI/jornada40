# Employee roster CSV — schema

Loader: `jornada40/ingest/employees.py::load_employees(path, year)` → `LoadResult(employees, issues)`.
Sample: `data/employees_sample.csv`.

## Columns

| Column (canonical) | Accepted aliases | Req. | Format / default |
|---|---|---|---|
| `employee_id` | id_empleado, numero_empleado, no_empleado | ✅ | Unique string. Use IDs, not names (no PII needed). |
| `store_id` | tienda, id_tienda, sucursal | ✅ | String |
| `salary_amount` | salario, sueldo, salary | – | `315.04`, `$9,800.00`, `1.234,50` all accepted |
| `salary_period` | periodo_salario, periodo | – | daily/diario · weekly/semanal · biweekly/quincenal · monthly/mensual · hourly/por_hora. Default: daily |
| `daily_salary` | salario_diario, sd | – | Shortcut: overrides amount+period |
| `salary_zone` | zona, zona_salarial | – | general · zlfn/frontera. Default: general |
| `contract_weekly_hours` | horas_contrato, horas_semanales | – | Default: legal weekly max for the plan year (40 in 2030) |
| `birth_date` | fecha_nacimiento | – | YYYY-MM-DD or DD/MM/YYYY. Used only to flag minors |
| `hire_date` | fecha_ingreso | – | Same formats. For vacation seniority (Art. 76) |
| `role` | puesto | – | Free text (skill matching later) |
| `rest_day_preference` | dia_descanso | – | mon…sun / lun…dom |

File handling: UTF-8 with or without BOM (Excel), delimiter auto-detected (`,` `;` tab `|`), headers case/space-insensitive, unknown columns ignored with a warning.

## Salary → salario diario (SD)

| Period | SD |
|---|---|
| daily | amount |
| weekly | amount / 7 |
| biweekly | amount / 15 |
| monthly | amount / 30 (divisor configurable in `config.PERIOD_DAYS`) |
| hourly | amount × contract_weekly_hours / 7 (6×1: rest day is paid) |

## Validation policy

| Case | Severity | Behavior |
|---|---|---|
| Salary missing | WARNING | SD = minimum wage of the zone; `salary_source="imputed_min_wage"` |
| SD < minimum wage (pro-rated for part-time: `min × contract_h / weekly_max`) | ERROR | Row rejected — never silently raised to the minimum |
| SD > 20× minimum | WARNING | Likely wrong period/units |
| Duplicate `employee_id`, empty id/store, bad number/date/zone | ERROR | Row rejected |
| `contract_weekly_hours` > legal max for the year | ERROR | Row rejected |
| Plan year without published minimum wage | WARNING | Uses latest known year |

Rejected rows are reported, not dropped silently; the UI must show `issues` before any cost calculation.
