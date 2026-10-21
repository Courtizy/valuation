"""Acquisition models: whole-firm DCF with synergies and just synergies. Run: pytest tests/test_L2_synergy.py"""
from __future__ import annotations

import json

import pytest

from valuation._core.synergy import cost_adjustments, just_synergies
from valuation.L2_models.base import get_model
from valuation.L2_models.dcf.synergy import DealError
from valuation.L3_app.demo import write_demo

A = pytest.approx


@pytest.fixture
def detail(tmp_path):
    out = write_demo(tmp_path)
    return json.loads((out / "company_detail.json").read_text())


def assumptions(**syn):
    return {
        "mode": "forecast",
        "market": {"price": 40.0, "basic_shares": 100e6},
        "forecast": {"years_to_terminal": 10, "revenue_growth": 0.08, "terminal_growth": 0.03, "tax_rate": 0.21},
        "cost_of_capital": {"risk_free": 0.04, "risk_free_terminal": 0.05, "equity_risk_premium": 0.05,
                            "beta": 1.1, "pre_tax_cost_of_debt": 0.06},
        "deal": {"synergies": {"annual_cost": 50e6, "revenue_pct_of_cost": 0.3, "years_to_full": 2, **syn}},
    }


def test_cost_adjustments_phase_in_and_terminal():
    assert cost_adjustments(0.1, 1.0, 0.2, 2, 5) == A([0.1, -0.05, -0.1, -0.1, -0.02])
    assert cost_adjustments(0.1, 0.5, 0.0, 3, 5) == A([0.05, -0.05 / 3, -0.1 / 3, -0.05, 0.0])


def test_just_synergies_hand_check():
    v = just_synergies(annual_cost=100, revenue_pct_of_cost=0.0, one_time_cost=100, tax_rate=0.0, terminal_growth=0.0,
                       wacc=0.1, wacc_terminal=0.1, growth=0.0, years_to_full=1, terminal_year=1, cost_forever=1.0,
                       shares=10, pre_price=20)
    # year 0: -100 one-time, undiscounted; year 1: (100 + 100 / 0.1) / 1.1 = 1000
    assert v["total_value"] == A(-100 + 1100 / 1.1)
    assert v["value_per_share"] == A(20 + v["total_value"] / 10)


def test_no_synergies_gives_standalone(detail):
    dcf = get_model("dcf").run(detail, assumptions()).details["bridge"]["value_per_share"]
    r = get_model("dcf_synergy").run(detail, assumptions(annual_cost=0, revenue_pct_of_cost=0, revenue_growth_add=0))
    assert r.details["standalone_per_share"] == A(dcf)
    assert r.value_per_share["p50"] == A(dcf)
    j = get_model("just_synergy").run(detail, assumptions(annual_cost=0, one_time_cost=0))
    assert j.value_per_share["p50"] == A(40.0)


def test_synergies_add_value_and_ranges_are_ordered(detail):
    r = get_model("dcf_synergy").run(detail, assumptions(revenue_growth_add=0.01))
    v = r.value_per_share
    assert v["p10"] < v["p50"] < v["p90"]
    assert r.details["synergy_per_share"] > 0
    assert r.details["cost_pct"] > 0
    g = r.details["sensitivity"]
    assert g["values"][3][2] == A(v["p50"])            # centre cell is the base case
    j = get_model("just_synergy").run(detail, assumptions())
    assert j.value_per_share["p10"] < j.value_per_share["p50"] < j.value_per_share["p90"]
    assert j.details["pre_announcement_price"] == 40.0
    assert j.details["max_premium"] == A(j.details["synergy_per_share"] / 40.0)
    assert j.details["synergies"]["one_time_cost"] == A(2 * 50e6 * 1.3)     # the default rule of thumb


def test_pre_announcement_price_overrides_market(detail):
    a = assumptions()
    a["deal"]["pre_announcement_price"] = 30.0
    j = get_model("just_synergy").run(detail, a)
    assert j.details["pre_announcement_price"] == 30.0


def test_missing_deal_is_explained(detail):
    a = assumptions()
    del a["deal"]
    with pytest.raises(DealError, match="enter the expected synergies"):
        get_model("dcf_synergy").run(detail, a)


# ------------------------------------------------------------ deal summary

from valuation.L2_models.reconcile.deal import deal_summary  # noqa: E402


def _r(model, low, mid, high):
    return {"model": model, "value_per_share": {"p10": low, "p50": mid, "p90": high},
            "details": {"range": {"conservative": low, "expected": mid, "aggressive": high}}}


def test_offer_range_weights_power_and_synergy_share():
    by = {"precedents": _r("precedents", 40, 45, 50), "dcf_synergy": _r("dcf_synergy", 42, 48, 55),
          "just_synergy": _r("just_synergy", 41, 46, 52), "dcf": _r("dcf", 30, 33, 36)}
    detail = {"market": {"price": 33.0, "quote": {"wk52_low": 25.0, "wk52_high": 40.0}}}
    s = deal_summary(by, detail, {"relative_power": 0.6, "offer_price": 53.0})
    o = s["offer"]["range"]
    low = 0.34 * 40 + 0.33 * 42 + 0.33 * 41
    high = 0.34 * 50 + 0.33 * 48 + 0.33 * 46          # synergy methods enter the top at their best guess
    assert o["conservative"] == A(low) and o["aggressive"] == A(high)
    assert o["best_guess"] == A(low + (high - low) * 0.6)
    assert s["offer"]["premium"]["conservative"] == A(low / 33 - 1)
    assert s["offer"]["synergy_share"]["aggressive"] == A(1.0)
    assert s["offer_price_synergy_share"] == A((53 - 33) / (high - 33))
    # standalone: comps and prior-deal pre-announcement multiples are missing, so DCF and the
    # 52-week range share the weight 2 : 1
    st = s["standalone"]["range"]
    assert st["best_guess"] == A((0.4 * 33 + 0.2 * 33) / 0.6)
    assert st["conservative"] == A((0.4 * 30 + 0.2 * 25) / 0.6)
    assert any("no value yet" in n for n in s["notes"])


def test_weights_override_and_blank_rows():
    by = {"dcf_synergy": _r("dcf_synergy", 42, 48, 55)}
    s = deal_summary(by, {"market": {"price": 33.0}}, {"weights": {"offer": {"just_synergy": 0}}})
    rows = {r["method"]: r for r in s["offer"]["methods"]}
    assert rows["dcf_synergy"]["adjusted_weight"] == A(1.0)
    assert s["offer"]["range"]["aggressive"] == A(48)
