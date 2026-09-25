from collections import Counter
from datetime import date, time
from pathlib import Path

import pytest

from jornada40.compliance import evaluate
from jornada40.ingest.shift_grid import import_shift_grid, parse_time_range, to_rows
from jornada40.shifts import Shift, ShiftDef

FIXTURE = Path(__file__).parent / "fixtures" / "smartsheet_24x7_8h_ES.xlsx"
START = date(2027, 1, 4)  # a Monday
pytestmark = pytest.mark.filterwarnings("ignore::UserWarning")


@pytest.fixture(scope="module")
def grid():
    return import_shift_grid(FIXTURE, START, sheet="EJEMPLO - Turno de 8 horas")


@pytest.mark.parametrize("text,expected", [
    ("Turno nocturno (10:00\xa0p.\xa0m. - 6:00\xa0a.m.)", (time(22), time(6))),
    ("Matutino (6:00 a.m. - 2:00 p. m.)", (time(6), time(14))),
    ("Cierre 13:30-21:30", (time(13, 30), time(21, 30))),
    ("sin horario", None),
])
def test_parse_time_range(text, expected):
    assert parse_time_range(text) == expected


def test_grid_import(grid):
    assert set(grid.legend) == {"L", "A", "N"}
    assert grid.n_days == 28 and len(grid.employees) == 5 and len(grid.shifts) == 102
    assert not [i for i in grid.issues if i.severity == "ERROR"]
    assert any(i.field == "pattern" for i in grid.issues)  # duplicated rows detected
    assert not any(i.field == "total" for i in grid.issues)  # typed totals match
    row = to_rows(grid.shifts)[0]
    assert set(row) >= {"employee_id", "date", "start", "end", "jornada_type"}


def test_template_is_not_lft_compliant(grid):
    r = evaluate(grid.shifts, START, grid.n_days, 2030, requirement=lambda t: 1, cyclic=True)
    rules = Counter(f.rule for f in r.by_kind("VIOLATION"))
    assert rules["Art. 68 max 12 h/day"] == 2          # N -> L back-to-back = 16 h
    assert rules["Art. 66 OT on max 4 days/week"] == 5
    gaps = r.by_kind("GAP")
    assert len(gaps) == 3 and sum(g.hours for g in gaps) == 24  # 2 nights + 1 morning uncovered
    assert r.total_ot_h == 93.5


def test_cyclic_removes_boundary_gap(grid):
    linear = evaluate(grid.shifts, START, grid.n_days, 2030, requirement=lambda t: 1)
    assert len(linear.by_kind("GAP")) == 4


def test_weekly_overtime_bands():
    # 6 x 8 h diurna in 2030 -> 40 ordinary + 8 OT at 2x, no violation
    d = ShiftDef("L", time(6), time(14))
    shifts = [Shift.from_def("E", date(2030, 3, 4 + i), d) for i in range(6)]
    r = evaluate(shifts, date(2030, 3, 4), 7, 2030)
    w = r.weeks[0]
    assert (w.ordinary_h, w.ot_2x_h, w.ot_3x_h) == (40, 8, 0)
    assert not r.by_kind("VIOLATION")


def test_seven_days_straight_violates_6x1():
    d = ShiftDef("L", time(9), time(13))
    shifts = [Shift.from_def("E", date(2030, 3, 4 + i), d) for i in range(7)]
    rules = {f.rule for f in evaluate(shifts, date(2030, 3, 4), 7, 2030).by_kind("VIOLATION")}
    assert "Art. 69 rest day per 6 worked" in rules


def test_3x_band_within_cap_is_overtime_not_violation():
    # 2030: 40 ordinary + 12 OT at 2x + 2 OT at 3x = 54 h -> legal, costly
    d = ShiftDef("L", time(6), time(15))  # 9 h diurna = 8 ordinary + 1 OT/day
    shifts = [Shift.from_def("E", date(2030, 3, 4 + i), d) for i in range(6)]
    r = evaluate(shifts, date(2030, 3, 4), 7, 2030)
    w = r.weeks[0]
    assert w.worked_h == 54 and w.ot_3x_h == 2
    assert not any(f.rule == "Art. 59 weekly max" for f in r.by_kind("VIOLATION"))
