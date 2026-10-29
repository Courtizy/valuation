"""Standalone DCF model and the core math under it. Run: pytest tests/test_L2_dcf.py"""
from __future__ import annotations

import json

import pytest

from valuation._core.cost_of_capital import discount_rates, relever_beta, unlever_beta, wacc
from valuation._core.dcf import solve, terminal_value, value_firm
from valuation._core.projection import project
from valuation._core.shares import treasury_stock_method
from valuation.L2_models.base import get_model
from valuation.L2_models.dcf import AssumptionError
from valuation.L2_models.reconcile import build_comparison
from valuation.L3_app.demo import write_demo

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


def test_missing_inputs_fall_back_or_are_named(detail):
    detail = {**detail, "market": None, "risk_free": None}  # showcase mode: no market block
    # no beta anywhere: the sector's illustrative beta from company detail, said so in the sources
    r = get_model("dcf").run(detail, assumptions(cost_of_capital={"beta": None})).to_dict()
    assert r["details"]["rates"]["beta_levered_observed"] == detail["sector_beta"]["value"]
    assert "illustrative" in r["assumptions_used"]["sources"]["beta"]
    # no price (showcase mode): book D/E, and implied mode falls back to forecast
    r = get_model("dcf").run(detail, {**assumptions(), "mode": "implied", "market": {"basic_shares": 1e8}}).to_dict()
    assert r["details"]["implied_growth"] is None and any("model's own equity value" in n for n in r["notes"])
    with pytest.raises(AssumptionError, match="risk_free"):            # no FRED rate either: named input
        get_model("dcf").run(detail, assumptions(cost_of_capital={"risk_free": None}))
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


def test_default_case_values_a_company_without_a_dcf_json(detail):
    from valuation.L2_models.dcf import default_assumptions
    d = {**detail, "market": None, "shares_outstanding": 330e6,
         "risk_free": {"value": 0.045, "date": "2026-09-30", "series": "DGS10"}}
    a = default_assumptions(d)
    assert a["default_case"] and -0.05 <= a["forecast"]["revenue_growth"] <= 0.20
    r = get_model("dcf").run(d, a).to_dict()
    assert r["details"]["default_case"] and r["value_per_share"]["p50"] > 0
    assert r["assumptions_used"]["cost_of_capital"]["risk_free"] == 0.045
    assert r["notes"][0].startswith("default assumptions")
    assert "illustrative" in r["assumptions_used"]["sources"]["beta"]


def test_default_case_uses_damodaran_beta_and_erp(detail):
    """Showcase mode with Damodaran's data in company detail: the industry's unlevered beta is
    relevered at the company's own (solved) D/E, and the implied ERP replaces the flat 5%."""
    from valuation.L2_models.dcf import default_assumptions
    d = {**detail, "market": None, "shares_outstanding": 330e6,
         "risk_free": {"value": 0.045, "date": "2026-09-30", "series": "DGS10"},
         "sector_beta": {"value": 0.58, "unlevered": True, "industry": "Beverage (Soft)",
                         "basis": "Damodaran US industry unlevered beta, cash-corrected: Beverage (Soft) (27 firms, January 2026)"},
         "equity_risk_premium": {"value": 0.0423, "year": 2025, "basis": "Damodaran implied ERP (FCFE), start of 2026"}}
    r = get_model("dcf").run(d, default_assumptions(d)).to_dict()
    rates, src = r["details"]["rates"], r["assumptions_used"]["sources"]
    assert rates["beta_unlevered"] == A(0.58)
    assert rates["beta_levered_observed"] > 0.58 if rates["current_debt_to_equity"] > 0 else True   # levered at its own D/E
    assert r["assumptions_used"]["cost_of_capital"]["equity_risk_premium"] == 0.0423
    assert "Damodaran" in src["beta"] and "Damodaran" in src["equity_risk_premium"]


