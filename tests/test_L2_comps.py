"""Public comparables model. Run: pytest tests/test_L2_comps.py"""
from __future__ import annotations

import json

import pytest

from L2_models.base import get_model
from L2_models.comps import CompsError, implied_price, peer_row
from L3_app.demo import write_demo

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
    with pytest.raises(CompsError, match="price and a share count"):
        get_model("comps").run(details["DEMO"], {"target": {"shares": 1e8}, "peers": ["DEMOG"]}, [details["DEMOG"]])
