from datetime import date, time

import pytest

from jornada40.shifts import Shift, ShiftDef

D = date(2027, 1, 4)


@pytest.mark.parametrize("start,end,jtype,night,excess", [
    (time(6), time(14), "diurna", 0, 0),
    (time(14), time(22), "mixta", 2, 0.5),
    (time(22), time(6), "nocturna", 8, 1),
    (time(16), time(23, 30), "nocturna", 3.5, 0.5),   # exactly 3.5 night -> nocturna
    (time(12), time(19), "diurna", 0, 0),
    (time(5), time(12), "mixta", 1, 0),              # early start counts as night
])
def test_classification(start, end, jtype, night, excess):
    s = Shift.from_def("E", D, ShiftDef("X", start, end))
    assert (s.jornada_type, s.night_hours, s.daily_excess_hours) == (jtype, night, excess)


def test_overnight_shift_belongs_to_start_day():
    s = Shift.from_def("E", D, ShiftDef("N", time(22), time(6)))
    assert s.day == D and s.end.date() == date(2027, 1, 5) and s.hours == 8


def test_jornada_code_comes_from_times_not_client_code():
    # client calls it "L" (morning) but a 05:00 start makes it mixta
    s = Shift.from_def("E", D, ShiftDef("L", time(5), time(12)))
    assert s.code == "L" and s.jornada_code == "M"
