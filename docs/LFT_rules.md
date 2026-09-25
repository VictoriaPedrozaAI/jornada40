# Ley Federal del Trabajo (LFT) — Rules Reference for Jornada40

> Scope: rules from Mexico's Ley Federal del Trabajo (Apartado A, private sector) that constrain or price a weekly store schedule.
> Legal baseline: LFT as amended by the decree published in the DOF on **1 May 2026** (in force the same day), implementing the constitutional reform to Art. 123 published in the DOF on **3 March 2026**.
> Last reviewed: 2026-09-23. Not legal advice — validate with labor counsel before production use.

---

## 1. The 40-hour reform — what actually changed

| Article | Rule after the reform |
|---|---|
| Art. 58 | Jornada = time the worker is at the employer's disposal. **Can be distributed by mutual agreement** between employer and worker. |
| Art. 59 | Max ordinary jornada: **40 h/week** (reached gradually, see §1.1). 2nd paragraph (Saturday-afternoon redistribution) **repealed**. |
| Art. 61 | Daily max: **8 h diurna, 7 h nocturna, 7.5 h mixta**. |
| Art. 66 | Overtime ("tiempo extraordinario") paid at **+100%** (2× ordinary hourly rate). Weekly cap phased 9 → 12 h; max **4 h/day** on max **4 days/week**. |
| Art. 67 | 2nd paragraph repealed (old "3 h × 3 times" rule is gone). |
| Art. 68 | Overtime beyond the Art. 66 cap: max **4 extra h/week**, paid at **+200%** (3×). **Ordinary + overtime ≤ 12 h/day, never exceeded.** |
| Art. 69 | At least **1 paid rest day per 6 days worked** ("6×1" rule unchanged — no mandatory 2nd rest day). |
| Art. 71 | Sunday work earns a **prima dominical of ≥ 25%**. |
| Art. 132 XXXIV | **Electronic time register** (start/end per worker) mandatory; STPS technical rules and sanctions apply from **1 Jan 2027**. |
| Art. 994 IV Bis | Fines of **250–5,000 UMA** for register non-compliance (≈ MXN 29,327 – 586,550 at UMA 2026 = 117.31). |
| Transitorio 4° (const.) | Reduction **cannot** be used to cut salaries, wages or benefits. |

### 1.1 Phase-in calendar (effective each 1 January)

| Year | Max ordinary h/week (Art. 59) | Overtime cap at 2× (Art. 66) | Extra band at 3× (Art. 68) | Absolute weekly ceiling |
|---|---|---|---|---|
| 2026 | 48 | 9 | 4 | 61 |
| 2027 | 46 | 9 | 4 | 59 |
| 2028 | 44 | 10 | 4 | 58 |
| 2029 | 42 | 11 | 4 | 57 |
| **2030** | **40** | **12** | **4** | **56** |

- The overtime cap rules (4 h/day, 4 days/week, 12 h/day total, 3× band) apply **since 1 May 2026**; only the weekly overtime cap number moves with the calendar.
- The challenge asks for a **40 h cap per employee** → model the 2030 end-state, but keep the year as a parameter so the tool also answers "what does 2027 look like?" (a likely CFO question).

---

## 2. Jornada types (Art. 60–61)

| Type | Window | Daily max |
|---|---|---|
| Diurna | 06:00–20:00 | 8 h |
| Nocturna | 20:00–06:00 | 7 h |
| Mixta | Spans both; night portion **< 3.5 h** (otherwise it counts as nocturna) | 7.5 h |

Scheduling implications:
- Store closing shifts that cross 20:00 become **mixta**; if ≥ 3.5 h fall after 20:00 they become **nocturna** → lower daily max. Classify each shift before validating it.
- Art. 63: at least **30 min rest** during a continuous jornada. Art. 64: if the worker cannot leave the workplace during it, that time **counts as worked time**. → Decide per client whether breaks are paid/counted.
- Art. 58 allows agreed redistribution (e.g., 4×10 h), but the 12 h/day absolute ceiling (Art. 68) always binds. Whether an agreed 10 h day exceeds the Art. 61 daily max without generating overtime is an **open interpretive point** — treat as configurable, default = conservative (hours above Art. 61 daily max = overtime).

