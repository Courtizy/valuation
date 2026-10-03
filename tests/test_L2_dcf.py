"""Standalone DCF model and the core math under it. Run: pytest tests/test_L2_dcf.py"""
from __future__ import annotations

import json

import pytest

from core.cost_of_capital import discount_rates, relever_beta, unlever_beta, wacc
from core.dcf import solve, terminal_value, value_firm
from core.projection import project
from core.shares import treasury_stock_method
from L2_models.base import get_model
from L2_models.dcf import AssumptionError
from L2_models.reconcile import build_comparison
from L3_app.demo import write_demo

A = pytest.approx


@pytest.fixture
def detail(tmp_path):
    out = write_demo(tmp_path)
    return json.loads((out / "company_detail.json").read_text())


def assumptions(**over):
    a = {
        "mode": "forecast",
        "market": {"price": 40.0, "basic_shares": 100e6},
        "forecast": {"years_to_terminal": 10, "revenue_growth": 0.08, "terminal_growth": 0.03, "tax_rate": 0.21},
        "cost_of_capital": {"risk_free": 0.04, "risk_free_terminal": 0.05, "equity_risk_premium": 0.05,
                            "beta": 1.1, "pre_tax_cost_of_debt": 0.06},
    }
    for k, v in over.items():
        a[k] = {**a.get(k, {}), **v} if isinstance(v, dict) else v
    return a


# ---------------------------------------------------------------- core math

def test_beta_round_trip_and_wacc():
    bu = unlever_beta(1.2, 0.5, 0.25)
    assert relever_beta(bu, 0.5, 0.25) == A(1.2)
    assert wacc(0.10, 0.06, 0.25, 1.0) == A(0.5 * 0.10 + 0.5 * 0.045)


def test_terminal_rates_default_to_current():
    r = discount_rates(risk_free=0.04, pre_tax_cost_of_debt=0.06, beta=1.0, equity_risk_premium=0.05,
                       tax_rate=0.2, current_debt_to_equity=0.25)
    assert r["wacc_terminal"] == A(r["wacc"]) and r["target_debt_to_equity"] == 0.25
    r2 = discount_rates(risk_free=0.04, pre_tax_cost_of_debt=0.06, beta=1.0, equity_risk_premium=0.05,
                        tax_rate=0.2, current_debt_to_equity=0.25, risk_free_terminal=0.06)
    assert r2["pre_tax_cost_of_debt_terminal"] == A(0.08)        # spread kept
    assert r2["wacc_terminal"] > r2["wacc"]


def test_treasury_stock_method():
    t = treasury_stock_method(100, 50, [(10, 20), (5, 60)])     # second tranche out of the money
    assert t["in_the_money_options"] == 10 and t["exercise_proceeds"] == 200
    assert t["diluted"] == A(100 + 10 - 200 / 50)
    with pytest.raises(ValueError):
        treasury_stock_method(100, 0)


def _proj():
    base = dict(revenue=100, cogs=60, sga=20, depreciation=5, fixed_assets=50, equity=50)
    d = {"revenue": {"method": "growth", "rates": [0.0]}, "cogs": {"method": "pct_of_sales"},
         "sga": {"method": "pct_of_sales"}, "depreciation": {"method": "pct_of_sales"},
         "capex": {"method": "pct_of_sales", "value": 0.05}, "nwc": {"method": "incremental", "ratio": 0.1},
         "tax_rate": 0.25}
    return project(base, d, 3)


def test_value_firm_conventions_and_bridge():
    p = _proj()
    kw = dict(wacc=0.10, wacc_terminal=0.10, terminal_growth=0.0, tax_rate=0.25, capex_to_sales_terminal=0.05,
              nwc_to_sales_change=0.1, net_debt=20, shares=10)
    v = value_firm(p, **kw)
    fcf = p["years"][0]["free_cash_flow"]["fcf"]                  # flat sales: every year the same
    assert fcf == A(25 * 0.75 + 5 * 0.25 - 5)
    tv = terminal_value(p["years"][-1], terminal_growth=0.0, wacc_terminal=0.10, tax_rate=0.25,
                        capex_to_sales=0.05, nwc_to_sales_change=0.1)["terminal_value"]
    assert v["enterprise_value"] == A(fcf * (1 + 1 / 1.1 + 1 / 1.21) + tv / 1.21)
    assert v["equity_value"] == A(v["enterprise_value"] - 20)
    assert v["value_per_share"] == A(v["equity_value"] / 10)
    eoy = value_firm(p, convention="end_of_year", **kw)
    assert eoy["enterprise_value"] == A(v["enterprise_value"] / 1.1)
    with pytest.raises(ValueError):
        value_firm(p, convention="weird", **kw)
    with pytest.raises(ValueError):
        value_firm(p, **{**kw, "terminal_growth": 0.12})


def test_solve_needs_a_bracket():
    assert solve(lambda x: x * x, 4, 0, 5) == A(2, abs=1e-8)
    with pytest.raises(ValueError):
        solve(lambda x: x * x, -1, 0, 5)


# ---------------------------------------------------------------- the model

