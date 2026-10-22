"""Public comparables model. Run: pytest tests/test_L2_comps.py"""
from __future__ import annotations

import json

import pytest

from valuation.L2_models.base import get_model
from valuation.L2_models.comps import CompsError, implied_price, match, peer_row
from valuation.L3_app.demo import write_demo

A = pytest.approx


@pytest.fixture
def details(tmp_path):
    write_demo(tmp_path)
    load = lambda t: json.loads((tmp_path / "data" / t / "2026-09-30" / "company_detail.json").read_text())  # noqa: E731
    return {t: load(t) for t in ("DEMO", "DEMOG", "DEMOU")}


def test_peer_row_and_implied_price():
    r = peer_row({"price": 10, "shares": 100, "debt": 300, "cash": 100, "sales": 1000, "ebitda": 200, "net_income": 50})
    assert r["enterprise_value"] == 1200 and r["multiples"] == {"ev_sales": A(1.2), "ev_ebitda": A(6.0), "pe": A(20.0)}
    target = {"shares": 50, "debt": 100, "cash": 0, "sales": 500, "ebitda": 100, "net_income": 30}
    assert implied_price("ev_ebitda", 6.0, target) == A((600 - 100) / 50)
    assert implied_price("pe", 20.0, target) == A(20 * 30 / 50)
    assert implied_price("ev_ebitda", 6.0, {**target, "ebitda": -5}) is None
    assert peer_row({"price": 10, "shares": 1, "ebitda": -1, "sales": 5})["multiples"]["ev_ebitda"] is None


def test_comps_from_sec_peers_and_manual_peer(details):
    a = {"target": {"shares": 330e6}, "market": {"price": 45},
         "peers": [{"ticker": "DEMOG", "price": 18.0, "shares": 100e6},
                   {"ticker": "DEMOU", "price": 98.0, "shares": 250e6},
                   {"ticker": "PRIVCO", "sec": False, "price": 20, "shares": 1e8, "debt": 0, "cash": 0,
                    "sales": 2e9, "ebitda": 4e8, "net_income": 2e8}]}
    r = get_model("comps").run(details["DEMO"], a, [details["DEMOG"], details["DEMOU"]])
    d = r.details
    assert [p["source"] for p in d["peers"]] == ["sec", "sec", "manual"]
    implied = d["multiples"]["ev_ebitda"]["implied"]
    vals = sorted(x for x in implied.values() if x is not None)
    assert d["multiples"]["ev_ebitda"]["conservative"] == A(vals[0])
    assert d["multiples"]["ev_ebitda"]["aggressive"] == A(vals[-1])
    v = r.value_per_share
    assert v["p10"] <= v["p50"] <= v["p90"]
    assert v["p50"] == A((d["multiples"]["ev_ebitda"]["expected"] + d["multiples"]["ev_sales"]["expected"]) / 2)
    json.dumps(r.to_dict())


def test_comps_quartiles_weights_and_drops(details):
    peers = [{"ticker": t, "sec": False, "price": p, "shares": 1e8, "debt": 0, "cash": 0, "sales": 1e9,
              "ebitda": e, "net_income": 1e8} for t, p, e in
             [("A", 10, 2e8), ("B", 12, 2e8), ("C", 14, 2e8), ("D", 16, 2e8), ("E", 30, 2e8)]]
    a = {"target": {"shares": 330e6}, "peers": peers, "multiples": ["ev_ebitda", "pe"],
         "weights": {"ev_ebitda": 3, "pe": 1}, "range": "quartiles"}
    r = get_model("comps").run(details["DEMO"], a, [])
    m = r.details["multiples"]
    assert m["ev_ebitda"]["conservative"] < m["ev_ebitda"]["expected"] < m["ev_ebitda"]["aggressive"]
    assert r.value_per_share["p50"] == A(0.75 * m["ev_ebitda"]["expected"] + 0.25 * m["pe"]["expected"])
    loss = json.loads(json.dumps(details["DEMO"]))
    loss["views"]["ttm"][-1]["values"]["net_income"] = -1
    r2 = get_model("comps").run(loss, a, [])
    assert "pe" not in r2.details["multiples"] and any("P / E dropped" in n for n in r2.notes)


def test_comps_errors(details):
    with pytest.raises(CompsError, match="no peers"):
        get_model("comps").run(details["DEMO"], {}, [])
    no_market = {**details["DEMOG"], "market": None}       # showcase mode: no peer prices
    with pytest.raises(CompsError, match="no peer has a price"):
        get_model("comps").run(details["DEMO"], {"target": {"shares": 1e8}, "peers": ["DEMOG"]}, [no_market])


