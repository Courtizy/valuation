"""Action titles: one sentence per chart or section, built from the figures the page shows."""
from __future__ import annotations

import json

import pytest

from valuation.L1_detail.headlines import company_headlines
from valuation.L2_models.reconcile.headlines import deal_headlines, valuation_headlines
from valuation.L3_app.demo import write_demo


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    out = write_demo(tmp_path_factory.mktemp("demo"))
    return {n: json.loads((out / f"{n}.json").read_text()) for n in ("comparison", "company_detail")}


def test_valuation_headlines_state_the_answer(demo):
    c = demo["comparison"]
    h = c["headlines"]
    assert set(h) >= {"answer", "field", "spread", "sensitivity", "comps", "dcf"}
    assert h["answer"].startswith("DEMO is worth about $")
    assert f"${c['blend']['p50']:,.2f}" in h["answer"]
    assert f"${c['price']:,.2f} share price" in h["answer"]


def test_deal_headlines_follow_the_bid(demo):
    h = demo["comparison"]["deal"]["headlines"]
    assert h["summary"].startswith("At $54.00, the bid")
    assert "most a buyer can pay" in h["bridge"]
    assert "median" in h["premiums"] and "24 deals" in h["premiums"]


def test_company_headlines_from_the_charts(demo):
    h = demo["company_detail"]["headlines"]
    assert h["revenue"].startswith("Revenue grew ") and "a year from FY" in h["revenue"]
    assert h["returns"].startswith("DEMO earned ")
    assert "Operating margin" in h["margins"]
    assert h["cash"].startswith("Free cash flow was ")


def test_missing_figures_give_none_not_a_guess():
    assert company_headlines({}) == dict.fromkeys(("revenue", "returns", "margins", "cash"))
    one_year = {"views": {"annual": [{"label": "FY2025", "values": {"revenue": 1e9}}]}}
    assert company_headlines(one_year)["revenue"] is None
    assert not any(deal_headlines(None, {}).values())
    assert not any(valuation_headlines({"blend": None, "price": None, "plan": {"methods": []}, "football_field": []}, {}).values())


def test_flat_and_shrinking_revenue_wording():
    ann = lambda r0, r1: {"views": {"annual": [{"label": "FY2024", "values": {"revenue": r0}}, {"label": "FY2025", "values": {"revenue": r1}}]}}
    assert company_headlines(ann(100e6, 100.2e6))["revenue"] == "Revenue held flat from FY2024 to FY2025, to $100M."
    assert "shrank 10.0% a year" in company_headlines(ann(100e6, 90e6))["revenue"]
