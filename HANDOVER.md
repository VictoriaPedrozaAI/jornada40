# HANDOVER — Jornada40 (AIvena technical challenge) · v0 foundation

Date: 2026-09-24 · Status: **MVP working end-to-end**: data → current-roster cost → CP-SAT optimizer → savings, Streamlit UI (`app.py`), Docker for Hugging Face Spaces. All 50 demo stores (80 employees each) ≥ 8% saving with zero peak shortfall and zero overtime; the app compares 5-day weeks (chain 11.0%, 50/50 stores on goal) vs 6-day weeks (10.3%, 17/50) — D36.
Audience: the next agent, whose job is to **review the logic and the decisions**, not to extend features first.
Tests: `python -m pytest -q` → **63 passed**.

---

## 0. TL;DR for the reviewer

1. Read §1 (goal) and §3 (what exists), then run the tests.
2. Review §4 (decisions) — each has a *why*; challenge any you disagree with.
3. §5 lists **legal interpretations and unverified facts**. These are the highest-risk items: a wrong one silently changes every MXN figure.
4. §6 lists known limitations/bugs I am aware of. §7 is what is missing to meet the challenge.
5. Do not change legal parameters without citing a primary source (DOF / LFT text).

---

## 1. The challenge (source: `Reto_tecnico_-_Head_of_Product_and_Technology.pdf`, in Spanish)

Build in 7 days a **working tool** that, from a store's operational data (customer traffic, historical sales, current staff, current shifts), produces a **weekly schedule proposal** that:

- (a) respects a **40 h/week cap per employee**, and
- (b) quantifies in **MXN the avoided cost** vs the current schedule.

Assumptions given: Mexican retailer, ~50 stores, ~80 FTEs/store, operating Sunday–Sunday. Must show **≥ 8% savings in total labor cost** (overtime + overstaffing avoided) **without understaffing at peak hours**.

Deliverables:
1. The tool running end-to-end without the author (link, credentials, repo).
2. Process evidence: repo, docs, screenshots, assumptions, design decisions, a **constraint traceability note**, and a **log of how agentic tools were used**.
3. 45-min demo, including a simulated conversation with a CFO / COO of a Mexican retailer.

What is evaluated: how the candidate thinks and how fast an idea becomes something working. Output **and** reasoning.

---

## 2. Repository map (`/mnt/user-data/outputs/jornada40/`)

```
README.md                         entry point, run instructions
HANDOVER.md                       this file
requirements.txt                  openpyxl, pytest
docs/
  LFT_rules.md                    legal reference + machine-readable YAML params (§9 of that file)
  employee_csv_schema.md          roster/salary input contract
  deploy_hf_spaces.md             how to publish the Space
  app_method.md                   'Método' tab text (Spanish)
  screenshots/                    app screenshots (evidence)
  current_schedule_input.md       shift-grid import + compliance rules + template findings
  input_formats.md                client upload spec (all CSVs) + how savings are computed
  traffic_data_assessment.md      customer_visit.csv assessment, peaks, synthetic assumptions
  baseline_roster_review.md       client roster review + bad-planning baseline + its cost
  client/MD_Proposal_Roster.md    client's roster proposal (source)
app.py                            Streamlit UI
Dockerfile, .streamlit/           HF Spaces deployment
jornada40/
  optimizer.py                    CP-SAT two-stage optimizer (objective components)
  checks.py                       pre-solve capacity checks
  pipeline.py                     current vs proposed, savings, chain run
  cost.py                         cost engine
  demand.py                       forecast, requirement, peaks
  synth/                          synthetic traffic + baseline roster
  ingest/flat.py                  app CSV templates (one flat schedule file + optional requirement)
  config.py                       legal/payroll constants used by code
  shifts.py                       Shift/ShiftDef model, diurna/mixta/nocturna classification
  compliance.py                   LFT checks, overtime bands, hourly coverage gaps/overstaffing
  ingest/employees.py             roster CSV loader, salary normalization, validation
  ingest/shift_grid.py            Excel employee×day grid importer, legend parser, canonical rows
data/
  templates/                      one example CSV per client input file
  employees_sample.csv            6 sample employees (all salary formats)
  current_schedule_example.csv    canonical rows generated from the Smartsheet template
tests/
  fixtures/smartsheet_24x7_8h_ES.xlsx   client-style template (Smartsheet, Spanish)
  test_employees.py  test_shifts.py  test_shift_grid_and_compliance.py
```

