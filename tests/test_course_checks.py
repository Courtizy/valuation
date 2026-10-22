"""Course reasonableness checks across the models. Run: pytest tests/test_course_checks.py"""
from __future__ import annotations

import json
import math

import pytest

from valuation._core.checks import (exit_multiple_check, growth_band, lasting_cost_share, margin_vs_peers,
                                    synthetic_rating, terminal_checks)
from valuation._core.cost_of_capital import discount_rates
from valuation._core.dcf import terminal_value
from valuation._core.simulation import summarize
from valuation._core.stats import foster, ols
from valuation.L2_models.base import get_model
from valuation.L2_models.comps import synthesize
from valuation.L3_app.demo import write_demo

A = pytest.approx


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    out = write_demo(tmp_path_factory.mktemp("demo"))
    load = lambda n: json.loads((out / "model_results" / f"{n}.json").read_text())  # noqa: E731
    return {"out": out, "load": load, "detail": json.loads((out / "company_detail.json").read_text())}


def test_terminal_growth_bands_and_flags():
    assert growth_band(0.04) == "grows with the economy" and growth_band(0.03) == "slower than the economy"
    assert growth_band(0.02) == "flat real growth (in line with inflation)" and growth_band(-0.01) == "rapid decline"
    c = {x["key"]: x for x in terminal_checks(terminal_growth=0.05, last_year_growth=0.08, tv_share=0.85)}
    assert all(c[k]["status"] == "warning" for k in ("terminal_growth", "steady_state", "tv_share"))
    ok = terminal_checks(terminal_growth=0.03, last_year_growth=0.03, tv_share=0.6)
    assert all(x["status"] == "good" for x in ok)
    assert exit_multiple_check(15.0, 10.0)["status"] == "warning" and exit_multiple_check(11.0, 10.0)["status"] == "good"


def test_synthetic_rating_and_country_risk():
    assert synthetic_rating(100, 10)["rating"] == "AAA" and synthetic_rating(100, 42)["rating"] == "BB+"
    assert synthetic_rating(100, None) is None
    kw = dict(risk_free=0.04, pre_tax_cost_of_debt=0.06, beta=1.0, equity_risk_premium=0.05, tax_rate=0.21,
              current_debt_to_equity=0.0)
    base, crp = discount_rates(**kw), discount_rates(**kw, country_risk_premium=0.02)
    assert crp["cost_of_equity"] == A(base["cost_of_equity"] + 0.02) and crp["wacc_terminal"] == A(base["wacc_terminal"] + 0.02)


def test_finite_life_terminal_value():
    last = {"revenue": 100, "ebitda": 20}
    kw = dict(terminal_growth=0.02, wacc_terminal=0.10, tax_rate=0.0, capex_to_sales=0.0, nwc_to_sales_change=0.0)
    forever, ten = terminal_value(last, **kw)["terminal_value"], terminal_value(last, **kw, life_years=10)["terminal_value"]
    # growing annuity: sum of 20 x 1.02^k / 1.10^k for k = 1..10
    assert ten == A(sum(20 * 1.02 ** k / 1.10 ** k for k in range(1, 11)))
    assert ten < forever


def test_lasting_cost_share_and_margin_test():
    below = lasting_cost_share(roic_terminal=0.08, wacc_terminal=0.10, invested_capital=1000, annual_cost=100, tax_rate=0.2)
    assert below["share"] == A(0.02 * 1000 / 80) and below["range"] == A([0, 0.25])
    assert lasting_cost_share(roic_terminal=0.2, wacc_terminal=0.1, invested_capital=1000, annual_cost=100,
                              tax_rate=0.2)["share"] == 0
    assert margin_vs_peers(0.30, 0.27)["above"] is True


def test_ols_and_foster():
    f = ols([1, 2, 3, 4], [3, 5, 7, 9.01])
    assert f["slope"] == A(2.003) and f["r_squared"] > 0.99
    # a series that grows by 4 every quarter year on year: delta 4, phi 0
    q = [10, 20, 15, 30]
    for t in range(4, 16):
        q.append(q[t - 4] + 4)
    fit = foster(q)
    assert fit["delta"] == A(4, abs=1e-6) and fit["forecast"] == A([q[-4] + 4, q[-3] + 4, q[-2] + 4, q[-1] + 4])
    assert foster([1, 2, None, 3]) is None


def test_simulation_reports_the_mean_precision():
    s = summarize([1.0, 2.0, 3.0, 4.0])
    se = math.sqrt(sum((x - 2.5) ** 2 for x in (1, 2, 3, 4)) / 3) / 2
    assert s["standard_error"] == A(se) and s["mean_ci95"] == A([2.5 - 1.96 * se, 2.5 + 1.96 * se])