def test_target_shares_from_the_filed_count_and_missing_prices_are_a_warning(details):
    from valuation.L2_models.comps import NoPeerPrices, company_figures
    d = {**details["DEMO"], "market": None, "shares_outstanding": 123e6}   # showcase: no market block
    assert company_figures(d)["shares"] == 123e6               # cover-page count wins over the statements
    no_market = {**details["DEMOG"], "market": None}
    with pytest.raises(NoPeerPrices) as e:
        get_model("comps").run(d, {"peers": ["DEMOG"]}, [no_market])
    assert e.value.is_warning


def test_match_rates_drivers_with_a_stoplight():
    t = {"growth_5y": 0.08, "growth_past_5y": 0.08, "discount_rate": 0.09, "ebitda_margin": 0.22,
         "net_debt_to_ev": 0.03, "sales": 100.0}
    close = match(t, {**t, "growth_5y": 0.095, "sales": 190.0})
    assert close["closeness"] == 1.0 and close["flag"] == "ok" and close["size"] == A(1.9)
    m = match(t, {**t, "growth_5y": 0.11, "discount_rate": 0.105, "net_debt_to_ev": 0.20})
    lights = {k: f["light"] for k, f in m["figures"].items()}
    assert lights == {"growth_5y": "yellow", "growth_past_5y": "green", "discount_rate": "red",
                      "ebitda_margin": "green", "net_debt_to_ev": "red"}
    assert m["closeness"] == A(2.5 / 5) and m["weight"] == A(0.5) and m["flag"] == "ok"
    weak = match(t, {**t, "growth_5y": 0.2, "discount_rate": 0.2, "ebitda_margin": 0.4})
    assert weak["flag"] == "weak" and weak["weight"] == A(0.4)
    few = match(t, {"ebitda_margin": 0.22, "sales": 100.0})
    assert few["checked"] == 1 and few["flag"] == "unchecked" and few["weight"] == 0.5
    assert match(t, {**t, "growth_5y": 0.12}, {"growth_5y": 0.05})["figures"]["growth_5y"]["light"] == "green"


def test_weighted_quantiles_match_the_equal_weight_rule():
    from valuation.L2_models.comps import _range, _wrange
    xs = [31.0, 37.0, 42.8, 45.8, 48.6, 52.7]
    assert _wrange([(x, 1.0) for x in xs], "quartiles") == A(_range(xs, "quartiles"))
    assert _wrange([(x, 1.0) for x in xs], "min_max")["expected"] == A(statistics_median(xs))
    heavy = _wrange([(10.0, 1.0), (20.0, 1.0), (30.0, 8.0)], "min_max")
    assert heavy["expected"] > 20 and heavy["conservative"] == 10 and heavy["aggressive"] == 30
    assert _wrange([(10.0, 0.0), (20.0, 1.0), (30.0, 1.0)], "min_max")["conservative"] == 20     # no weight, no say


def statistics_median(xs):
    import statistics
    return statistics.median(xs)


def test_closest_set_is_valued_alongside_the_sector_set(tmp_path):
    out = write_demo(tmp_path)
    r = json.loads((out / "model_results" / "comps.json").read_text())
    d = r["details"]
    assert all("match" in p for p in d["peers"]) and d["closest"]["blend"]["expected"] > 0
    manual = next(p for p in d["peers"] if p["ticker"] == "MANUALCO")
    assert manual["match"]["flag"] == "weak" and any("weak match" in n for n in r["notes"])
    assert manual["figure_sources"]["growth_5y"] == "typed in comps.json"
    assert d["target"]["figure_sources"]["growth_5y"].startswith("analysts, next 5 years")
    assert d["peer_weights"] == "closeness" and d["blend"] != d["blend_equal"]
    assert set(d["peer_average"]["growth_5y"]) == {"average", "weighted", "target"}
    assert r["assumptions_used"]["closest"] == [p["ticker"] for p in d["closest"]["peers"]]
    c = json.loads((out / "comparison.json").read_text())
    row = next(m for m in c["plan"]["methods"] if m["model"] == "comps_closest")
    assert row["weight"] == 0 and row["value_per_share"]["p50"] == A(d["closest"]["blend"]["expected"])
    assert any(m["method"] == "comps_closest" and m["weight"] == 0 for m in c["deal"]["standalone"]["methods"])
    assert "closest on fundamentals" in c["headlines"]["comps"]


def test_equal_peer_weights_option(details):
    a = {"target": {"shares": 330e6}, "market": {"price": 45}, "peer_weights": "equal",
         "peers": [{"ticker": "DEMOG", "price": 18.0, "shares": 100e6}, {"ticker": "DEMOU", "price": 98.0, "shares": 250e6}]}
    d = get_model("comps").run(details["DEMO"], a, [details["DEMOG"], details["DEMOU"]]).details
    assert d["blend"] == A(d["blend_equal"]) and d["peer_weights"] == "equal"