Stack: Python 3.10+ (tested on 3.12), stdlib + `openpyxl`. No DB, no web layer yet.

---

## 3. What exists, layer by layer

### 3.1 Legal reference — `docs/LFT_rules.md`
Rules of the Ley Federal del Trabajo relevant to scheduling and pricing, **as amended by the 40-hour reform** (constitutional reform DOF 2026-03-03; LFT decree DOF 2026-05-01):
- Phase-in of the weekly max: 48 (2026) → 46 (2027) → 44 (2028) → 42 (2029) → 40 (2030), effective each 1 January.
- Overtime (post-reform Art. 66–68): 2× for the first `cap[year]` h/week (9, 9, 10, 11, 12), then up to 4 h at 3×; max 4 OT h/day, max 4 OT days/week, never >12 h total per day. Minors: no overtime.
- Jornada types (Art. 60–61): diurna 8 h, mixta 7.5 h, nocturna 7 h; night window 20:00–06:00; mixta if night part < 3.5 h.
- Rest: 6×1 (Art. 69). Prima dominical ≥ 25% of daily salary (Art. 71). Working the rest day (Art. 73) or a feriado (Art. 75): +2× daily salary on top of the paid day (3× total).
- Feriados (Art. 74) with 2026–2027 calendar, and a list of *non*-mandatory days (Holy Week, 2 Nov, 12 Dec, 24/31 Dec) to be treated as demand events, not cost events.
- Other capacity/cost items: vacations (Art. 76), prima vacacional, aguinaldo, minimum wage 2026, electronic time register from 2027, salary-protection transitory.
- §6.1 salary input policy; §7 hard vs soft constraints; §8 cost formulas; §9 YAML parameter block; §10 sources.

### 3.2 Employee roster — `jornada40/ingest/employees.py`, `docs/employee_csv_schema.md`
- CSV with only `employee_id` and `store_id` required; Spanish/English header aliases; delimiter sniffing; UTF-8 BOM; money formats `315.04`, `315,04`, `$9,800.00`, `1.234,56`.
- Salary normalized to **salario diario (SD)** from daily/weekly(/7)/biweekly(/15)/monthly(/30)/hourly(× contract h / 7).
- Returns `LoadResult(employees, issues)`; issues are `ERROR` (row rejected) or `WARNING` (row accepted).
- `Employee.is_minor(on_date)` from `birth_date`.

### 3.3 Shift model — `jornada40/shifts.py`
- `ShiftDef(code, start, end)`; `Shift.from_def(employee, day, def)` handles overnight shifts. **A shift belongs to the day it starts.**
- Derived: `hours`, `night_hours` (overlap with 20:00–06:00, across multiple nights), `jornada_type`, `jornada_code` (D/M/N), `daily_max`, `ordinary_hours`, `daily_excess_hours`.

### 3.4 Current-schedule importer — `jornada40/ingest/shift_grid.py`
- Reads an employee × day Excel grid (like the Smartsheet template): finds header (`Empleado/Employee/Nombre…`), day columns up to a `Horas/Hours` column (max 31), employee rows until blank/totals row.
- Legend auto-detected anywhere in the workbook as `(code ≤3 chars, description with two times)`; parses `10:00 p. m.` (incl. non-breaking spaces) and `13:30-21:30`. Or pass `legend=`.
- `start_date` is **required** (templates carry placeholders like `DD/MM/AA`). `id_map` links grid names → roster `employee_id`.
- Warnings: identical rows (copy-paste), typed totals ≠ recomputed totals. Errors: unknown codes, no legend/header.
- `to_rows()` → canonical long format: `employee_id, date, code, start, end, hours, jornada_code, jornada_type, night_hours`.

