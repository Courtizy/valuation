"""The site's JavaScript projection must match core/projection.py exactly.

Runs site/assets/projection.js under Node on the same cases. Skips if Node
isn't installed. Run: pytest tests/test_site_projection.py
"""
from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path

import pytest

from core.projection import base_from_detail, project

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "site" / "assets" / "projection.js"

BASE = dict(revenue=1000, cogs=600, sga=150, rnd=50, depreciation=40, amortization=10,
            interest_expense=20, interest_income=2, income_taxes=40, net_income=120,
            cash=100, receivables=150, inventory=120, other_current_assets=30, fixed_assets=500,
            payables=90, accrued=60, short_term_debt=50, long_term_debt=250,
            other_lt_liabilities=40, equity=410, capex=60)

CASES = {
    "course_dcf_style": {
        "revenue": {"method": "fade", "g0": 0.2, "g_terminal": 0.04, "fade_years": 10},
        "cogs": {"method": "pct_of_sales", "value": None, "adjust": [0, 0.01, 0.02]},
        "sga": {"method": "pct_of_sales"}, "rnd": {"method": "pct_of_sales"},
        "depreciation": {"method": "pct_of_sales"}, "amortization": {"method": "pct_of_sales"},
        "capex": {"method": "pct_of_sales"}, "nwc": {"method": "incremental", "ratio": 0.15},
        "interest": {"method": "pct_of_sales"}, "tax_rate": 0.23,
        "amortization_tax_deductible": 0.5, "costs_include_da": True,
    },
    "pro_forma_style": {
        "revenue": {"method": "values", "values": [1100, 1200, 1250]},
        "cogs": {"method": "pct_of_sales", "value": 0.62}, "costs_include_da": False,
        "depreciation": {"method": "same_as_base"}, "interest": {"method": "same_as_base"},
        "tax_rate": [0.3, 0.28], "cash": {"method": "pct_of_sales"},
        "receivables": {"method": "days", "value": 60}, "inventory": {"method": "turnover", "value": 5},
        "payables": {"method": "days_purchases", "value": 45},
        "fixed_assets": {"method": "same_as_base"}, "plug": "equity",
    },
    "revolver_average_interest": {
        "revenue": {"method": "growth", "rates": [0.1, 0.05]},
        "cogs": {"method": "pct_of_sales"}, "sga": {"method": "pct_of_sales"}, "rnd": {"method": "pct_of_sales"},
        "depreciation": {"method": "pct_of_fixed_assets"}, "capex": {"method": "pct_of_sales", "value": 0.25},
        "receivables": {"method": "pct_of_sales"}, "inventory": {"method": "days", "value": 70},
        "payables": {"method": "pct_of_sales"}, "cash": {"method": "pct_of_sales"},
        "interest": {"method": "rate_on_debt", "rate": 0.07, "basis": "average", "cash_rate": 0.01},
        "long_term_debt": {"method": "schedule", "values": [200, 150]},
        "tax_rate": 0.25, "dividends": {"payout": 0.4}, "plug": "revolver",
    },
    "cash_plug_with_floor": {
        "revenue": {"method": "fade", "g0": 0.05, "adjust": [0, 0, 0]},
        "cogs": {"method": "pct_of_sales"}, "sga": {"method": "pct_of_sales"},
        "cash": {"method": "min", "value": 80}, "plug": "cash", "nonrecurring": [5, 0],
        "provisions": [1, 2, 3],
    },
}


def _node():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    return node


def _run_js(payload: dict) -> dict:
    script = (
        f"import {{ project, baseFromDetail }} from {json.dumps(JS.as_uri())};\n"
        "let s = ''; process.stdin.on('data', d => s += d); process.stdin.on('end', () => {\n"
        "  const p = JSON.parse(s); const out = {};\n"
        "  for (const [k, c] of Object.entries(p.cases)) out[k] = project(p.base, c.drivers, c.years);\n"
        "  out.__detail = baseFromDetail(p.detail);\n"
        "  process.stdout.write(JSON.stringify(out));\n"
        "});\n"
    )
    r = subprocess.run([_node(), "--input-type=module", "-e", script], input=json.dumps(payload),
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _same(py, js, path=""):
    if isinstance(py, dict):
        assert isinstance(js, dict), path
        missing = set(py) ^ set(js)
        assert not missing, f"{path}: keys differ {sorted(missing)}"
        for k in py:
            _same(py[k], js[k], f"{path}.{k}")
    elif isinstance(py, list):
        assert len(py) == len(js), path
        for i, (a, b) in enumerate(zip(py, js)):
            _same(a, b, f"{path}[{i}]")
    elif isinstance(py, bool) or py is None:
        assert py == js, f"{path}: {py!r} != {js!r}"
    elif isinstance(py, (int, float)):
        assert math.isclose(py, js, rel_tol=1e-12, abs_tol=1e-9), f"{path}: {py} != {js}"
    else:
        assert py == js, path


DETAIL = {"revenue": 100, "assets": 500, "current_assets_total": 200, "cash_and_marketable_securities": 50,
          "trade_receivables": 60, "inventories": 40, "current_liabilities_total": 120, "trade_payables": 30,
          "short_term_debt": 20, "long_term_debt": 150, "liabilities_and_equity": 500, "all_equity_balance": 160,
          "minority_interest_balance": 10, "depreciation_amortization_cf": 12, "amortization_of_intangibles": 2,
          "net_income": 9}


def test_js_projection_matches_python():
    years = {"course_dcf_style": 11, "pro_forma_style": 3, "revolver_average_interest": 2, "cash_plug_with_floor": 3}
    js = _run_js({"base": BASE, "detail": DETAIL,
                  "cases": {k: {"drivers": d, "years": years[k]} for k, d in CASES.items()}})
    for name, drivers in CASES.items():
        py = project(BASE, drivers, years[name])
        _same(py["years"], js[name]["years"], name)
        _same(py["base"], js[name]["base"], name + ".base")
    py_base = {k: v for k, v in base_from_detail(DETAIL).items() if v is not None}
    js_base = {k: v for k, v in js["__detail"].items() if v is not None}
    _same(py_base, js_base, "base_from_detail")
