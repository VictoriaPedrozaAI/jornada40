from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from jornada40.ingest.employees import load_employees

SAMPLE = Path(__file__).parents[1] / "data" / "employees_sample.csv"


def _csv(tmp_path, text, name="e.csv"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_sample_loads_clean():
    r = load_employees(SAMPLE, 2030)
    assert not r.errors
    assert len(r.employees) == 6
    assert r.imputed_count == 1


def test_period_normalization():
    by_id = {e.employee_id: e for e in load_employees(SAMPLE, 2030).employees}
    assert by_id["E0002"].daily_salary == Decimal("326.67")   # 9800 / 30
    assert by_id["E0004"].daily_salary == Decimal("346.67")   # 5200 / 15
    assert by_id["E0005"].daily_salary == Decimal("248.57")   # 72.50 * 24 / 7


def test_missing_salary_imputes_min_wage_by_zone(tmp_path):
    p = _csv(tmp_path, "employee_id,store_id,zona\nA,T1,\nB,T2,frontera\n")
    by_id = {e.employee_id: e for e in load_employees(p, 2026).employees}
    assert by_id["A"].daily_salary == Decimal("315.04")
    assert by_id["B"].daily_salary == Decimal("440.87")
    assert all(e.salary_source == "imputed_min_wage" for e in by_id.values())


def test_below_min_wage_is_rejected_not_fixed(tmp_path):
    p = _csv(tmp_path, "employee_id,store_id,salario_diario,zona\nA,T1,300,general\nB,T1,400,zlfn\n")
    r = load_employees(p, 2026)
    assert r.employees == []
    assert {i.row for i in r.errors} == {1, 2}


def test_part_time_min_wage_is_prorated(tmp_path):
    # 20h of 40h -> floor 157.52; 160 is legal
    p = _csv(tmp_path, "employee_id,store_id,salario_diario,horas_contrato\nA,T1,160,20\n")
    r = load_employees(p, 2030)
    assert not r.errors and r.employees[0].contract_weekly_hours == Decimal("20")


def test_contract_hours_above_year_cap(tmp_path):
    p = _csv(tmp_path, "employee_id,store_id,horas_contrato\nA,T1,46\n")
    assert load_employees(p, 2027).errors == []
    assert load_employees(p, 2030).errors[0].field == "contract_weekly_hours"


def test_spanish_headers_semicolon_bom_and_money_formats(tmp_path):
    text = "\ufeffID Empleado;Tienda;Sueldo;Periodo\nA;T1;$9,800.00;mensual\nB;T1;2.234,50;semanal\n"
    by_id = {e.employee_id: e for e in load_employees(_csv(tmp_path, text), 2030).employees}
    assert by_id["A"].daily_salary == Decimal("326.67")
    assert by_id["B"].daily_salary == Decimal("319.21")  # 2234.50 / 7, European format

def test_duplicates_and_missing_required_columns(tmp_path):
    r = load_employees(_csv(tmp_path, "employee_id,store_id\nA,T1\nA,T2\n"), 2030)
    assert len(r.employees) == 1 and r.errors[0].message.startswith("duplicate")
    r = load_employees(_csv(tmp_path, "employee_id,salario\nA,400\n", "x.csv"), 2030)
    assert r.errors[0].row == 0 and "store_id" in r.errors[0].field


def test_future_year_falls_back_to_latest_min_wage(tmp_path):
    r = load_employees(_csv(tmp_path, "employee_id,store_id\nA,T1\n"), 2028)
    assert any(i.field == "min_wage" for i in r.issues)
    assert r.employees[0].daily_salary == Decimal("315.04")


@pytest.mark.parametrize("bd,expected", [("2008-09-24", True), ("2008-09-23", False), ("23/09/2008", False)])
def test_minor_detection(tmp_path, bd, expected):
    p = _csv(tmp_path, f"employee_id,store_id,fecha_nacimiento\nA,T1,{bd}\n")
    assert load_employees(p, 2026).employees[0].is_minor(date(2026, 9, 23)) is expected


@pytest.mark.parametrize("raw,expected", [
    ("315,04", "315.04"), ("1,234.56", "1234.56"), ("1.234,56", "1234.56"), ("$9,800.00", "9800.00"), ("1,234", "1234"),
])
def test_money_formats(raw, expected):
    from jornada40.ingest.employees import _parse_money
    assert _parse_money(raw) == Decimal(expected)
