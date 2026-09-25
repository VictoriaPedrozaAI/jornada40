# Current schedule input + compliance check

## Sources
- **Excel grid** (employee × day, shift codes + legend) — `jornada40/ingest/shift_grid.py::import_shift_grid`.
  Tolerant layout detection: header cell `Empleado/Employee/Nombre`, day columns up to a `Horas/Hours`
  column (max 31), legend = any `(code, description with times)` pair in the workbook (`6:00 a.m. - 2:00 p. m.`
  or `13:30-21:30`), or passed via `legend=`. `start_date` is required (templates carry placeholders).
  `id_map` links grid names to `employee_id` in the salary roster.
- **Canonical long format** (internal contract, one row per shift):
  `employee_id, date, code, start, end, hours, jornada_code, jornada_type, night_hours` — see `data/current_schedule_example.csv`.

## Shift code vs jornada type
- `code` is the client's own label (e.g. `L/A/N` in the template) and is kept as-is so their file round-trips.
- `jornada_code` (**D** diurna · **M** mixta · **N** nocturna) is derived from the shift's times and is what the UI shows
  next to it. A client "morning" shift starting at 05:00 is still **M**; renaming codes would hide that.

## Rules applied (`jornada40/shifts.py`, `jornada40/compliance.py`)

| Check | Rule | Notes |
|---|---|---|
| Shift type | Art. 60: night hours in 20:00–06:00; 0 → diurna, < 3.5 → mixta, ≥ 3.5 → nocturna | Shift belongs to the day it starts |
| Daily ordinary max | Art. 61: 8 / 7.5 / 7 h | Excess = overtime (conservative default) |
| Weekly ordinary max | Art. 59 by plan year | Ordinary above max = overtime |
| OT bands | Art. 66/68: first `cap[year]` h at 2×, next 4 h at 3× | Above → VIOLATION |
| OT per day / days per week | ≤ 4 h/day, ≤ 4 days/week | Counts days with shift-type excess |
| Continuous work | Art. 68: ≤ 12 h | Back-to-back shifts merged (e.g. N → L = 16 h) |
| Rest | Art. 69: no 7 consecutive days | |
| Minors | Art. 177–178: ≤ 6 h, no Sunday/feriado | Needs roster `birth_date` |
| Coverage | Hourly headcount vs `requirement(dt)` | GAP / OVERSTAFF runs in person-hours; `cyclic=True` for rotations |

Not LFT rules, intentionally not enforced: minimum rest between shifts (quick turnarounds) — candidate soft constraint.

## Findings on the Smartsheet "EJEMPLO - Turno de 8 horas" template (fixture)
Evaluated as 2030 rules, requirement = 1 person 24/7, cyclic:
- 3 coverage gaps (24 person-hours): two uncovered nights, one uncovered morning.
- 2 × 16 h back-to-back blocks (N → L) — Art. 68 violation.
- 5 employee-weeks with overtime on > 4 days: every 14–22 shift is *mixta* (+0.5 h OT) and every 22–06 shift is *nocturna* (+1 h OT).
- 93.5 h of overtime over 4 weeks for 5 people; two employees share an identical row.

Lesson for the product: 8 h fixed-shift templates designed for the US silently generate overtime under Mexican law — the optimizer must size shifts by jornada type (e.g. 7 h nights, 7.5 h closing shifts).
