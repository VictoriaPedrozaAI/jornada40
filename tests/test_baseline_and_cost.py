from collections import Counter
from datetime import date, time
from decimal import Decimal

import pandas as pd

from jornada40.compliance import evaluate
from jornada40.cost import coverage_table, price
from jornada40.shifts import Shift, ShiftDef
from jornada40.synth.baseline_roster import build_baseline, daily_salaries

W = date(2026, 9, 28)


def test_baseline_structure():
    b = build_baseline(20, W)
    assert len(b.employees) == 80
    assert Counter(b.employees.turn) == {"T1": 25, "T2": 24, "T3": 23, "ADM": 8}
    rows = b.shift_rows()
    # every turn has at least its slots every day (A2 call-ins fill weekend gaps)
    per = rows[rows.code != "ADM"].groupby(["date", "code"]).size().unstack()
    assert (per["T1"] >= 17).all() and (per["T2"] >= 17).all() and (per["T3"] >= 16).all()
    assert rows.on_rest_day.sum() == 9  # Sat + Sun call-ins
    # 6x1 respected even with call-ins (2 rest days, at most 1 worked)
    assert rows.groupby("employee_id").size().max() == 6


def test_baseline_overtime_comes_from_crews_and_mixta():
    b = build_baseline(20, W)
    r = evaluate(b.shifts, W, 7, 2030, rest_days=b.rest_days)
    assert r.total_ot_h == 250.5  # 98 crews T1 + 52.5 closing + 100 mixta T2/T3
    assert sum(w.restdays_worked for w in r.weeks) == 9
    assert not any(f.rule == "Art. 69 rest day per 6 worked" for f in r.findings)


def test_restday_hours_not_double_counted_as_overtime():
    d = ShiftDef("L", time(9), time(17))
    shifts = [Shift.from_def("E", date(2030, 3, 4 + i), d) for i in range(6)]  # Mon-Sat
    r = evaluate(shifts, date(2030, 3, 4), 7, 2030, rest_days={"E": {5, 6}})
    w = r.weeks[0]
    assert (w.worked_h, w.ot_2x_h, w.restdays_worked) == (40, 0, 1)
    c = price(r, {"E": Decimal("315.04")})
    assert c.restday_extra == Decimal("630.08") and c.overtime_2x == 0
    assert c.base_salary == Decimal("2205.28")


def test_price_components():
    d = ShiftDef("L", time(8), time(17))  # 9 h diurna -> 1 h OT/day
    days = [date(2027, 4, 26 + i) for i in range(5)] + [date(2027, 5, 2)]  # Mon-Fri + Sun
    shifts = [Shift.from_def("E", x, d) for x in days]
    r = evaluate(shifts, date(2027, 4, 26), 7, 2030)
    c = price(r, {"E": Decimal("320")})
    # 54 h: 48 ordinary -> 8 weekly excess + 6 daily excess = 14 OT -> 12 at 2x, 2 at 3x (h = 40)
    assert c.overtime_2x == Decimal("960.00") and c.overtime_3x == Decimal("240.00")
    assert c.prima_dominical == Decimal("80.00")


def test_coverage_table_counts_extra_hours_as_overstaff():
    d = ShiftDef("L", time(7), time(10))
    shifts = [Shift.from_def("E", date(2027, 4, 26), d)]
    req = pd.DataFrame({"date": ["2027-04-26"] * 2, "hour": [8, 9], "required_headcount": [1, 2], "is_peak": [0, 1]})
    cov = coverage_table(shifts, req)
    c = price(evaluate(shifts, date(2027, 4, 26), 7, 2030), {"E": Decimal(320)}, coverage=cov)
    assert (c.overstaff_person_h, c.understaff_person_h, c.understaff_peak_person_h) == (1, 1, 1)