### 3.5 Compliance / coverage engine — `jornada40/compliance.py`
`evaluate(shifts, plan_start, n_days, year, requirement=None, employees=None, cyclic=False) -> Report`
- Per employee per 7-day block from `plan_start`: worked h, ordinary h, OT at 2×, OT at 3×, shifts by type, Sundays, feriados.
- OT = Σ(shift-type daily excess) + max(0, ordinary − weekly_max[year]).
- Findings: `VIOLATION` (illegal), `OVERTIME` (legal but paid), `GAP` (understaffed person-hours), `OVERSTAFF`.
- Checks: 4 h OT/day, 4 OT days/week, absolute weekly OT cap, >12 h continuous work (back-to-back shifts merged), 6×1, minors (6 h/day, no Sunday/feriado), hourly coverage vs `requirement(datetime) -> headcount`.
- `cyclic=True` wraps the horizon for rotating templates (removes the artificial gap at 00:00 of day 1).

### 3.6 Findings on the template (used as demo "before" case)
Evaluated with 2030 rules, requirement = 1 person 24/7, cyclic:
- 3 coverage gaps = 24 person-hours (two nights, one morning).
- 2 Art. 68 violations: N (22–06) followed by L (06–14) = 16 h continuous.
- 5 employee-weeks with OT on > 4 days, because **every 14–22 shift is mixta (+0.5 h OT) and every 22–06 shift is nocturna (+1 h OT)**.
- 93.5 OT hours in 4 weeks for 5 people; two employees share an identical row.
- **Product insight:** US-style fixed 8 h shifts silently create overtime under Mexican law. The optimizer must size shifts by jornada type (7 h nights, 7.5 h closing shifts).

---

## 4. Decisions and why (please challenge)

