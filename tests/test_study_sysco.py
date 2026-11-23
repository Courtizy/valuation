"""The Sysco FY2026 study reproduces from its frozen inputs (offline).

Run: pytest tests/test_study_sysco.py
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

STUDY = Path(__file__).resolve().parents[1] / "studies" / "sysco-fy2026"


@pytest.fixture(scope="module")
def case():
    spec = importlib.util.spec_from_file_location("sysco_case", STUDY / "case.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def res(case):
    return case.run(case.load())


def test_inputs_are_point_in_time(case):
    inp = case.load()
    for line, x in inp["known"].items():
        for fy, rec in x.items():
            if fy != "tag" and rec:
                assert rec["filed"] <= inp["cutoff"], f"{line} {fy} filed after the cutoff"
    assert all(x["FY2026"]["filed"] == "2026-08-21" for x in inp["outcome"].values())


def test_cash_flow_model_reconstructs_fy2025_cfo(res):
    # NI + D&A + SBC - trade NWC explains reported FY2025 CFO to within 2%.
    d = res["drivers"]
    assert abs(d["cfo_other_fy2025"]) / d["cfo_fy2025"] < 0.02


def test_documented_case_numbers(res):
    a, b = res["cases"]["A_hold_ratio"], res["cases"]["B_repeat_fy2025"]
    assert a["fy2026"]["cfo"] == pytest.approx(2873.4, abs=0.5)
    assert b["fy2026"]["cfo"] == pytest.approx(2597.3, abs=0.5)
    assert res["actual_fy2026"]["cfo"] == 2638
    assert res["cost_of_capital"]["food_wholesalers"]["wacc"] == pytest.approx(0.0671, abs=5e-5)
    assert a["value"]["food_wholesalers"]["per_share"] == pytest.approx(94.05, abs=0.01)
    assert b["value"]["food_wholesalers"]["per_share"] == pytest.approx(82.89, abs=0.01)
    assert a["value"]["retail_grocery_engine"]["per_share"] == pytest.approx(74.94, abs=0.01)


def test_workbook_agrees_with_script(case, res):
    pytest.importorskip("openpyxl")
    assert case.check_workbook(res) == []
