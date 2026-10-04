"""One similarity ranking for Similar Companies and the peer picker. Run: pytest tests/test_L3_similar.py"""
from __future__ import annotations

from valuation.L3_app.similar import rank


def co(t, **kw):
    base = {"ticker": t, "traits": {"stage": "mature", "predictability": "high"}, "revenue": 1e9,
            "revenue_cagr": 0.05, "operating_margin": 0.20, "fcf_margin_stdev": 0.01, "capex_to_sales": 0.04,
            "debt_to_ebitda": 1.0}
    return {**base, **kw}


def test_closest_first_and_self_excluded():
    me = co("ME")
    pool = [me, co("NEAR", operating_margin=0.21), co("FAR", operating_margin=0.60, revenue_cagr=0.40, revenue=1e11)]
    r = rank(me, pool)
    assert [x["ticker"] for x in r] == ["NEAR", "FAR"] and r[0]["score"] > r[1]["score"]


def test_shared_traits_break_ties():
    me = co("ME")
    twin_a = co("A", traits={"stage": "mature", "predictability": "high"}, operating_margin=0.25)
    twin_b = co("B", traits={"stage": "declining", "predictability": "low"}, operating_margin=0.15)
    r = rank(me, [me, twin_a, twin_b])
    assert r[0]["ticker"] == "A" and r[0]["traits_shared"] == 2 and r[1]["traits_shared"] == 0


def test_missing_figures_are_skipped_not_zeroed():
    me = co("ME")
    r = rank(me, [me, co("X", debt_to_ebitda=None, fcf_margin_stdev=None), co("Y", revenue_cagr=None,
             operating_margin=None, fcf_margin_stdev=None, capex_to_sales=None, debt_to_ebitda=None, revenue=None)])
    assert r[0]["ticker"] == "X" and r[-1]["score"] is None
