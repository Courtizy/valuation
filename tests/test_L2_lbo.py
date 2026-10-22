"""LBO model (course Week 7 / Week 9). Run: pytest tests/test_L2_lbo.py"""
from __future__ import annotations

import json

import pytest

from valuation._core.lbo import buyout, debt_schedule, pemv, size_debt
from valuation.L2_models.base import get_model
from valuation.L3_app.demo import write_demo

A = pytest.approx


@pytest.fixture
def detail(tmp_path):
    out = write_demo(tmp_path)
    return json.loads((out / "company_detail.json").read_text())


def assumptions(**lbo):
    return {"mode": "forecast", "market": {"price": 40.0, "basic_shares": 100e6},
            "forecast": {"years_to_terminal": 10, "revenue_growth": 0.06, "terminal_growth": 0.03, "tax_rate": 0.21},
            "cost_of_capital": {"risk_free": 0.04, "equity_risk_premium": 0.05, "beta": 1.0, "pre_tax_cost_of_debt": 0.05},
            "lbo": lbo}


PLAN = [{"year": t, "ebitda": 100.0, "ebit": 80.0, "capex": 20.0, "change_in_nwc": 0.0} for t in range(1, 6)]


def test_debt_is_sized_to_the_coverage_target():
    d = size_debt(ebit=80, securable_assets=300, pct_secured=1.0, sub_to_senior=0.6, coverage=2.0,
                  senior_rate=0.04, rate_step=0.03)
    assert d["interest"] == A(40) and d["coverage"] == A(2.0)
    assert d["amounts"]["subordinated"] == A(0.6 * d["amounts"]["senior"]) and d["amounts"]["mezzanine"] > 0
    # little collateral: senior and sub alone fit, mezzanine fills the rest
    capped = size_debt(ebit=80, securable_assets=50, pct_secured=1.0, sub_to_senior=0.6, coverage=2.0,
                       senior_rate=0.04, rate_step=0.03)
    assert capped["amounts"]["senior"] == A(50) and capped["interest"] == A(40)
    # too much collateral for the coverage: senior and sub shrink together, no mezzanine
    big = size_debt(ebit=80, securable_assets=5000, pct_secured=1.0, sub_to_senior=0.6, coverage=2.0,
                    senior_rate=0.04, rate_step=0.03)
    assert big["amounts"]["mezzanine"] == 0 and big["interest"] == A(40)


def test_sweep_pays_tranches_in_order_and_ties_out():
    debt = size_debt(ebit=80, securable_assets=100, pct_secured=1.0, sub_to_senior=0.6, coverage=2.0,
                     senior_rate=0.04, rate_step=0.03)
    rows = debt_schedule(PLAN, debt, 0.25)
    first = rows[0]
    assert first["repaid"]["senior"] > 0 and (first["end"]["senior"] == A(0) or first["repaid"]["subordinated"] == 0)
    for r in rows:
        # cash for debt = EBITDA - capex - dNWC - interest - taxes, with interest on the average balance
        assert r["cash_for_debt"] == A(r["ebitda"] - r["capex"] - r["change_in_nwc"] - r["total_interest"] - r["cash_taxes"])
        avg = sum((r["begin"][t] + r["end"][t]) / 2 * debt["rates"][t] for t in r["begin"])
        assert r["total_interest"] == A(avg)
        assert sum(r["repaid"].values()) + r["to_sponsor"] == A(max(r["cash_for_debt"], 0))


def test_max_price_ignores_the_premium_and_irr_ignores_the_target():
    kw = dict(plan=PLAN, ebit0=80, ebitda0=100, price=10, shares=100, net_debt=50, tax_rate=0.25,
              exit_multiple_change=0.0, securable_assets=100, senior_rate=0.04)
    a = buyout(**kw, sponsor_irr=0.20, offer_premium=0.30)
    b = buyout(**kw, sponsor_irr=0.20, offer_premium=0.10)
    c = buyout(**kw, sponsor_irr=0.25, offer_premium=0.30)
    assert a["max_price"] == A(b["max_price"]) and a["irr_at_offer"] == A(c["irr_at_offer"])
    assert a["max_price"] > c["max_price"]
    # paying exactly the max price earns exactly the target IRR
    at_max = buyout(**kw, sponsor_irr=0.20, offer_premium=a["max_price"] / 10 - 1)
    assert at_max["irr_at_offer"] == A(0.20, abs=1e-6)
    su = a["sources_uses"]
    assert sum(su["sources"].values()) == A(sum(su["uses"].values()))
    assert pemv(a["schedule"], 100, a["exit"]["multiple"], 0.20) == A(a["pemv_at_target"])


def test_lbo_model_on_the_demo(detail):
    r = get_model("lbo").run(detail, assumptions(steps={"margin_add": 0.01}))
    v = r.value_per_share
    assert v["p10"] < v["p50"] < v["p90"]
    d = r.details
    assert d["debt"]["coverage"] >= 2.0 - 1e-9 and len(d["schedule"]) == 5
    assert d["range"]["expected"] == A(d["max_price"]) and d["irr_at_offer"] is not None
    lifted = get_model("lbo").run(detail, assumptions(steps={"margin_add": 0.03})).details["max_price"]
    assert lifted > d["max_price"]          # operating improvements raise what a sponsor can pay
    json.dumps(r.to_dict())


def test_lbo_needs_a_price(detail):
    a = assumptions()
    a["market"]["price"] = None
    d = {**detail, "market": None}
    with pytest.raises(ValueError, match="no market price"):
        get_model("lbo").run(d, a)