def test_default_case_handles_negative_book_equity(detail):
    """Dell-like: buybacks leave book equity negative, and there's no price in showcase mode."""
    from copy import deepcopy
    from valuation.L2_models.dcf import default_assumptions
    d = deepcopy({**detail, "market": None, "shares_outstanding": 330e6,
                  "risk_free": {"value": 0.045, "date": "2026-09-30", "series": "DGS10"}})
    for view in ("annual", "ttm", "quarterly"):
        for p in d["views"][view]:
            p["values"]["all_equity_balance"] = -2.0e9
    r = get_model("dcf").run(d, default_assumptions(d)).to_dict()
    rates = r["details"]["rates"]
    assert rates["debt_to_equity_basis"] == "model equity value" and 0 < rates["current_debt_to_equity"] < 4
    eq = r["details"]["bridge"]["equity_value"]
    assert rates["current_debt_to_equity"] == A(r["details"]["bridge"]["debt"] / eq, rel=1e-3)   # converged


# ---------------------------------------------------------------- Monte Carlo

def test_simulation_is_seeded_and_summarized(detail):
    a = assumptions(simulation={"runs": 800, "seed": 11})
    r1 = get_model("dcf").run(detail, a).to_dict()
    r2 = get_model("dcf").run(detail, assumptions(simulation={"runs": 800, "seed": 11})).to_dict()
    s = r1["details"]["simulation"]
    assert s == r2["details"]["simulation"]                                   # same seed, same numbers
    ps = s["per_share"]
    assert ps["p5"] < ps["p10"] < ps["p50"] < ps["p90"] < ps["p95"] and s["middle_90"] == [ps["p5"], ps["p95"]]
    h = s["histogram"]
    assert sum(h["counts"]) + h["below"] + h["above"] == s["runs_used"] <= 800
    assert r1["value_per_share"]["p10"] == ps["p10"] and r1["value_per_share"]["p90"] == ps["p90"]
    assert r1["value_per_share"]["p50"] == r1["details"]["scenarios"]["expected"]  # base stays the course case
    assert 0 < s["terminal_value_share"] < 1
    other = get_model("dcf").run(detail, assumptions(simulation={"runs": 800, "seed": 12})).to_dict()
    assert other["details"]["simulation"]["per_share"] != ps


def test_simulation_ranges_can_be_set_and_bad_runs_dropped(detail):
    tight = {"runs": 300, "growth": 0.05, "wacc": {"dist": "uniform", "low": 0.08, "high": 0.081},
             "terminal_growth": {"dist": "triangular", "low": 0.02, "mode": 0.03, "high": 0.035}}
    s = get_model("dcf").run(detail, assumptions(simulation=tight)).to_dict()["details"]["simulation"]
    assert s["inputs"]["growth"] == 0.05 and s["per_share"]["p95"] - s["per_share"]["p5"] < 30
    wild = {"runs": 300, "terminal_growth": {"dist": "uniform", "low": 0.0, "high": 0.2}}
    s = get_model("dcf").run(detail, assumptions(simulation=wild)).to_dict()["details"]["simulation"]
    assert s["runs_used"] < 300                                                # terminal growth above WACC dropped


def test_simulation_draws_revenue_from_the_calibrated_table(detail):
    from valuation.L2_models.dcf.revenue_range import load_table, multipliers
    t = load_table()
    assert t is not None and t["_horizons"] == [1, 2, 3, 4, 5]
    s = get_model("dcf").run(detail, assumptions(simulation={"runs": 400, "seed": 3})).to_dict()["details"]["simulation"]
    assert s["inputs"]["revenue"]["dist"] == "calibrated" and s["revenue_range"]["scale"] >= t["scale"]["floor"]
    b80, b90 = s["revenue_range"]["bands"]["80"], s["revenue_range"]["bands"]["90"]
    for lo, hi in zip(b80, b90):
        assert hi["low"] < lo["low"] < 1 < lo["high"] < hi["high"]               # 90% wraps 80%, both straddle the base
    assert b90[-1]["high"] - b90[-1]["low"] > b90[0]["high"] - b90[0]["low"]    # wider further out
    assert s["middle_80"] == [s["per_share"]["p10"], s["per_share"]["p90"]]
    m = multipliers(t, 0.5, 0.2, 12)
    assert len(m) == 12 and m[5:] == [m[4]] * 7                                   # years past 5 hold year 5's level


