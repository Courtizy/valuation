"""Three-statement projection engine. Run: pytest tests/test_core_projection.py"""
from __future__ import annotations

import pytest

from core.projection import ProjectionError, base_from_detail, project, revenue_path

A = pytest.approx

BASE = dict(revenue=1000, cogs=600, sga=150, rnd=50, depreciation=40, amortization=10,
            interest_expense=20, interest_income=2, income_taxes=40, net_income=120,
            cash=100, receivables=150, inventory=120, other_current_assets=30, fixed_assets=500,
            payables=90, accrued=60, short_term_debt=50, long_term_debt=250,
            other_lt_liabilities=40, equity=410, capex=60)


def test_revenue_fade_matches_linear_formula():
    path = revenue_path({"method": "fade", "g0": 0.2, "g_terminal": 0.04, "fade_years": 10}, 100, 3)
    assert path == A([120, 120 * 1.184, 120 * 1.184 * 1.168])


def test_revenue_fade_adjust_overrides_and_growth_extends():
    assert revenue_path({"method": "fade", "g0": 0.05, "adjust": [0, 0]}, 100, 3) == A([105, 110.25, 115.7625])
    assert revenue_path({"method": "growth", "rates": [0.1]}, 100, 2) == A([110, 121])
    with pytest.raises(ProjectionError):
        revenue_path({"method": "values", "values": [1]}, 100, 2)


def test_null_driver_value_uses_base_ratio():
    y = project(BASE, {"revenue": {"method": "growth", "rates": [0.1]},
                       "cogs": {"method": "pct_of_sales", "value": None}}, 1)["years"][0]
    assert y["cogs"] == A(0.6 * 1100)


@pytest.mark.parametrize("plug", ["equity", "cash", "revolver"])
def test_statements_balance_and_cash_flow_ties(plug):
    drivers = {
        "revenue": {"method": "growth", "rates": [0.08, 0.06, 0.05]},
        "cogs": {"method": "pct_of_sales"}, "sga": {"method": "pct_of_sales"},
        "rnd": {"method": "pct_of_sales"}, "depreciation": {"method": "pct_of_fixed_assets"},
        "amortization": {"method": "same_as_base"}, "capex": {"method": "pct_of_sales", "value": 0.07},
        "receivables": {"method": "days", "value": 55}, "inventory": {"method": "turnover", "value": 5},
        "payables": {"method": "days_purchases", "value": 50}, "cash": {"method": "pct_of_sales"},
        "interest": {"method": "rate_on_debt", "rate": 0.06, "basis": "average", "cash_rate": 0.02},
        "tax_rate": 0.25, "dividends": {"payout": 0.3}, "plug": plug,
    }
    for y in project(BASE, drivers, 3)["years"]:
        assert y["balance_check"] == A(0, abs=1e-6)
        assert y["cash_flow"]["ties"]
        assert y["income_taxes"] == A(0.25 * y["ebt"])
        if plug != "equity":
            assert y["cash_flow"]["equity_issued_or_plug"] == A(0, abs=1e-6)


def test_average_interest_converges_to_fixed_point():
    drivers = {"revenue": {"method": "growth", "rates": [0.1]}, "cogs": {"method": "pct_of_sales"},
               "sga": {"method": "pct_of_sales"}, "rnd": {"method": "pct_of_sales"},
               "capex": {"method": "pct_of_sales", "value": 0.3}, "tax_rate": 0.25, "plug": "revolver",
               "cash": {"method": "same_as_base"},
               "interest": {"method": "rate_on_debt", "rate": 0.1, "basis": "average"}}
    y = project(BASE, drivers, 1)["years"][0]
    avg_debt = (300 + y["short_term_debt"] + y["long_term_debt"] + y["revolver"]) / 2
    assert y["revolver"] > 0
    assert y["interest_expense"] == A(0.1 * avg_debt, rel=1e-8)


def test_incremental_nwc_and_fcf_formula():
    drivers = {"revenue": {"method": "growth", "rates": [0.1, 0.1]},
               "cogs": {"method": "pct_of_sales"}, "sga": {"method": "pct_of_sales"},
               "rnd": {"method": "pct_of_sales"}, "depreciation": {"method": "pct_of_sales"},
               "amortization": {"method": "pct_of_sales"}, "capex": {"method": "pct_of_sales"},
               "nwc": {"method": "incremental", "ratio": 0.2}, "tax_rate": 0.3,
               "amortization_tax_deductible": 0.5, "costs_include_da": True}
    years = project(BASE, drivers, 2)["years"]
    y1 = years[0]
    assert y1["free_cash_flow"]["change_in_nwc"] == A(0.2 * 100)
    assert y1["ebitda"] == A(1100 - 1100 * 0.8 + 1100 * 0.05)
    expected = (y1["ebitda"] * 0.7 + y1["depreciation"] * 0.3 + y1["amortization"] * 0.3 * 0.5
                - y1["capex"] - 20)
    assert y1["free_cash_flow"]["fcf"] == A(expected)
    assert years[1]["balance_check"] == A(0, abs=1e-6)


def test_costs_exclude_da_switch():
    d = {"revenue": {"method": "growth", "rates": [0]}, "cogs": {"method": "pct_of_sales"},
         "sga": {"method": "pct_of_sales"}, "rnd": {"method": "pct_of_sales"},
         "costs_include_da": False}
    y = project(BASE, d, 1)["years"][0]
    assert y["ebit"] == A(1000 - 800 - 50) and y["ebitda"] == A(200)


def test_fixed_asset_roll_forward():
    d = {"revenue": {"method": "growth", "rates": [0]}, "capex": {"method": "pct_of_sales", "value": 0.1}}
    y = project(BASE, d, 1)["years"][0]
    assert y["fixed_assets"] == A(500 + 100 - 40 - 10)


def test_requires_revenue():
    with pytest.raises(ProjectionError):
        project(BASE, {}, 1)
    with pytest.raises(ProjectionError):
        project({**BASE, "revenue": 0}, {"revenue": {"method": "growth", "rates": [0]}}, 1)


def test_base_from_detail_uses_totals():
    v = {"revenue": 100, "assets": 500, "current_assets_total": 200, "cash_and_marketable_securities": 50,
         "trade_receivables": 60, "inventories": 40, "current_liabilities_total": 120, "trade_payables": 30,
         "short_term_debt": 20, "long_term_debt": 150, "liabilities": 330,
         "depreciation_amortization_cf": 12, "amortization_of_intangibles": 2}
    b = base_from_detail(v)
    assert b["other_current_assets"] == 50 and b["accrued"] == 70
    assert b["fixed_assets"] == 300 and b["other_lt_liabilities"] == 60
    assert b["equity"] == 170 and b["depreciation"] == 10 and b["amortization"] == 2
    assets = b["cash"] + b["receivables"] + b["inventory"] + b["other_current_assets"] + b["fixed_assets"]
    liabs = b["payables"] + b["accrued"] + b["short_term_debt"] + b["long_term_debt"] + b["other_lt_liabilities"]
    assert assets == liabs + b["equity"]
