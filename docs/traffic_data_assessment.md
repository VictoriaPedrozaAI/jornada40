# Customer visit data — assessment and synthetic traffic design

Source: `data/customer_visit_sample.csv` (client-provided, 30,889 visits).
Columns: `visit_id, customer_id, store_id, date, entry_timestamp, exit_timestamp`.

## 1. What the file contains

| Check | Result |
|---|---|
| Rows / nulls / duplicate ids | 30,889 / 0 / 0 |
| Period | 2019-01-02 → 2024-12-31 (2,168 days) |
| Stores / customers | 60 / 5,598 (customers visit 1–10 different stores) |
| Store hours implied | first entry 09:00, last entry 20:59, last exit 21:59 → **open 09:00–22:00** |
| Dwell time | 1–120 min, **uniform** (mean 65 min); truncated at closing for late entries |
| Entries by hour | 3 flat blocks: 09 h (15%), 12 h (20%), 17 h (20%), 18 h (10%); ~5% every other hour; ~2–3% after 19 h |
| Minutes within each hour | uniform |
| Weekday / month / year | **flat** (±2%); no 2020 COVID dip, no December peak, no quincena effect |
| Volume | **1.16 visits per store-day** on the days with any visit; 21% of store-days have visits |
| Quality issues | 6 customer-days with overlapping visits; last-hour dwell truncated by closing |

## 2. Verdict

The file is **itself synthetic** (uniform minutes and dwell, step-shaped hourly shares, no calendar effects, a volume of ~0.2 visits per store per day, thousands of times below a store with 80 FTE). It cannot be used as-is for staffing volume or calendar patterns. It **is** useful for:

1. **Store opening window** — 09:00–22:00, last entry ~21:00.
2. **Intraday shape** — relative entry share per hour.
3. **Dwell time** — turns entries into **in-store occupancy**, which is what floor staff actually serve.
4. **Relative store size** — visits per store range from 0.54× to 3.26× the median store.

## 3. Key finding: in-store peak ≠ entry peak

Because customers stay ~1 h, occupancy lags entries by about an hour:

| Hour | 9 | 10 | 11 | 12 | 13 | 14 | 15 | 16 | 17 | 18 | 19 | 20 | 21 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Entries % | 15.1 | 4.7 | 4.9 | **20.2** | 4.9 | 5.0 | 5.0 | 4.8 | **20.4** | 10.0 | 3.0 | 1.9 | 0 |
| Checkouts % | 2.8 | 8.9 | 7.7 | 7.7 | **12.9** | 9.4 | 5.0 | 5.0 | 7.8 | **14.0** | 11.6 | 4.8 | 2.4 |
| In store % | 6.3 | 9.5 | 5.7 | 11.2 | **12.6** | 6.3 | 5.0 | 5.0 | 11.3 | **14.8** | 8.0 | 3.2 | 1.2 |

→ **Peak windows: 12:00–14:00 (lunch) and 17:00–19:00 (after work)**; 18 h is the busiest hour. Staffing to the entry peak would put people on the floor an hour early and leave the checkout peak short. The requirement therefore uses **occupancy**; a future role split would use checkouts for cashiers.

## 4. How the synthetic dataset is built (`jornada40/synth/`)

Learned from the file (`traffic_profile.py` → `data/profiles/traffic_profile.json`): open window, entry share per hour, dwell sample, store size.

Assumed (not in the file; all parameters in `synth/traffic.Scenario`, change them to test sensitivity):

| Assumption | Value | Rationale |
|---|---|---|
| Volume | calibrated so the average store needs **90% of 72 floor FTE × 40 h = 2,592 person-h/week** (≈ 3,900 customers/day); 8 of the 80 FTE are non-floor managers/admin (client roster, `docs/baseline_roster_review.md`) | Challenge brief: ~80 FTE per store |
| Service standard | 12 customers in store per associate; floor of 4 people while open; opening and closing crew of 4 (08–09 h, 22–23 h) | Placeholder; client-specific |
| Weekday factors Mon→Sun | 0.90, 0.88, 0.92, 0.95, 1.08, 1.20, 1.12 | Mexican retail is weekend-heavy |
| Quincena | +8% on the 15th–17th and last day–2nd | Paydays on the 15th and last day of month |
| Seasonality | December ×1.20, January ×0.92 | Christmas / "cuesta de enero" |
| Feriados | ×1.05 | Stores open; mild uplift |
| Store size | file's relative size ^0.5, normalized to mean 1 | Keeps stores near the ~80 FTE brief (range ≈ 50–120 FTE-equivalent) |
| Noise | Poisson customers; lognormal day factor σ = 0.05 | |
| Checkout conversion / ticket | 75%; MXN 320 average ticket (lognormal) | Placeholder for `tickets`, `sales_mxn` |

Simulation is at visit level (entry minute + dwell) and aggregated per hour into the `traffic.csv` format plus an `occupancy` column.

## 5. Demo dataset (`python -m jornada40.synth.build_dataset` → `data/synthetic/`)

- Dates are anchored to **today (Thu 24 Sep 2026)**: plan week = **next week, Mon 28 Sep–Sun 4 Oct 2026**; history = the **last 4 complete weeks, Mon 24 Aug–Sun 20 Sep 2026** (includes the 16 Sep feriado, excluded from the forecast, and two quincenas). The current week (21–27 Sep) is incomplete and not used. `HISTORY_WEEKS` can be set to 8 for a steadier average.
- 50 stores (5 in the northern border zone, ZLFN).
- `traffic_history.csv` (18,200 rows), `traffic_plan_week_actual.csv`, `traffic_plan_week_forecast.csv`, `staffing_requirement.csv`, `peak_summary.csv`, `stores.csv`.
- Result: required 2,632 person-h/week on average per store (range 1,823–4,419); peak hours 13 h and 18 h on 100% of store-days, 17 h on 75%, 12 h on 55%.
- Forecast (same weekday-hour average over 4 weeks, feriados excluded): 7.3% hourly error. Under-forecast by 4–7% on Wed 30 Sep–Fri 2 Oct, the quincena window (payday on the 30th), because the naive forecast ignores it. **Adding calendar features to the forecast is a clear improvement**, and a good demo talking point.

## 6. What to ask a real client for instead

Hourly door-counter or POS ticket counts per store for ≥ 8 weeks (ideally 1 year for seasonality), plus their service standard. With real data, the calibration step disappears and the assumptions in §4 are replaced by measured effects.