---

## 3. Overtime pay (Art. 66–68)

Let `h` = ordinary hourly rate.

| Band (2030 values) | Rate | Total paid per hour |
|---|---|---|
| Ordinary hours ≤ 40/week | base | 1 × h |
| Overtime hours 1–12 in the week (≤ 4 h/day, ≤ 4 days) | +100% | **2 × h** |
| Overtime hours 13–16 in the week | +200% | **3 × h** |
| > 16 overtime h/week, or > 12 total h in a day | **Not allowed** | — (hard constraint) |

Watch the label trap: "200%" in Art. 68 is the *additional* percentage → total factor is **3×**, not 2×.

Hourly-rate assumption (must be documented in the tool):
- Market practice: `h = salario_diario / 8` (diurna).
- Alternative (weekly basis): `h = (salario_diario × 7) / weekly_ordinary_hours`. Since salaries cannot drop while hours fall, this rate rises every year of the phase-in.
- Expose as a parameter and show sensitivity; it directly moves the "costo evitado" figure.

Who cannot work overtime:
- **Minors (< 18)**: prohibited (Art. 178 + reform). Minors 15–17 also have max 6 h/day and cannot work Sundays or feriados (Art. 177–178).
- **Pregnant / breastfeeding workers**: no overtime or night industrial work when it risks health (Art. 166).
- Workers are not obliged to work beyond the permitted limits (Art. 68).

---

## 4. Weekly rest, Sunday work and prima dominical (Art. 69–73)

- **6×1 rule** (Art. 69): ≥ 1 paid rest day per 6 days worked. Hard constraint: no employee works 7 consecutive days.
- Rest day is **preferably Sunday** (Art. 71, 1st para.). In continuous operations (retail Sunday–Sunday), employer and worker agree which day (Art. 70).
- **Prima dominical** (Art. 71, 2nd para.): worker who works on Sunday (and rests another weekday) gets **≥ 25% of one ordinary daily salary** extra, per Sunday worked.
  - Example: SD = 315.04 (min. wage 2026) → prima = **78.76 MXN** per Sunday.
  - It is paid on top of the normal day's salary, not instead of it.
- **Working on the weekly rest day** (Art. 73): worker is not obliged; if they do, they get their rest-day salary **plus double salary** for the service → **3× SD** for that day.
  - If that rest day is a Sunday, conservative default = also add the 25% prima dominical (interpretations vary — flag in assumptions).

Model rule of thumb: a Sunday shift for someone whose rest day is Tuesday costs **1.25 × SD**; making someone work on their own rest day costs **3 × SD** (+0.25 if Sunday). The optimizer should almost never choose the latter.

---

## 5. Official mandatory rest days — días de descanso obligatorio (Art. 74)

| Date | Holiday |
|---|---|
| 1 January | Año Nuevo |
| 1st Monday of February | Día de la Constitución (5 Feb) |
| 3rd Monday of March | Natalicio de Benito Juárez (21 Mar) |
| 1 May | Día del Trabajo |
| 16 September | Día de la Independencia |
| 3rd Monday of November | Revolución Mexicana (20 Nov) |
| 1 October, every 6 years | Transmisión del Poder Ejecutivo Federal (next: **2030**) |
| 25 December | Navidad |
| Election days | As set by federal and local electoral law for ordinary elections |

### 5.1 Calendar for the tool

| Holiday | 2026 | 2027 |
|---|---|---|
| Año Nuevo | Thu 1 Jan | Fri 1 Jan |
| Constitución | Mon 2 Feb | Mon 1 Feb |
| Benito Juárez | Mon 16 Mar | Mon 15 Mar |
| Día del Trabajo | Fri 1 May | Sat 1 May |
| Independencia | Wed 16 Sep | Thu 16 Sep |
| Revolución | Mon 16 Nov | Mon 15 Nov |
| Navidad | Fri 25 Dec | Sat 25 Dec |
| Federal election | — | Sun 6 Jun (verify final INE date; local elections may add state-specific days) |