def test_dcf_carries_the_checks_tornado_and_seasonal_model(demo):
    d = demo["load"]("dcf")["details"]
    assert {c["key"] for c in d["checks"]} == {"terminal_growth", "steady_state", "tv_share"}
    swings = [b["swing"] for b in d["tornado"]["bars"]]
    assert swings == sorted(swings, reverse=True) and len(swings) == 7
    assert d["seasonal"]["year1_estimate"] > 0 and abs(d["seasonal"]["gap"]) < 0.1
    assert d["synthetic_rating"]["rating"] and "standard_error" in d["simulation"]["per_share"]


def test_private_firm_mode(demo):
    a = {"mode": "forecast", "market": {"price": 40.0, "basic_shares": 100e6},
         "forecast": {"years_to_terminal": 10, "revenue_growth": 0.06, "terminal_growth": 0.03, "tax_rate": 0.21},
         "cost_of_capital": {"risk_free": 0.04, "equity_risk_premium": 0.05, "beta": 1.0, "pre_tax_cost_of_debt": 0.05}}
    pub = get_model("dcf").run(demo["detail"], a).details
    priv = get_model("dcf").run(demo["detail"], {**a, "private": {"r_squared": 0.25, "discount": 0.25}}).details
    assert priv["rates"]["beta_levered_observed"] == A(2.0) and priv["rates"]["total_beta"]["multiplier"] == A(2.0)
    assert priv["bridge"]["value_per_share"] < pub["bridge"]["value_per_share"]
    same_beta = get_model("dcf").run(demo["detail"], {**a, "private": {"total_beta": False, "discount": 0.25}}).details
    assert same_beta["bridge"]["value_per_share"] == A(0.75 * pub["bridge"]["value_per_share"])


def test_synthesized_firm_matches_the_target():
    t = {"growth_5y": 0.08, "discount_rate": 0.09, "ebitda_margin": 0.20}
    rows = [{"ticker": "A", "growth_5y": 0.04, "discount_rate": 0.09, "ebitda_margin": 0.18},
            {"ticker": "B", "growth_5y": 0.12, "discount_rate": 0.09, "ebitda_margin": 0.22},
            {"ticker": "C", "growth_5y": 0.30, "discount_rate": 0.15, "ebitda_margin": 0.50}]
    s = synthesize(t, rows)
    assert s["weights"]["A"] == A(0.5, abs=0.01) and s["weights"]["B"] == A(0.5, abs=0.01) and s["weights"]["C"] < 0.01
    assert all(f["light"] == "green" for f in s["figures"].values())


def test_comps_precedents_and_synergy_checks_on_the_demo(demo):
    c = demo["load"]("comps")["details"]
    assert c["synthesized"]["blend"]["expected"] > 0 and abs(sum(c["synthesized"]["weights"].values()) - 1) < 1e-9
    assert c["sales_vs_ebitda"]["note"]
    p = demo["load"]("precedents")["details"]
    assert p["regression"]["slope"] < 0 and p["regression"]["sign_ok"]
    assert p["synergy_stats"]["n"] >= 5 and {x["light"] for x in p["alignment"]} <= {"green", "yellow", "red", None}
    s = demo["load"]("dcf_synergy")["details"]["checks"]
    assert s["needed_for_price"]["price"] == 54.0 and s["needed_for_price"]["cost_pct"] > 0
    assert s["lasting_cost"]["share"] == 0 and s["synergies_to_sales"] > 0
    comp = json.loads((demo["out"] / "comparison.json").read_text())
    assert comp["cross_checks"]["exit_multiple"]["key"] == "exit_multiple"
    assert any(r["model"] == "comps_synth" for r in comp["football_field"])
    assert any(r["model"] == "lbo" for r in comp["football_field"])


def test_rnoa_split_and_eva_in_company_detail(demo):
    an = demo["detail"]["analysis"]["annual"]
    r = an[-1]["ratios"]["reformulated"]
    ch = r["rnoa_change"]
    assert ch["margin_effect"] + ch["turnover_effect"] == A(ch["change"])
    va = r["value_added"]
    assert va["eva"] == A(an[-1]["reformulated_income_statement"]["nopat"] - va["wacc"] * va["invested_capital"])
    credit = an[-1]["ratios"]["risk"]["credit"]
    assert credit["cfo_to_debt"] is not None and credit["free_operating_cf_to_debt"] < credit["cfo_to_debt"]