| # | Decision | Why | Alternative considered |
|---|---|---|---|
| D1 | Legal year is a **parameter**, not hardcoded to 40 h | The 40 h cap is the 2030 end-state; in 2027 it is 46 h. A CFO will ask "what does next year cost me?" | Hardcode 40 h (matches challenge text literally, but is not current law) |
| D2 | **Conservative defaults** on every ambiguous rule (see §5) | A savings claim built on aggressive interpretations collapses in front of a CFO/lawyer. Conservative = overtime is never under-counted | Choose the cheapest interpretation |
| D3 | Default salary = **minimum wage by zone**; roster CSV overrides per employee | Challenge gives no salaries; per-employee SD makes premiums (proportional to SD) realistic and lets the optimizer be cost-aware | Single average salary |
| D4 | Salary below minimum → **reject row**, never auto-correct | Silently fixing illegal input hides a compliance problem the client has | Clamp to minimum |
| D5 | Missing salary → **impute minimum + flag** (`salary_source`) | Lets the report state "X% of payroll imputed" — a credibility item | Reject row |
| D6 | Part-time minimum wage **pro-rated** (`min × contract_h / weekly_max`) | Retail uses part-time; a full-day floor would reject legal contracts | Full daily minimum always |
| D7 | Hourly pay → SD = rate × contract h / 7 | 6×1: the rest day is paid, so weekly pay is spread over 7 days | rate × contract h / 6 |
| D8 | Monthly → SD = /30 (configurable) | Common payroll practice; some clients use 30.4 | Hardcode |
| D9 | Shift belongs to the **day it starts** | Standard payroll practice; one rule for Sunday/feriado attribution | Split hours across calendar days |
| D10 | Jornada type **derived from times**, never from client codes; client codes kept as-is, D/M/N shown as a badge | A client "morning" shift starting 05:00 is legally mixta; renaming codes would hide that and break round-trip with the client's file | Rename client codes to D/M/N (proposed by user, declined with this reasoning; user accepted) |
| D11 | Excel grid importer is **layout-tolerant** (header/legend detection) instead of a fixed template | Clients plan in Excel with their own layouts; a rigid format kills adoption in the pilot | Force our own template only |
| D12 | Canonical **long format** (one row per shift) as internal contract | Same structure for current and proposed schedule → same cost engine for both → avoided cost is an apples-to-apples diff | Keep grids internally |
| D13 | Compliance engine checks **any** schedule (current or proposed) | The optimizer output must pass the same validator; also produces the "before" findings for the demo | Validate only proposals |
| D14 | Employee IDs, not names | No PII needed for scheduling; the template's names are fictitious | Names as keys |
| D15 | Minimum inter-shift rest **not enforced** | Not an LFT rule; candidate soft constraint (well-being/turnover) | Enforce EU-style 11 h |
| D16 | Pure Python, stdlib + openpyxl, no framework yet | Keep v0 reviewable; framework choice belongs to the optimizer/UI step | Start with a web stack |
| D17 | **Stores are independent** (confirmed by user 2026-09-24): no staff sharing across stores, no chain-level headcount/budget coupling → **one CP-SAT model per store per week**, solved in parallel; chain savings = Σ stores | ~30k bool vars per store vs ~1.5M for the chain; one infeasible store does not block the other 49; matches how store managers operate | One chain-wide model (only needed if stores are coupled) |
| D18 | **Full-time only by default**; part-time is an optional "what-if" scenario, off by default | Part-time is uncommon in Mexican retail and not in the brief; IMSS contributions cannot be based below the daily minimum wage, which makes part-time more expensive per hour than it looks. Demand flexibility comes from start times and shift lengths within legal maxima | Part-time as a default lever |
| D19 | Solver money in **integer centavos**; all user-facing figures in pesos | CP-SAT only accepts integer coefficients; centavos keep SD-based amounts exact so the optimizer objective reconciles to the centavo with the independent cost report | Rounded pesos (drift between solver total and cost report) |
| D21 | Client inputs = `stores`, `employees`, `current_schedule`, and `staffing_requirement` **or** `traffic` (+ optional `time_off`, `payroll_actuals`) — spec in `docs/input_formats.md`, templates in `data/templates/` | Minimum data a Mexican retailer can export from Excel/POS/time clock; requirement is mandatory because overstaffing/understaffing only exist relative to it | Ask for everything up front |
| D22 | Savings reported as **cash** (overtime, premiums) vs **freed capacity** (overstaffing hours/FTE valued in MXN), both from the same cost engine | Salaried full-time staff are paid regardless of overstaffing; mixing both as "cash" would not survive a CFO review | Single blended savings number |
| D23 | `customer_visit.csv` treated as **shape-only** data: open window (09–22), intraday entry share, dwell, relative store size. Volume and calendar effects are **explicit assumptions** in `synth/traffic.Scenario` | The file is itself synthetic (uniform dwell/minutes, flat weekday/season, ~0.2 visits/store-day) — see `docs/traffic_data_assessment.md` | Use its volume directly (would need ~0 staff) |
| D24 | Staffing requirement driven by **in-store occupancy**, not entries | With ~65 min dwell, in-store peak lags entries by ~1 h; peaks = 12–14 h and 17–19 h (18 h busiest) | Entries per hour (staff an hour early, short at checkout peak) |
| D25 | Synthetic volume **calibrated from FTE**: average store needs 90% of **72 floor FTE** × 40 h (80 FTE − 8 non-floor per client roster) = 2,592 person-h/week | Ties the demo to the brief; savings then come from how hours are placed, not from an arbitrary volume | Pick a customer count |
| D26 | Baseline "current" roster = client proposal `docs/client/MD_Proposal_Roster.md` + explicit bad-planning adjustments A1–A4 (`synth/baseline_roster.py`, review in `docs/baseline_roster_review.md`) | Grounds the "before" in the client's own planning style; every inefficiency is a named parameter, so savings can be traced to causes | Invent a random bad roster |
| D27 | Work on a designated rest day is priced under Art. 73 (paid day + 2×) and **excluded** from ordinary/overtime hours; a feriado on a rest day is priced once | Avoids paying the same hours twice | Count them also as weekly overtime |
| D28 | Sunday alone = +25% prima dominical; **triple** only on rest day (Art. 73) or feriado (Art. 75) | Corrects the brief's "Sunday paid triple" | — |
| D29 | Planning is anchored to **today (24 Sep 2026)**: plan week = next Mon–Sun (28 Sep–4 Oct 2026); history = last **4** complete weeks (24 Aug–20 Sep); current incomplete week ignored. The week is evaluated under the **40 h scenario** (2030 rules) because that is the challenge, while the law in force in 2026 allows 48 h | A demo about "next week's roster" must use recent data; the 40 h vs 48 h gap is itself a CFO talking point (same roster priced under today's law vs the reform) | Arbitrary 2027 dates (previous version, with 1 May feriado) |
| D30 | Demo demand calibrated on **daily peaks** (+ opening crew), not hours: Σ days (peak + crew) = 95% of 72 floor FTE × 5 days | First optimizer run: a store sized on hours cannot cover its peaks with one 8 h shift per person per day → the optimizer bought overtime. A store's headcount is set by its peaks | Hours-based calibration (D25, superseded) |
| D31 | Optimizer = **two-stage count model**: CP-SAT decides people per shift template per day + employees per weekly pattern (see D35 for week types); then cheapest employees → costliest patterns, shifts → on-duty staff | Per-employee booleans were highly symmetric (38% gap after 30 s); the count model is OPTIMAL in 0.1 s. Off-peak shortfall penalty 150 MXN/person-h (500 made the solver buy 6th days with overtime) | Per-employee x[e,d,t] model |
| D32 | MVP UI = **Streamlit, Spanish labels**, deployed as **Docker Space** on Hugging Face (port 8501, XSRF off for uploads) | Users/evaluators are Mexican; Spaces' Streamlit SDK is deprecated in favor of Docker | Gradio |
| D33 | **50 stores × 80 employees** (8 admin + 72 floor) in the demo, all planned with the same client proposal (each store varies crew sizes and weekend-rest preference, seeded by store id); store traffic varies ±15% and demand is calibrated so the **largest** store's 72 floor staff can cover its peaks | Brief: ~50 stores × ~80 FTE. Same headcount everywhere means smaller stores carry more idle hours, as in real chains | Headcount proportional to traffic (previous version, 60–123 per store) |
| D34 | App input = **one flat CSV** (`programacion_actual.csv`: one row per shift with store, employee, salary, rest days, floor flag) + optional `requerimiento.csv`; without it, the current coverage per hour is kept as requirement. Downloadable template + filled 50-store example | Users export shifts from a time clock/Excel as one table; 4–7 separate files were too much friction. Flow: data → diagnosis (hours paid 2×/3×, their cost) → CTA "Generar nueva programación" → savings | Separate stores/employees/schedule/requirement files (`docs/input_formats.md`, still valid for integrations) |
| D35 | **Rest rule = Art. 69 only (1 rest day per 6 worked).** 5 working days + 2 rest days is NOT a legal requirement; it was a modeling artifact (full-length shifts only). The optimizer now chooses per employee between legal week types: 5 d × 8 h/7.5 h (2 rest days) or 6 d × 6.5 h = 39 h (1 rest day) under 40 h; 6 × 7.5 h under 46 h; 6 × 8 h under 48 h; optionally a 6th full day as priced overtime. UI toggle "semanas de 6 días" (default on) | User: model must follow Art. 69. Demo chain: 6-day weeks cut total understaffing 4,962 → 1,243 person-h and overstaffing 51.2k → 48.0k h, at +58k MXN/week Sunday premium; cash saving 11.0% → 10.5% (lowest store 8.0%). Service vs cash trade-off is a client choice | Keep 5 × 2 only (fewer Sundays, worse coverage) |
| D36 | **Week type is a user-visible trade-off, not a hidden setting.** "Generar nueva programación" runs two scenarios per store — everyone on 5-day weeks (8 h shifts, 2 rest days) vs everyone on 6-day weeks (6.5 h under 40 h, 1 rest day) — and shows a chain comparison (saving, stores meeting the goal, peak and total shortfall, overstaffing, overtime, Sunday premium); the user picks which roster to view/download. The optimizer also supports `week_policy="mixed"` (model decides per employee, best coverage) but it is not in the MVP UI to keep it simple. Per-employee week type and HR impact deferred | User: show the 5 vs 6 trade-off, keep MVP simple. Demo chain (40 h): 5 d = 11.0% saving, 50/50 stores on goal, 4,962 h shortfall; 6 d = 10.3%, 17/50 on goal (188 h peak shortfall, $285k Sunday premium vs $204k), 2,617 h shortfall; mixed = 10.5%, 50/50, 1,243 h | Single on/off toggle (hides the trade-off) |
| D37 | Adopted 3 patterns from `charlesyapai/healthcare_workforce_scheduler_v2` (MIT; React+FastAPI rewrite of a Streamlit v1) **without leaving Streamlit**: (1) job-based menu via `st.navigation(position="top")`: Inicio · Datos · Diagnóstico · Nueva programación, landing with "Probar con la demo" first; (2) cost explainability: savings waterfall (actual → overtime → rest days → feriados → Sunday premium → proposed) for chain and store, plus the CP-SAT objective broken down by component (`OptimizerResult.components`, penalties labelled as weights, not cash); (3) pre-solve capacity check (`jornada40/checks.py`): longest chain of demand slots at least one shift apart → minimum person-days vs staff × days; red = peak shortfall guaranteed (sound: validated against the optimizer), yellow/green = no guarantee | Keeps the working MVP; React+FastAPI stays the planned next architecture (solver package is UI-independent). Their per-person CP-SAT model, streaming callback/Stop and Lab are not needed at our solve times (< 1 s/store) | Full React rewrite before the demo |
| D20 | Optimizer = **OR-Tools CP-SAT** (reviewed `jonaspoelmans/crew_rostering_open_source`, no license → patterns only, no code reuse) | Adopt: pre-generated shift templates, eligibility pre-filter, one class per rule (traceability), history carry-over for 6×1, integer scaling, per-unit decomposition. Avoid: unlinked "worked-day" vars (their rest rule is vacuous), constant objective, hard equality coverage (infeasible instead of informative), double-counted history windows | MILP (PuLP/HiGHS) |

---

## 5. Legal interpretations & unverified facts (highest-risk — verify)

**Interpretations (all configurable or flagged):**
1. **Hours above the Art. 61 daily max are overtime**, even under an Art. 58 agreed distribution (e.g., 4×10 h). Conservative; some counsel would disagree.
2. **Hourly rate basis for overtime**: docs propose `SD/8` (market practice) vs `(SD×7)/weekly_hours` (rises as hours fall). Not yet in code — decide before the cost engine.
3. **Prima dominical stacks** with rest-day/feriado pay when those fall on Sunday. Conservative.
4. **Art. 68 "12 h/day"** implemented as **continuous blocks** (back-to-back shifts merged). An alternative reading is ≤ 12 h per calendar day / rolling 24 h. Consider implementing both.
5. **OT days/week** counts only days with shift-type excess; weekly-excess hours are not assigned to days (conservative in the client's favor; alternative: assign to last days of the week).
6. **Weekly max for night workers** under the reform: code uses the same weekly max for all; whether nocturna has a lower weekly cap (historically 42 h under 6×7) is an open question.
7. **Breaks (Art. 63/64)** not modeled; shift hours = paid, worked hours.
8. **6×1** uses calendar days with a shift start; a night worker finishing 06:00 on their "rest day" is treated as rested. Legal meaning of a full rest day (24 h?) should be confirmed.
9. **Sunday premium for overnight shifts** (Sat 22:00–Sun 06:00): attributed to Saturday by D9 → no prima dominical. Could be contested.

**Facts to verify against primary sources (DOF, CONASAMI, INE):**
- Reform dates and phase-in tables (weekly max and OT cap by year) — taken from secondary legal analyses (Greenberg Traurig, Garrigues, law-firm summaries) + DOF references; confirm the literal decree text.
- Minimum wage 2026: general 315.04 (confirmed in search), **ZLFN 440.87 and UMA 117.31 are from model knowledge — verify**.
- 2027 federal election date (set as 2027-06-06, Sunday) — verify with INE; local elections may add days per state.
- Feriados are duplicated in `docs/LFT_rules.md` §9 YAML **and** `jornada40/config.py` → two sources of truth; consolidate (load YAML in code).

---

## 6. Known limitations / tech debt

- `year` is passed independently of the shift dates (demo evaluates Sep 2026 dates under 2030 rules on purpose, D29). Add an explicit "scenario" label in reports so this is never ambiguous.
- Weeks are 7-day blocks from `plan_start`, not the client's payroll week. Make the week start configurable.
- `OVERTIME` findings are emitted only for weekly excess; daily shift-type excess shows up in `EmployeeWeek.ot_*` but not as findings → reporting inconsistency.
- Coverage is O(hours × shifts): fine for 1 store/week (~80 employees), may need indexing for 50 stores × multiple weeks.
- Continuous-block merge only when shifts touch/overlap (gap = 0); a 15-min gap starts a new block.
- Legend auto-detection is heuristic (any short code next to a text with two times) → possible false positives on noisy workbooks; `legend=` override exists.
- `openpyxl` loads with `data_only=True` (cached values); workbooks never opened/saved in Excel may have no cached formula values. It also warns about unsupported data-validation extensions (harmless).
- Minimum wage for years without a published value falls back to the latest known year (warning emitted) → understates cost for 2027+.
- Duplicate `employee_id`: first occurrence kept, later ones rejected.
- `LOAD_FACTOR` (IMSS/INFONAVIT/ISN/aguinaldo/vacations) is a placeholder (1.35) in docs, not implemented.
- Bugs fixed during handover prep (with tests): `315,04` was parsed as 31504; a weekly-max finding was labeled `VIOLATION` whenever the legal 3× band was used.

---

## 7. What is missing / next (priority order)

Done in MVP: requirement from traffic, cost engine, optimizer, 50-store synthetic chain, CFO-style UI, deploy files, constraint mapping spread across `LFT_rules.md` §7/§9, `config.py`, `compliance.py`, tests.

1. **Deploy** the Space (`docs/deploy_hf_spaces.md`) and put the link in the deliverables.
2. **Constraint traceability note** (deliverable): one table LFT article → config key → code → test.
3. **Roles in the optimizer** (cashiers vs floor vs warehouse, min supervisors) — today one pool.
4. **Structural limit to explain in the demo:** 8 h full-time shifts cannot cover two peaks ~8 h apart (10 h and 18 h); the proposal accepts off-peak shortfall at 10 h and idle hours at 14–16 h. Part-time what-if (D18) is the lever — worth adding as a scenario.
5. Calendar-aware forecast (quincena, feriados); load factor (IMSS/INFONAVIT/ISN) in cost; 3× overtime band and minors in the optimizer.
6. Consolidate feriados (YAML vs `config.py`); verify legal facts in §5.

**Product ambiguities to close** (the Head of Product brief asks for this explicitly):
- Definition of "costo laboral total" baseline (does it include benefits/social costs? which weeks?).
- How the 8% is measured (per week? per store? average across the chain?) and what counts as overstaffing.
- Service standard used to derive requirement from traffic (who sets it: client or us?).
- Allowed shift lengths/start times, role/skill coverage, union/CBA rules that override LFT minimums.
- Does the client use part-time at all (D18)? Store independence is **confirmed** as an assumption (D17).

---

## 8. Agentic-tools log (so far)

| Step | Tool / mode | What the agent did | Human decision |
|---|---|---|---|
| 1 | Claude (claude.ai project "AIvena") + web search | Read the challenge PDF; researched the 2026 LFT reform (DOF, STPS FAQ, law-firm analyses); wrote `docs/LFT_rules.md` | User asked for LFT rules incl. feriados, OT pay, prima dominical |
| 2 | Claude + code execution sandbox | Built roster CSV loader + schema + 12 tests | User set: default salary = minimum wage, per-employee salaries via CSV |
| 3 | Claude + code execution | Analyzed the Smartsheet 24/7 template; evaluated it against LFT | User asked whether the template helps |
| 4 | Claude + code execution | Built shift model, grid importer, compliance engine, fixture tests | User: "take what really helps the logic" |
| 5 | Claude | Added derived D/M/N badge instead of renaming client codes | User proposed renaming codes; agent argued against; user accepted |
| 6 | Claude + code execution | Self-review → fixed 2 bugs, added requirements, wrote this handover | User requested handover |
| 7 | Claude + code execution (git clone, OR-Tools) | Reviewed the CP-SAT crew-rostering repo; attempted a run (crashes before solving); mapped patterns to Jornada40 | User asked for analysis |
| 8 | Claude | Answered part-time / centavos / per-store questions; recorded D17–D20 | User confirmed stores are independent |
| 9 | Claude + code execution | Profiled `customer_visit.csv`; built traffic profile, visit-level generator, forecast, requirement/peaks, 50-store dataset; 6 tests | User asked to assess the file for synthetic traffic and peak hours |
| 10 | Claude + code execution | Reviewed client roster MD (R1–R9), built bad-planning baseline for store 20, rest-day handling in compliance, cost engine v0; recalibrated demand to 72 floor FTE; 5 tests | User asked to review the roster as baseline with overtime and triple-paid rest-day work |
| 11 | Claude + code execution | Fixed baseline role/rest-day correlation and double call-in (6×1); re-anchored dataset to today: history 24 Aug–20 Sep 2026, plan week 28 Sep–4 Oct 2026 | User: we are in September, use the last 4 weeks |
| 12 | Claude + code execution + web search | Built MVP: CP-SAT optimizer (rewritten to count model after symmetry issue), pipeline, uploads, Streamlit app, Dockerfile/HF config; recalibrated on peaks; headless + browser screenshots; 50-store run 12.9% | User: build the MVP for HF Spaces with Streamlit/Gradio |
| 13 | Claude + code execution | App v2 for 50 stores: flat CSV templates + loader, diagnosis of 2×/3× hours and cost, CTA → CP-SAT per store, chain results; demo 50×80; vectorized coverage (chain 50 stores: 0.7 s diagnosis, 4.4 s optimization) | User: 50 shops × 80 FTE, template download/upload, show double-paid hours, CTA button, explain CP-SAT |
| 14 | Claude + code execution | Corrected the 5×2 assumption: week types per Art. 69 (5 d or 6 d within the weekly max), optimizer stage 1/2 rewritten around week types, 5-vs-6 comparison on 50 stores | User: model must use Art. 69 (1 rest per 6 worked) |
| 15 | Claude + code execution | Added week_policy (5 / 6 / mixed) to the optimizer; CTA now runs 5-day and 6-day scenarios and shows the comparison; tests | User: let the user see the 5 vs 6 trade-off, simple MVP, HR out of scope |
| 16 | Claude + code execution + browser | Reviewed the healthcare scheduler Space (repo + live UI); implemented multipage menu, savings waterfall, objective breakdown, pre-solve checks; 3 tests | User: assess that app's CP-SAT/UI/menu, then implement the 3 proposals |
| 17 | Claude + code execution | Generated an independent test company (`scripts/make_test_company.py` → `data/test_company/`: 'Súper Palma', 24 stores, 1,938 employees, week 23–29 Nov 2026) in the app template format; validated end-to-end and recorded reference results in `data/test_company/LEEME.md` | User: create a new company CSV to test the user journey |
| 18 | Claude + code execution | Súper Palma moved to 42 h (6 × 7 h) mid-transition planning, guards 6 × 7 h nocturna; app scenarios limited to the 40 h path (40 / 42 / 44 / 46 h), 48 h removed. Under 40 h: 7.7% saving, peaks fully covered (5,438 → 0 person-h), 5/24 stores ≥ 8% | User: don't consider 48 h; use 42 h as a realistic year-to-year reduction |
| 19 | Claude + code execution | Benchmarked for HF CPU Basic (2 vCPU/16 GB): 50 stores × 2 scenarios ≈ 10 s on 1 vCPU, ~200 MB; CP-SAT workers now = CPU count | User: does it run on the HF free tier? |

All code was executed and tested in the sandbox (`35 passed`). Legal content relies on web sources listed in `docs/LFT_rules.md` §10.

---

## 9. Reviewer checklist

- [ ] `pip install -r requirements.txt && python -m pytest -q` → 63 passed.
- [ ] Re-derive by hand: 14:00–22:00 → mixta (2 h night); 22:00–06:00 → nocturna; 05:00–12:00 → mixta.
- [ ] Re-derive a week: 6 × 8 h diurna in 2030 → 40 ordinary + 8 OT at 2×, no violation.
- [ ] Verify §5 facts against DOF/CONASAMI/INE; update `config.py` **and** YAML (or consolidate first).
- [ ] Decide §5 interpretations 1, 2, 4, 6 with the user before building the cost engine.
- [ ] Check `import_shift_grid` on a second, differently laid-out Excel before trusting D11.
- [ ] Confirm the demo framing: template = "before", LFT findings = hook for the CFO conversation.