**NOT mandatory under LFT** (common confusion — don't apply premium unless a CBA/internal policy says so): Jueves/Viernes Santo, 2 Nov (Día de Muertos), 12 Dec (Virgen de Guadalupe), 24 and 31 Dec. Treat these as *demand* events (traffic peaks/dips), not *cost* events.

### 5.2 Pay for working a feriado (Art. 75)
- Worker keeps the day's salary **plus double salary** for the service → **3× SD** total.
  - Example at SD 315.04 → **945.12 MXN** for the day.
- If the feriado falls on Sunday: add prima dominical (conservative default).
- If the feriado falls on the worker's rest day and they work it: conservative default = apply the higher of Art. 73/75 treatments, not both stacked (flag in assumptions; confirm with counsel).
- Workers and employer agree who works on feriados; for retail, feriado demand forecasting + minimizing feriado headcount is a direct savings lever.

---

## 6. Other rules that affect effective capacity (FTE math)

| Item | Rule | Why it matters |
|---|---|---|
| Vacations (Art. 76) | 12 days after year 1, +2/yr up to 20 days (year 5), then +2 every 5 years | Reduces available hours per FTE (~4–8% of the year) |
| Prima vacacional (Art. 80) | ≥ 25% of vacation salary | Part of total labor cost |
| Aguinaldo (Art. 87) | ≥ 15 days of salary, paid before 20 Dec | Part of fully-loaded hourly cost |
| Minimum wage 2026 | General: 315.04 MXN/day · Zona Libre Frontera Norte: 440.87 MXN/day | Floor for any rate; 2027 value set by CONASAMI in Dec 2026 |
| Salary protection (reform transitorio) | No salary/benefit cut due to hour reduction | Cost per hour rises; savings must come from overtime/overstaffing, not pay cuts |
| Time records & burden of proof (Art. 784 VIII, 804) | Employer must prove hours worked; without records the worker's claim prevails | Tool output doubles as compliance evidence |
| Employer social costs | IMSS, INFONAVIT (5%), state payroll tax (ISN, varies by state) | Needed for "costo laboral total" — model as a load factor parameter |

### 6.1 Salary input policy (project decision)

- **Default assumption:** every employee earns the **minimum wage** of their zone (2026: 315.04 MXN/day general, 440.87 MXN/day ZLFN).
- **Client data overrides it:** a roster CSV can supply a per-employee salary (daily, weekly, biweekly, monthly or hourly), normalized to salario diario (SD). Schema: `docs/employee_csv_schema.md`.
- Salary below the legal minimum (pro-rated for part-time) is **rejected**, never silently corrected.
- Missing salaries are imputed at minimum wage and flagged, so every savings figure can state what share of payroll was imputed.
- Per-employee SD makes the optimizer **cost-aware**: when coverage is equivalent, overtime and Sunday/feriado shifts go to the lower-cost eligible employee — premiums are proportional to SD.

---

## 7. Hard vs soft constraints for the optimizer

**Hard (never violate):**
1. Ordinary hours/employee/week ≤ `MAX_ORD[year]` (40 in 2030).
2. Overtime/employee/week ≤ `OT_CAP[year] + 4`; ≤ 4 OT h/day; OT on ≤ 4 days/week.
3. Ordinary + OT ≤ 12 h in any day.
4. Daily ordinary ≤ 8 / 7.5 / 7 h by shift type (unless agreed distribution is enabled).
5. ≥ 1 rest day per 6 worked; no 7 consecutive days.
6. Minors: ≤ 6 h/day, no OT, no Sunday/feriado.
7. Coverage ≥ required headcount in every interval (no *subdotación* in peak hours).

**Soft (cost-minimized):**
- 2× overtime hours, 3× overtime hours, Sunday premiums, feriado/rest-day work, overstaffing (headcount above requirement), shift fragmentation / employee preferences.

---

## 8. Cost formulas (per employee, per week)

```
h            = SD / 8                              # configurable, see §3
ord_cost     = ord_hours * h
ot2_cost     = min(ot_hours, OT_CAP[year]) * 2 * h
ot3_cost     = max(0, ot_hours - OT_CAP[year]) * 3 * h   # must be ≤ 4 h
sunday_cost  = sundays_worked * 0.25 * SD
feriado_cost = feriados_worked * 2 * SD           # on top of the paid day
restday_cost = restdays_worked * 2 * SD           # on top of the paid day
weekly_cost  = (ord_cost + ot2_cost + ot3_cost + sunday_cost
                + feriado_cost + restday_cost) * LOAD_FACTOR  # IMSS/INFONAVIT/ISN/aguinaldo/vacations
```

`costo_evitado = weekly_cost(current_schedule) − weekly_cost(proposed_schedule)`, reported in MXN per store and scaled to the ~50-store chain.

---

## 9. Parameters (machine-readable)

```yaml
lft:
  source: "DOF 2026-05-01, decreto reforma LFT reducción de jornada"
  weekly_max_ordinary: {2026: 48, 2027: 46, 2028: 44, 2029: 42, 2030: 40}
  overtime_cap_2x:     {2026: 9,  2027: 9,  2028: 10, 2029: 11, 2030: 12}
  overtime_band_3x_hours: 4
  overtime_max_hours_per_day: 4
  overtime_max_days_per_week: 4
  max_total_hours_per_day: 12
  daily_max_ordinary: {diurna: 8, mixta: 7.5, nocturna: 7}
  night_window: ["20:00", "06:00"]
  mixta_night_threshold_hours: 3.5
  min_rest_days_per_6_worked: 1
  prima_dominical_pct: 0.25
  feriado_worked_extra_multiplier: 2      # on top of paid day → 3x total
  restday_worked_extra_multiplier: 2      # on top of paid day → 3x total
  minors: {max_hours_per_day: 6, overtime: false, sunday: false, feriado: false}
  min_wage_daily_2026: {general: 315.04, zlfn: 440.87}
  salary_default: "min_wage_by_zone"      # overridden per employee by roster CSV
  salary_below_min_wage: "reject"
  uma_daily_2026: 117.31
  feriados:
    2026: ["2026-01-01","2026-02-02","2026-03-16","2026-05-01","2026-09-16","2026-11-16","2026-12-25"]
    2027: ["2027-01-01","2027-02-01","2027-03-15","2027-05-01","2027-06-06","2027-09-16","2027-11-15","2027-12-25"]
assumptions_to_confirm:
  - hourly_rate_basis: "SD/8"            # vs (SD*7)/weekly_hours
  - agreed_distribution_over_daily_max_is_overtime: true
  - prima_dominical_stacks_with_restday_or_feriado: true
  - breaks_counted_as_worked_time: false  # Art. 64 depends on whether worker can leave
  - load_factor: 1.35                     # placeholder; replace with client payroll data
```

---

## 10. Sources

- DOF, 1 May 2026 — Decreto que reforma la LFT en materia de reducción de la jornada laboral: https://dof.gob.mx/nota_detalle.php?codigo=5786537&fecha=01%2F05%2F2026
- Cámara de Diputados, reform text (ref. 52): https://www.diputados.gob.mx/LeyesBiblio/ref/lft/LFT_ref52_01may26.pdf
- STPS FAQ — Reducción de la jornada laboral a 40 horas: https://www.gob.mx/stps/documentos/reduccion-de-la-jornada-laboral-a-40-horas-preguntas-frecuentes
- Greenberg Traurig analysis (May 2026): https://www.gtlaw.com/en/insights/2026/5/reforma-a-la-ley-federal-del-trabajo---reduccion
- Garrigues analysis: https://www.garrigues.com/es_ES/noticia/reforma-laboral-2026-2030-reduccion-gradual-jornada-trabajo-mexico
- ILC Abogados (6×1 rule, 5×2 / 4×3 compatibility): https://ilcabogados.com.mx/reforma-laboral-2026-jornada-laboral/
- LFT consolidated text (Arts. 60–80, 87, 166, 175–178, 784, 804): https://www.diputados.gob.mx/LeyesBiblio/pdf/LFT.pdf
