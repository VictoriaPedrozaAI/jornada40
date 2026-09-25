# Review of `MD_Proposal_Roster.md` and the demo baseline

Source: `docs/client/MD_Proposal_Roster.md` (80 FTE, 3,200 h cap, 3 fixed 8 h turns, store 09:00–22:00).
Baseline code: `jornada40/synth/baseline_roster.py` → `data/synthetic/baseline/` (store 20, plan week Mon 28 Sep–Sun 4 Oct 2026, evaluated under the **40 h scenario** — the 2030 rules; the law actually in force in 2026 allows 48 h).

## 1. Review findings on the proposal

| # | Finding | Impact |
|---|---|---|
| R1 | **Crew headcount inconsistent**: §2 counts 3 people pre-open and 3 closing; the §3 matrix lists 5 and 5 | Real total = 3,218 h → **above the 3,200 h cap**, not 10 h below |
| R2 | **1-hour "shifts"** (pre-open, setup, closing) every day of the week | Nobody is hired for 1 h × 7 days (also breaks 6×1). In practice turn workers stay longer → **daily overtime** |
| R3 | Table counts **positions per day, not people**: 50 turn slots × 7 days = 350 person-days; with 2 rest days each that needs 70 people + crews, and it never says who rests when | Rest days are the planning problem the proposal skips |
| R4 | **"Overtime: none" is wrong.** T2 (13–21) and T3 (14–22) include 1–2 h after 20:00 → *jornada mixta*, max 7.5 h (Art. 60–61). The paid 30-min break counts as worked time (Art. 64) | +0.5 h overtime on **every** T2/T3 shift |
| R5 | Coverage is flat; demand is not. The 14:00–17:00 overlap (50 people) is the **quietest** time; the peaks at 12–14 h and 18 h are short. "T2+T3 overlap 14–21" is also off: T1 leaves at 17:00, so 17–21 has 33 people | Overstaffing and understaffing at the same time |
| R6 | Same staffing every day: weekends (+10–20%), paydays and feriados ignored | Weekend peaks short; on a feriado everyone on duty is paid 3× |
| R7 | Pre-open starts **07:00**; our store data assumes 60 min (08–09) | Hour 07 is extra unless receiving really needs it → set `pre_open_minutes = 120` if so |
| R8 | 10 h buffer, no allowance for vacations (Art. 76) or absences (~5% of capacity) | Every absence becomes overtime |
| R9 | Legal table misses Art. 60–61 (mixta), 66–68 (overtime limits), **73 (rest day worked = triple)**, 75 (feriado worked = triple) | These are exactly the cost drivers |

Correction to the brief: working **on Sunday** only adds a 25% prima dominical (Art. 71). It becomes **triple pay** only if Sunday is the worker's **rest day** (Art. 73) or a feriado (Art. 75). The baseline models the rest-day case explicitly.

## 2. Baseline = the proposal + explicit bad-planning adjustments

Kept from the proposal: 8 non-shift staff Mon–Fri 09–17; three fixed turns T1 09–17 (17/day), T2 13–21 (17), T3 14–22 (16) with the §3 roles; same plan every day. Each floor employee belongs to one turn: 25 / 24 / 23 people = 72 + 8 = **80 employees**.

| Adj. | Bad-planning behaviour (parameter in `BaselineParams`) | Legal / cost effect |
|---|---|---|
| A1 | Pre-open and closing covered by the **same turn workers** staying longer: 5 T1 start 07:00 (10 h), 4 T1 start 08:00 (9 h), 5 T3 stay to 23:00 (9 h) | Daily overtime; overtime on 5 days/week > 4 allowed (Art. 66) |
| A2 | Rest days granted by preference (25% Sat–Sun, 14% Sun–Mon…) → Saturday/Sunday short → **9 people called in on their rest day** (Sat: 2, Sun: 7) | Art. 73: paid day + 2× (triple) |
| A3 | Weekday surplus not re-planned: 52–57 people on duty vs 50 slots | Overstaffing |
| A4 | Demand ignored: same headcount every hour and every day | Overstaffing and understaffing at the same time |

Rest days are shuffled across roles with a fixed seed (every role is present every day) and nobody is called in twice in the same week (one real rest day kept, Art. 69).

Salaries are **assumptions** (daily SD, MXN): cashier/sales 315.04 (minimum wage), customer service/warehouse 330, security 350, supervisor 480, managers 420–1,600. Replace them with the client's `employees.csv`.

## 3. Result — store 20, one week (2030 rules)

| Item | MXN / hours |
|---|---|
| Weekly base salaries (80 × 7 × SD) | 211,340.08 |
| Overtime 2× — **250.5 h** | 21,768.22 |
| Prima dominical | 4,200.28 |
| Feriado worked | 0.00 (no feriado in the plan week) |
| Rest day worked (9 call-ins, triple) | 7,020.32 |
| **Premiums** (everything paid above base salaries) | **32,988.82** (13.5% of total) |
| **Total cash cost** | **244,328.90** |
| Overstaffing (capacity, not cash — D22) | 1,035 person-h ≈ 43,667 MXN |
| Understaffing | 597 person-h, **353 at peak hours** |
| LFT findings | 56 employee-weeks with overtime on > 4 days; 9 rest-day call-ins |

Where the 250.5 overtime hours come from: T1 starting 07:00 (70 h), T1 starting 08:00 (28 h), T3 closing to 23:00 (52.5 h), mixta excess on normal T2/T3 shifts (100 h).

Coverage gap (people scheduled − people needed): large surplus every afternoon 14–17 h; shortfalls at 10 h, 12–13 h and 17–18 h; Saturday/Sunday worst (see `coverage_store20.csv`).

## 4. What the optimizer can realistically remove

Cash: most of the overtime (crews and mixta excess disappear with shifts sized by jornada type and staggered starts) and all rest-day call-ins — together ≈ 28.8k MXN, **≈ 11.8% of the weekly cash cost**, to be confirmed by the solver. On top, peaks become fully covered and 1,035 overstaffed hours are freed.

**Feriado weeks (e.g. 16 Nov, 25 Dec) are different:** Art. 75 pays +2 × SD per person who works the day, regardless of hours, and the store must still cover its peak. That cost is mostly unavoidable; the lever is longer, well-placed shifts so nobody is brought in just for a few hours. A previous version of this baseline used a week with 1 May and showed this effect (≈ 31k MXN of feriado pay).

## 5. Open points

- Scale to 50 stores: turn sizes proportional to each store's requirement (store 20 is the average store).
- Confirm with the client: pre-open 1 h or 2 h (R7), real salaries by role, how rest days are actually granted.