def test_triangular_growth_is_kept_when_asked(detail):
    s = get_model("dcf").run(detail, assumptions(simulation={"runs": 300, "revenue_errors": False})).to_dict()["details"]["simulation"]
    assert s["inputs"]["growth"]["dist"] == "triangular" and s["revenue_range"] is None


def test_unit_revenue_shock_changes_nothing(detail):
    m = get_model("dcf")
    p = m.prepare(detail, assumptions())
    assert m.value(p, revenue_shock=[1.0] * p["years"])["value_per_share"] == A(m.value(p)["value_per_share"])


def test_blend_path_is_the_geometric_mean_then_the_fade():
    from valuation._core.projection import revenue_path
    d = {"method": "blend", "g0": 0.15, "g_terminal": 0.025, "fade_years": 10, "sector_growth": 0.03, "blend_years": 5}
    blend, fade = revenue_path(d, 100.0, 10), revenue_path({**d, "method": "fade"}, 100.0, 10)
    for t in range(5):
        assert blend[t] == A((100.0 * fade[t] * 100.0 * 1.03 ** (t + 1)) ** (1 / 3))
    for t in range(5, 10):
        assert blend[t] / blend[t - 1] == A(fade[t] / fade[t - 1])          # then the fade's own rates
    assert blend[4] < fade[4]                                                # a fast grower is pulled in
    no_sector = revenue_path({**d, "sector_growth": None}, 100.0, 3)
    assert no_sector[0] == A((100.0 * fade[0] ** 2) ** (1 / 3))


def test_default_case_uses_the_blend_and_reports_momentum(detail):
    from valuation.L2_models.dcf import default_assumptions
    a = default_assumptions(detail)
    assert a["forecast"]["revenue_method"] == "blend"
    r = get_model("dcf").run(detail, {**a, "simulation": {"runs": 200}}).to_dict()
    assert r["details"]["drivers"]["revenue"]["method"] == "blend"
    assert r["details"]["momentum"]["value_per_share"] > 0 and r["details"]["yardstick"]["flat_revenue_per_share"] > 0
    v = r["value_per_share"]
    assert v["p5"] < v["p10"] < v["p90"] < v["p95"]
    tested = r["details"]["simulation"]["revenue_range"]["tested"]["levels"]
    assert 0.85 < tested["90"]["3"]["coverage"] < 0.97                      # the study's out-of-sample hit rate
    assert get_model("dcf").run(detail, assumptions()).to_dict()["details"]["momentum"] is None   # a dcf.json keeps the fade


def test_sector_growth_lookup_takes_the_latest_year_up_to_the_base():
    from valuation.L2_models.dcf.revenue_range import division, sector_growth
    assert division("3571") == "Manufacturing" and division("6021") is None and division(None) is None
    s = sector_growth("3571", 2019)
    assert s["division"] == "Manufacturing" and s["year"] <= 2019 and s["n"] >= 5
    assert sector_growth("3571", 1990) is None


def test_core_simulation_helpers():
    from valuation._core.simulation import histogram, percentile, rng, sample, summarize
    xs = sample({"dist": "triangular", "low": 0, "mode": 1, "high": 2}, 1000, rng(3))
    assert min(xs) >= 0 and max(xs) <= 2 and abs(summarize(xs)["p50"] - 1) < 0.1
    assert percentile([1, 2, 3, 4], 50) == 2.5 and sample(4.0, 3, rng(1)) == [4.0, 4.0, 4.0]
    assert sum(histogram(xs, bins=10, trim=0)["counts"]) == 1000
    with pytest.raises(ValueError):
        sample({"dist": "lognormal"}, 1, rng(1))
