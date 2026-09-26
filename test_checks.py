from datetime import date

import pandas as pd

from jornada40.checks import daily_lower_bound, presolve_checks
from jornada40.optimizer import OptimizerSettings
from jornada40.pipeline import demo_chain, run_store


def test_daily_lower_bound_chains_far_apart_points():
    # slots (30 min): 10:00 needs 20, 18:00 needs 30 -> 8 h apart: an 8 h shift cannot cover both
    needs = {20: 20, 36: 30}
    assert daily_lower_bound(needs, 480) == 50
    assert daily_lower_bound(needs, 510) == 30  # an 8.5 h shift could cover both
    assert daily_lower_bound({20: 5, 30: 7, 40: 9}, 300) == 21  # 10:00, 15:00, 20:00 are 5 h apart: 3 groups
    assert daily_lower_bound({}, 480) == 0


def test_checks_are_sound_on_demo():
    """A red check must always mean peak shortfall in the optimized roster (necessary condition)."""
    ch = demo_chain()
    flagged = []
    for k, v in ch.items():
        for c in presolve_checks(v.requirement, v.week_start, len(v.floor_ids), 2030):
            if c.severity == "error":
                flagged.append((k, c.policy))
    assert flagged, "demo should contain at least one guaranteed peak shortfall (6-day weeks)"
    for k, pol in flagged[:3]:
        r = run_store(ch[k], settings=OptimizerSettings(week_policy=pol))
        assert r.proposed.cost.understaff_peak_person_h > 0


def test_objective_components_sum_to_objective():
    ch = demo_chain()
    r = run_store(ch["20"])
    assert abs(sum(r.opt.components.values()) - r.opt.objective_mxn) < 0.02
    assert r.opt.components["peak_short"] == 0


def test_test_company_files_load_and_run():
    from jornada40.ingest.flat import load_chain
    from jornada40.pipeline import ROOT
    P = ROOT / "data" / "test_company"
    ch = load_chain(P / "programacion_actual.csv", P / "requerimiento.csv", 2030)
    assert not ch.errors and len(ch.stores) == 24
    r = run_store(ch.stores["SP-01"], settings=OptimizerSettings(week_policy="5"))
    assert r.opt.status == "OPTIMAL" and r.proposed.cost.understaff_peak_person_h == 0 and r.saving_pct > 0
    assert r.current.cost.understaff_peak_person_h > 0  # their 7 h fixed shifts leave peaks uncovered


def test_chain_schedule_closed_days_and_hours():
    from jornada40.ingest.flat import load_chain
    from jornada40.pipeline import ROOT
    P = ROOT / "data" / "test_company"
    dh = {d: ("08:00", "21:00") for d in range(6)}
    dh[5] = ("09:30", "20:00")
    dh[6] = None  # Sunday closed
    ch = load_chain(P / "programacion_actual.csv", P / "requerimiento.csv", 2030, day_hours=dh)
    inp = ch.stores["SP-01"]
    assert not ch.errors and inp.store["day_hours"][6] is None
    r = run_store(inp, settings=OptimizerSettings(week_policy="5", allow_sixth_day=False))
    assert r.opt.status == "OPTIMAL" and not any(s.day.weekday() == 6 for s in r.opt.shifts)
    sat = [s for s in r.opt.shifts if s.day.weekday() == 5]
    assert min(s.start.time() for s in sat).strftime("%H:%M") >= "08:30"  # 1 h before 09:30
    assert max(s.end.time() for s in sat).strftime("%H:%M") <= "21:00"  # 1 h after 20:00
    dh[0] = None  # two closed days -> 6-day weeks cannot apply
    ch2 = load_chain(P / "programacion_actual.csv", P / "requerimiento.csv", 2030, day_hours=dh)
    r6 = run_store(ch2.stores["SP-01"], settings=OptimizerSettings(week_policy="6"))
    assert r6.opt.status == "NO_APLICA"
