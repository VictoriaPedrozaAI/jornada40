from datetime import date, time

import pandas as pd
import pytest

from jornada40.ingest.flat import load_chain
from jornada40.optimizer import OptimizerSettings, generate_templates, optimize_store, work_patterns
from jornada40.pipeline import ROOT, demo_input, run_store



def test_templates_are_legal_full_length():
    ts = generate_templates(9 * 60, 22 * 60, 60, 60)
    assert len(ts) == 15
    for t in ts:
        kind = "diurna" if t.code.startswith("D") else "mixta"
        assert t.hours == (8 if kind == "diurna" else 7.5)
        end = t.start.hour * 60 + t.start.minute + t.hours * 60
        assert 8 * 60 <= t.start.hour * 60 + t.start.minute and end <= 23 * 60
        if kind == "mixta":
            assert 0 < end - 20 * 60 < 210  # < 3.5 h of night


def test_patterns_and_week_types():
    from jornada40.optimizer import week_types
    assert len(work_patterns(5)) == 21 and len(work_patterns(6)) == 7
    wt = {w.name: w for w in week_types(2030, True, True)}
    assert wt["6d"].days * wt["6d"].diurna_len / 60 <= 40  # 6 x 6.5 h = 39 h, legal (Art. 69: 1 rest day)
    assert wt["5d"].days * wt["5d"].diurna_len / 60 == 40
    assert wt["6d+ot"].overtime_h == 8
    wt26 = {w.name: w for w in week_types(2026, True, True)}
    assert wt26["6d"].diurna_len == 480 and "6d+ot" not in wt26  # 6 x 8 h = 48 h is ordinary in 2026


@pytest.fixture(scope="module")
def store20():
    return run_store(demo_input(20))


def test_store20_meets_challenge(store20):
    r = store20
    assert r.opt.status == "OPTIMAL"
    assert r.saving_pct >= 8
    assert r.proposed.cost.understaff_peak_person_h == 0
    assert r.proposed.cost.overtime_hours == 0
    assert not r.proposed.report.by_kind("VIOLATION")
    assert r.proposed.cost.restdays_worked == 0


def test_every_employee_full_time_and_rests(store20):
    rows = pd.DataFrame([(s.employee_id, s.day, s.hours) for s in store20.proposed.shifts],
                        columns=["e", "d", "h"])
    per = rows.groupby("e").agg(days=("d", "nunique"), h=("h", "sum"))
    assert per.days.isin([5, 6]).all()  # >= 1 rest day (Art. 69)
    assert (per.h <= 40).all() and (per.h >= 37.5).all()
    assert rows.groupby(["e", "d"]).size().max() == 1


def test_six_day_weeks_improve_coverage():
    inp = demo_input(20)
    five = run_store(inp, settings=OptimizerSettings(allow_six_day_weeks=False))
    six = run_store(inp, settings=OptimizerSettings(allow_six_day_weeks=True))
    assert six.proposed.cost.understaff_person_h < five.proposed.cost.understaff_person_h
    assert six.proposed.cost.overtime_hours == five.proposed.cost.overtime_hours == 0


def test_scarce_staff_reports_peak_shortage_instead_of_failing():
    inp = demo_input(20)
    floor = inp.employees[inp.employees.is_floor == 1].head(30)[["employee_id", "daily_salary"]]
    res = optimize_store(floor, inp.requirement, inp.store, inp.week_start, OptimizerSettings(allow_sixth_day=False))
    per = pd.Series([s.employee_id for s in res.shifts]).value_counts()
    assert res.status == "OPTIMAL" and len(per) == 30 and per.isin([5, 6]).all()


TPL = ROOT / "data" / "templates_app"


def test_flat_upload_roundtrip_matches_demo(store20):
    ch = load_chain(TPL / "ejemplo_programacion_actual_50_tiendas.csv", TPL / "ejemplo_requerimiento_50_tiendas.csv")
    assert not ch.errors and len(ch.stores) == 50
    assert all(len(v.employees) == 80 for v in ch.stores.values())
    r = run_store(ch.stores["20"])
    assert round(r.saving_pct, 3) == round(store20.saving_pct, 3)


def test_flat_upload_without_requirement_keeps_current_coverage():
    ch = load_chain(TPL / "ejemplo_programacion_actual_50_tiendas.csv")
    assert ch.requirement_source == "current coverage" and len(ch.stores) == 50
    r = run_store(ch.stores["20"])
    assert r.proposed.cost.understaff_peak_person_h == 0 and r.saving_pct > 0


def test_flat_rejects_below_minimum_wage(tmp_path):
    p = tmp_path / "p.csv"
    p.write_text("tienda,empleado,salario_diario,fecha,entrada,salida\nT1,E1,200,2026-09-28,09:00,17:00\n")
    ch = load_chain(p)
    assert ch.errors and not ch.stores


def test_flat_accepts_english_headers_semicolons_and_overnight(tmp_path):
    p = tmp_path / "p.csv"
    p.write_text("store_id;employee_id;daily_salary;date;start_time;end_time\n"
                 "T1;E1;400;28/09/2026;22:00;06:00\nT1;E2;400;2026-09-28;14:00;22:00\n")
    ch = load_chain(p)
    assert not ch.errors
    sh = sorted(ch.stores["T1"].current_shifts, key=lambda s: s.employee_id)
    assert sh[0].hours == 8 and sh[0].jornada_code == "N"


def test_assessment_counts_double_hours(store20):
    from jornada40.pipeline import assessment_row
    row = assessment_row("20", store20.inp, store20.current, 2030)
    assert row["horas_dobles"] == 250.5 and row["tope_semanal_h"] == 40
    assert row["costo_horas_dobles"] > 0


@pytest.mark.parametrize("policy,days", [("5", {5}), ("6", {6})])
def test_week_policy_forces_week_type(policy, days):
    inp = demo_input(20)
    r = run_store(inp, settings=OptimizerSettings(week_policy=policy, allow_sixth_day=False))
    per = pd.Series([s.day for s in r.proposed.shifts if s.employee_id in inp.floor_ids]).groupby(
        [s.employee_id for s in r.proposed.shifts if s.employee_id in inp.floor_ids]).nunique()
    assert set(per.unique()) == days
    assert r.proposed.cost.overtime_hours == 0 and not r.proposed.report.by_kind("VIOLATION")
