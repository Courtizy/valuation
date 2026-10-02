"""Parity tests against the course workbooks. Local only.

Set VALUATION_COURSE_DIR to the folder holding the workbooks, and map each
check to a workbook in tests/course_cases.local.json (gitignored; see
course_cases.example.json). Tests skip when either is missing, when a workbook
is missing, or when openpyxl isn't installed. The
workbooks are never copied into the repo; inputs and expected values are read
from them at test time (cached cell values, as last saved by Excel).

Legacy .xls files are converted with LibreOffice (soffice) into a temp folder.

Run: VALUATION_COURSE_DIR=/path/to/workbooks pytest tests/test_course_parity.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from core.projection import project
from L1_detail.analysis import load_classification, managerial_ratios, mbs_free_cash_flow, reformulated_ratios

COURSE = os.environ.get("VALUATION_COURSE_DIR")
_CONVERTED = Path(tempfile.gettempdir()) / "valuation_course_xlsx"
# Which workbook backs which check lives in a local, gitignored file
# (see course_cases.example.json), so no course file names are committed.
_CASES_FILE = Path(os.environ.get("VALUATION_COURSE_CASES", Path(__file__).with_name("course_cases.local.json")))
CASES = json.loads(_CASES_FILE.read_text()) if _CASES_FILE.exists() else {}
FIRM_DCF_CASES = CASES.get("firm_dcf", {"case_a": None})


def _book(rel: str | None):
    if not COURSE:
        pytest.skip("VALUATION_COURSE_DIR not set")
    if not rel:
        pytest.skip(f"no workbook mapped in {_CASES_FILE.name}")
    openpyxl = pytest.importorskip("openpyxl")
    path = Path(COURSE).expanduser() / rel
    if not path.exists():
        pytest.skip(f"missing {rel}")
    if path.suffix == ".xls":
        target = _CONVERTED / (path.stem + ".xlsx")
        if not target.exists():
            soffice = shutil.which("soffice") or shutil.which("libreoffice")
            if not soffice:
                pytest.skip("LibreOffice needed to read .xls")
            _CONVERTED.mkdir(parents=True, exist_ok=True)
            subprocess.run([soffice, "--headless", "--convert-to", "xlsx", "--outdir", str(_CONVERTED), str(path)],
                           check=True, capture_output=True, timeout=120)
        path = target
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return openpyxl.load_workbook(path, data_only=True)


def _num(x):
    return float(x or 0)


# ------------------------------------------------- 772: projection and MBS

def test_772_balance_sheet_projection():
    ws = _book(CASES.get("projection_bs")).active
    c = lambda a: _num(ws[a].value)  # noqa: E731
    base = dict(revenue=c("D3"), cogs=c("D4"), depreciation=c("D6"), interest_expense=c("D8"),
                income_taxes=c("D10"), net_income=c("D12"), cash=c("D15"), receivables=c("D16"),
                inventory=c("D17"), other_current_assets=c("D18"), fixed_assets=c("D20"),
                payables=c("D22"), short_term_debt=c("D23"), accrued=c("D24"),
                long_term_debt=c("D26"), other_lt_liabilities=c("D27"), equity=c("D29"))
    drivers = {
        "revenue": {"method": "values", "values": [c("E3")]},
        "cogs": {"method": "pct_of_sales", "value": c("G4")}, "costs_include_da": False,
        "depreciation": {"method": "same_as_base"}, "interest": {"method": "same_as_base"},
        "tax_rate": c("G10"),
        "cash": {"method": "pct_of_sales"}, "receivables": {"method": "pct_of_sales"},
        "inventory": {"method": "turnover", "value": c("G17")},
        "payables": {"method": "days_purchases", "value": c("G22")},
        "fixed_assets": {"method": "same_as_base"}, "plug": "equity",
    }
    y = project(base, drivers, 1)["years"][0]
    assert y["ebit"] == pytest.approx(c("E5") - c("E6"))      # EBIT uses projected GP less depreciation
    assert y["net_income"] == pytest.approx(c("E12"))
    for item, cell in (("cash", "E15"), ("receivables", "E16"), ("inventory", "E17"),
                       ("payables", "E22"), ("equity", "E29")):
        assert y[item] == pytest.approx(c(cell)), item
    assert y["managerial"]["wcr"] == pytest.approx(c("E34"))
    assert y["managerial"]["invested_capital"] == pytest.approx(c("E41"))
    assert y["managerial"]["capital_employed"] == pytest.approx(c("E45"))
    assert y["cash_flow"]["ties"]


def _at_values(ws, col):
    c = lambda r: _num(ws[f"{col}{r}"].value)  # noqa: E731
    ca, cl = c(15) + c(16) + c(17) + c(18), c(22) + c(23) + c(24)
    return {"revenue": c(3), "cost_of_goods_and_services_sold": c(4), "depreciation_expense": c(6),
            "operating_income_loss": c(7), "interest_expense": c(8),
            "cash_and_marketable_securities": c(15), "trade_receivables": c(16), "inventories": c(17),
            "current_assets_total": ca, "assets": ca + c(20), "trade_payables": c(22),
            "short_term_debt": c(23), "current_liabilities_total": cl, "long_term_debt": c(26),
            "liabilities": cl + c(26) + c(27)}


def test_772_operating_and_financial_ratios():
    ws = _book(CASES.get("ratios_operating_financial")).active
    cfg = load_classification({"marginal_tax_rate": 0.5})
    for col, rcol, pcol in (("C", "H", "B"), ("D", "I", "C")):
        r = managerial_ratios(_at_values(ws, col), _at_values(ws, pcol), cfg)
        e = lambda row: _num(ws[f"{rcol}{row}"].value)  # noqa: E731
        assert r["nsf"] == pytest.approx(e(3))
        assert r["nlf"] == pytest.approx(e(4))
        assert r["liquidity_ratio"] == pytest.approx(e(5))
        assert r["wcr_to_sales"] == pytest.approx(e(6))
        assert r["collection_period_days"] == pytest.approx(e(7))
        assert r["days_inventory"] == pytest.approx(e(8))
        assert r["inventory_turnover"] == pytest.approx(e(9))
        assert r["payment_period_days"] == pytest.approx(e(10))


def test_772_mbs_free_cash_flow():
    ws = _book(CASES.get("mbs_fcf")).active

    def vals(col):
        c = lambda r: _num(ws[f"{col}{r}"].value)  # noqa: E731
        # MBS layout: cash, WCR (A/R, inventory, prepaid, -A/P, -accrued), fixed assets, STD, LTD, NW
        ca = c(15) + c(17) + c(18) + c(19)
        cl = -c(20) - c(21) + c(24)
        return {"operating_income_loss": c(7), "depreciation_expense": c(6),
                "cash_and_marketable_securities": c(15), "current_assets_total": ca,
                "assets": ca + c(22), "short_term_debt": c(24), "current_liabilities_total": cl,
                "long_term_debt": c(25), "liabilities": cl + c(25)}

    cfg = load_classification({"marginal_tax_rate": 0.5})
    for col, prev, out in (("C", "B", "C"), ("D", "C", "D")):
        f = mbs_free_cash_flow(vals(col), vals(prev), cfg)
        assert f["noplat"] == pytest.approx(_num(ws[f"{out}30"].value))
        assert f["change_in_wcr"] == pytest.approx(_num(ws[f"{out}32"].value))
        assert f["capex_from_balance_sheet"] == pytest.approx(_num(ws[f"{out}33"].value))
        assert f["fcf"] == pytest.approx(_num(ws[f"{out}34"].value))


# ---------------------------------------------------- 733: reformulated

def test_733_reformulated_ratio_definitions():
    """Feed the template's NOPAT, NI, NOA, NNO and CSE through our ratio code.

    Our code computes NOA from totals, so the inputs are arranged so that
    assets = NOA + financial assets and liabilities = financial obligations."""
    ws = _book(CASES.get("reformulated_ratios"))["Reformulated ratios"]
    t = _num(ws["C24"].value)
    cfg = load_classification({"marginal_tax_rate": t})

    def vals(col, with_flows=True):
        noa, nno = _num(ws[f"{col}49"].value), _num(ws[f"{col}52"].value)
        fa = 1_000_000.0                      # any financial asset level; NNO is what matters
        v = {"assets": noa + fa, "cash_and_marketable_securities": fa,
             "long_term_debt": nno + fa, "liabilities": nno + fa}
        if with_flows:
            nopat, ni = _num(ws[f"{col}18"].value), _num(ws[f"{col}23"].value)
            v.update(revenue=_num(ws[f"{col}6"].value), profit_loss=ni,
                     interest_expense=(nopat - ni) / (1 - t))
        return v

    cols = "BCDEF"
    for i in range(1, len(cols)):
        col, prev = cols[i], cols[i - 1]
        r = reformulated_ratios(vals(col), vals(prev, with_flows=False), cfg)
        e = lambda row: _num(ws[f"{col}{row}"].value)  # noqa: E731
        assert r["nopm"] == pytest.approx(e(65))
        assert r["beg"]["noat"] == pytest.approx(e(64))
        assert r["beg"]["rnoa"] == pytest.approx(e(66))
        assert r["beg"]["roce"] == pytest.approx(e(67))
        assert r["beg"]["flev"] == pytest.approx(e(68))
        assert r["avg"]["noat"] == pytest.approx(e(71))
        assert r["avg"]["rnoa"] == pytest.approx(e(73))
        assert r["avg"]["roce"] == pytest.approx(e(74))
        assert r["avg"]["flev"] == pytest.approx(e(75))
        assert r["fcf"] == pytest.approx(e(55))


# ------------------------------------------- 789: Firm DCF projection rows

def _firm_dcf_inputs(wb):
    ir = wb["Inputs_Results"]
    c = lambda a: _num(ir[a].value)  # noqa: E731
    dcf = wb["Firm DCF"]
    n_tv = int(c("F5"))
    cols = [chr(ord("D") + i) for i in range(n_tv + 1)]
    adj = lambda row: [_num(dcf[f"{col}{row}"].value) for col in cols]  # noqa: E731
    cost_adj = adj(8)
    base = {"revenue": c("M3"), "cogs": c("M4"), "sga": c("M5"), "other_opex": c("M6") + c("M8"),
            "rnd": c("M7"), "depreciation": c("M10"), "amortization": c("M11"),
            "interest_expense": c("M13")}
    drivers = {
        "revenue": {"method": "fade", "g0": c("F10"), "g_terminal": c("F11"), "fade_years": c("F5"),
                    "adjust": adj(7)},    # the template's per-year growth adjustments (a fade by default)
        "cogs": {"method": "pct_of_sales", "value": c("N4"), "adjust": [a + b for a, b in zip(cost_adj, adj(16))]},
        "sga": {"method": "pct_of_sales", "value": c("N5"), "adjust": [a + b for a, b in zip(cost_adj, adj(21))]},
        "other_opex": {"method": "pct_of_sales", "value": c("N6") + c("N8"), "adjust": cost_adj},
        "rnd": {"method": "pct_of_sales", "value": c("N7"), "adjust": [a + b for a, b in zip(cost_adj, adj(28))]},
        "depreciation": {"method": "pct_of_sales", "value": c("N10"), "adjust": [a + b for a, b in zip(cost_adj, adj(35))]},
        "amortization": {"method": "pct_of_sales", "value": c("N11"), "adjust": [a + b for a, b in zip(cost_adj, adj(37))]},
        "capex": {"method": "pct_of_sales", "value": c("N19"), "adjust": [a + b for a, b in zip(cost_adj, adj(56))]},
        "nwc": {"method": "incremental", "ratio": c("V4")},
        "interest": {"method": "pct_of_sales", "value": _num(dcf["C41"].value)},
        "tax_rate": c("F4"),
        "amortization_tax_deductible": c("V9"),
        "costs_include_da": True,
    }
    return base, drivers, cols, dcf


@pytest.mark.parametrize("case", sorted(FIRM_DCF_CASES))
def test_789_firm_dcf_projection_rows(case):
    wb = _book(FIRM_DCF_CASES[case])
    base, drivers, cols, dcf = _firm_dcf_inputs(wb)
    if any(_num(dcf[f"{c}14"].value) for c in cols):
        pytest.skip("year-specific revenue overrides not modeled")
    years = project(base, drivers, len(cols))["years"]
    rows = {"revenue": 13, "ebitda": 31, "depreciation": 34, "ebit": 38, "capex": 55}
    for y, col in zip(years, cols):
        for item, row in rows.items():
            assert y[item] == pytest.approx(_num(dcf[f"{col}{row}"].value), rel=1e-9, abs=1e-6), (case, col, item)
        assert y["free_cash_flow"]["change_in_nwc"] == pytest.approx(_num(dcf[f"{col}57"].value), rel=1e-9, abs=1e-6)
        assert y["free_cash_flow"]["fcf"] == pytest.approx(_num(dcf[f"{col}61"].value), rel=1e-9, abs=1e-6), (case, col)