def test_forecast_mode_result(detail):
    r = get_model("dcf").run(detail, assumptions())
    v, b = r.value_per_share, r.details["bridge"]
    assert v["p10"] < v["p50"] < v["p90"] and v["p50"] > 0
    assert b["equity_value"] == A(b["enterprise_value"] - b["net_debt"])
    assert b["value_per_share"] == A(v["p50"])
    assert b["net_debt"] == A(b["debt"] - b["cash"] * 0.5)        # half the cash is operating by default
    assert len(r.details["projection"]) == 11                      # closing year + 10
    used = r.assumptions_used
    assert used["forecast"]["revenue_growth"][0] == A(0.08)
    assert used["forecast"]["revenue_growth"][-1] == A(0.03)       # faded to terminal
    assert used["cost_of_capital"]["wacc_terminal"] > used["cost_of_capital"]["wacc"]
    json.dumps(r.to_dict())                                        # serializable


def test_base_ebit_ties_to_reported_operating_income(detail):
    m = get_model("dcf")
    p = m.prepare(detail, assumptions())
    rev = p["base"]["revenue"]
    base_ebit = rev - sum(p["drivers"][k]["value"] * rev for k in ("cogs", "sga", "rnd", "other_opex"))
    assert base_ebit == A(p["period"]["values"]["operating_income_loss"], rel=1e-9)


def test_implied_mode_matches_price(detail):
    r = get_model("dcf").run(detail, assumptions(mode="implied"))
    assert r.value_per_share["p50"] == A(40.0, rel=1e-8)
    assert r.details["implied_growth"] is not None
    assert any("implied near-term growth" in n for n in r.notes)


def test_options_dilute_through_tsm(detail):
    plain = get_model("dcf").run(detail, assumptions())
    diluted = get_model("dcf").run(detail, assumptions(market={"options": [[10e6, 20.0]]}))
    assert diluted.details["bridge"]["shares"] == A(100e6 + 10e6 - 10e6 * 20 / 40)
    assert diluted.value_per_share["p50"] < plain.value_per_share["p50"]


def test_missing_inputs_are_named(detail):
    with pytest.raises(AssumptionError, match="cost_of_capital.beta"):
        get_model("dcf").run(detail, assumptions(cost_of_capital={"beta": None}))
    with pytest.raises(AssumptionError, match="price"):
        get_model("dcf").run(detail, {**assumptions(), "market": {"basic_shares": 1e8}})
    with pytest.raises(AssumptionError):
        get_model("dcf").run({}, assumptions())


def test_result_reconciles(detail, tmp_path):
    r = get_model("dcf").run(detail, assumptions()).to_dict()
    p = tmp_path / "dcf.json"
    p.write_text(json.dumps(r))
    comp = build_comparison([p])
    assert comp["football_field"][0]["model"] == "dcf"


def test_longterm_investments_can_count_as_cash(detail):
    detail["views"]["annual"][-1]["values"]["longterm_investments"] = 1e9
    base = get_model("dcf").run(detail, assumptions())
    incl = get_model("dcf").run(detail, assumptions(bridge={"include_longterm_investments": True}))
    assert incl.details["bridge"]["cash"] == A(base.details["bridge"]["cash"] + 1e9)
    assert incl.details["bridge"]["net_debt"] == A(base.details["bridge"]["net_debt"] - 0.5e9)


def test_cost_of_debt_method_order(detail):
    m = get_model("dcf")
    v = detail["views"]["annual"][-1]["values"]
    a = assumptions(cost_of_capital={"pre_tax_cost_of_debt": None})
    p = m.prepare(detail, a)
    debt = v["short_term_debt"] + v["long_term_debt"]
    assert p["rates"]["cost_of_debt_method"] == "interest_over_debt"
    assert p["rates"]["pre_tax_cost_of_debt"] == A(v["interest_expense"] / debt)
    assert m.prepare(detail, assumptions())["rates"]["cost_of_debt_method"] == "given"
    no_int = json.loads(json.dumps(detail))
    no_int["views"]["annual"][-1]["values"].pop("interest_expense")
    with pytest.raises(AssumptionError, match="fallback"):
        m.prepare(no_int, a)
    fb = m.prepare(no_int, assumptions(cost_of_capital={"pre_tax_cost_of_debt": None,
                                                        "pre_tax_cost_of_debt_fallback": 0.058}))
    assert fb["rates"]["pre_tax_cost_of_debt"] == 0.058 and fb["rates"]["cost_of_debt_method"] == "fallback"


def test_sensitivity_grid_centre_is_base_and_slopes_right(detail):
    r = get_model("dcf").run(detail, assumptions())
    g = r.details["sensitivity"]
    assert len(g["values"]) == 5 and all(len(row) == 5 for row in g["values"])
    assert g["values"][2][2] == A(r.details["bridge"]["value_per_share"])
    assert g["values"][0][2] > g["values"][2][2] > g["values"][4][2]      # higher WACC, lower value
    assert g["values"][2][0] < g["values"][2][2] < g["values"][2][4]      # higher growth, higher value
