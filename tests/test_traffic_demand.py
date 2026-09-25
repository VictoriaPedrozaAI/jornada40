from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from jornada40.demand import forecast_traffic, staffing_requirement
from jornada40.synth.traffic import Scenario, day_factor, generate_traffic
from jornada40.synth.traffic_profile import intraday_curves, profile_from_visits

SAMPLE = Path(__file__).parents[1] / "data" / "customer_visit_sample.csv"


@pytest.fixture(scope="module")
def profile():
    return profile_from_visits(SAMPLE)


def test_profile_matches_source(profile):
    assert (profile.open_minute, profile.close_minute) == (9 * 60, 22 * 60)
    assert profile.source_rows == 30889
    assert abs(sum(profile.entry_share.values()) - 1) < 1e-9
    top = sorted(profile.entry_share, key=profile.entry_share.get, reverse=True)[:3]
    assert set(top) == {9, 12, 17}  # entry bursts


def test_occupancy_peaks_lag_entries(profile):
    occ = intraday_curves(profile)["occupancy"]
    assert set(occ.nlargest(4).index) == {12, 13, 17, 18}
    assert occ.idxmax() == 18


def test_generator_is_deterministic_and_scaled(profile):
    a = generate_traffic(profile, [1, 2], date(2027, 3, 1), 7, 1000, seed=7)
    b = generate_traffic(profile, [1, 2], date(2027, 3, 1), 7, 1000, seed=7)
    pd.testing.assert_frame_equal(a, b)
    assert set(a.hour) == set(range(9, 22))
    per_day = a.groupby(["store_id", "date"]).customers.sum()
    assert 700 < per_day.mean() < 1300


def test_calendar_factors():
    sc = Scenario()
    sat, tue = day_factor(date(2027, 3, 6), sc), day_factor(date(2027, 3, 9), sc)
    assert sat > tue
    assert day_factor(date(2027, 3, 15), sc) > day_factor(date(2027, 3, 8), sc)  # payday + feriado
    assert day_factor(date(2027, 12, 8), sc) > day_factor(date(2027, 11, 10), sc)  # December


def test_requirement_floor_crew_and_peaks():
    stores = pd.DataFrame([{"store_id": 1, "opening_time": "09:00", "closing_time": "22:00",
                            "pre_open_minutes": 60, "post_close_minutes": 60, "min_headcount_open": 4,
                            "customers_per_associate_hour": 10, "peak_threshold_pct": 20}])
    occ = {h: v for h, v in zip(range(9, 22), [5, 100, 50, 120, 200, 60, 50, 50, 110, 220, 90, 30, 5])}
    tr = pd.DataFrame([{"store_id": 1, "date": "2027-04-26", "hour": h, "occupancy": v} for h, v in occ.items()])
    r = staffing_requirement(tr, stores).set_index("hour")
    assert r.loc[8, "required_headcount"] == 4 and r.loc[22, "required_headcount"] == 4  # crews
    assert r.loc[9, "required_headcount"] == 4  # floor
    assert r.loc[18, "required_headcount"] == 22  # ceil(220/10)
    assert sorted(r[r.is_peak == 1].index) == [12, 13, 18]  # top 20% of 13 h = 3 hours


def test_forecast_excludes_feriados(profile):
    hist = generate_traffic(profile, [1], date(2027, 3, 8), 14, 1000, seed=3)  # includes Mon 15 Mar
    fc = forecast_traffic(hist, date(2027, 4, 26), 7)
    mon = fc[fc.date == "2027-04-26"].set_index("hour").customers
    only_8 = hist[hist.date == "2027-03-08"].set_index("hour").customers
    pd.testing.assert_series_equal(mon.astype(float), only_8.astype(float), check_names=False)
