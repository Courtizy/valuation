"""Company profile (L1) and the method plan it drives (reconcile). Run: pytest tests/test_profile_and_plan.py"""
from __future__ import annotations

import json

import pytest

from L1_detail.build import build_detail
from L1_detail.profile import build_profile, load_rules
from L2_models.reconcile import build_comparison
from L2_models.reconcile.methods import method_plan
from L3_app.demo import AS_OF, SPECS, synthetic_records, write_demo
from L3_app.publish import publish

A = pytest.approx


def detail_for(ticker: str) -> dict:
    canonical = {"stage": "L1.normalize", "as_of": AS_OF, "entity": {"ticker": ticker}, "records": synthetic_records(SPECS[ticker])}
    return build_detail(canonical, AS_OF)


@pytest.mark.parametrize("ticker, expected", [
    ("DEMO", {"stage": "mature grower", "predictability": "high", "asset_intensity": "moderate", "capital_structure": "low leverage"}),
    ("DEMOG", {"stage": "high growth", "predictability": "low", "asset_intensity": "light", "capital_structure": "low leverage"}),
    ("DEMOU", {"stage": "mature", "predictability": "high", "asset_intensity": "heavy", "capital_structure": "high leverage"}),
])
def test_profile_labels(ticker, expected):
    p = detail_for(ticker)["profile"]
    assert {k: v["label"] for k, v in p["traits"].items()} == expected
    assert p["traits"]["stage"]["measures"]["revenue_cagr"] == A(SPECS[ticker]["growth"], abs=1e-9)
    assert all(t["rule"] for t in p["traits"].values())


def test_profile_rules_can_be_overridden():
    d = detail_for("DEMO")
    p = build_profile(d, load_rules({"stage": {"high_growth_cagr": 0.05}}))
    assert p["traits"]["stage"]["label"] == "high growth"


def test_profile_unknown_without_history():
    p = build_profile({"views": {"annual": [], "ttm": [], "quarterly": []}, "analysis": {"annual": [], "ttm": []}})
    assert {t["label"] for t in p["traits"].values()} == {"unknown"}


def _profile(**labels):
    return {"traits": {k: {"label": v} for k, v in labels.items()}}


def test_plan_follows_traits_not_sector():
    mature = method_plan(_profile(stage="mature grower", predictability="high", capital_structure="low leverage"), ["dcf", "comps"])
    assert [(m["model"], m["role"], m["weight"]) for m in mature["methods"][:2]] == [("dcf", "primary", 0.6), ("comps", "cross-check", 0.4)]
    growth = method_plan(_profile(stage="high growth", predictability="low"), ["dcf", "comps"])
    assert growth["methods"][0]["model"] == "comps" and growth["methods"][0]["weight"] == A(0.6)
    bank = method_plan(_profile(stage="mature", predictability="high", capital_structure="financial"), ["dcf", "comps"])
    assert bank["methods"][0]["model"] == "comps" and next(m for m in bank["methods"] if m["model"] == "dcf")["weight"] == 0
    for plan in (mature, growth, bank):
        assert sum(m["weight"] for m in plan["methods"]) == A(1.0)
        assert all(m["reason"] for m in plan["methods"])


def test_plan_renormalizes_when_a_method_is_missing():
    p = method_plan(_profile(stage="mature grower", predictability="high"), ["dcf"])
    assert next(m for m in p["methods"] if m["model"] == "dcf")["weight"] == A(1.0)
    assert any("didn't run" in n for n in p["notes"])


def test_overrides_and_acquisition_context():
    p = method_plan(_profile(stage="mature grower", predictability="high"), ["dcf", "comps", "precedents"],
                    {"weights": {"dcf": 1, "precedents": 3}})
    w = {m["model"]: m["weight"] for m in p["methods"]}
    assert w == {"dcf": A(0.25), "precedents": A(0.75), "comps": 0.0, "lbo": 0.0}
    assert p["methods"][0]["model"] == "precedents" and p["methods"][0]["role"] == "primary"
    acq = method_plan(None, ["dcf", "precedents"], {"context": "acquisition"})
    assert acq["context"] == "acquisition"
    assert next(m for m in acq["methods"] if m["model"] == "precedents")["weight"] == A(1.0)


def test_comparison_blend_and_upside(tmp_path):
    out = write_demo(tmp_path)
    c = json.loads((out / "comparison.json").read_text())
    vps = {m["model"]: m["value_per_share"] for m in c["plan"]["methods"] if m["value_per_share"]}
    for k in ("p10", "p50", "p90"):
        assert c["blend"][k] == A(0.6 * vps["dcf"][k] + 0.4 * vps["comps"][k])
        assert c["upside"][k] == A(c["blend"][k] / c["price"] - 1)
    assert c["price_source"] == "market data"          # the example's synthetic market block
    assert c["profile"]["traits"]["stage"]["label"] == "mature grower"


def test_comparison_without_detail_still_works(tmp_path):
    out = write_demo(tmp_path)
    c = build_comparison(sorted((out / "model_results").glob("*.json")))
    assert c["profile"] is None and c["plan"]["methods"] and c["price"] == 45.0


def test_publish_writes_company_cards(tmp_path):
    write_demo(tmp_path / "site")
    publish(tmp_path / "nodata", tmp_path / "site")
    cards = {c["ticker"]: c for c in json.loads((tmp_path / "site" / "data" / "companies.json").read_text())["companies"]}
    assert set(cards) == {"DEMO", "DEMOG", "DEMOU"}
    d = cards["DEMO"]
    assert d["traits"]["predictability"] == "high"
    ttm = json.loads((tmp_path / "site" / "data" / "DEMO" / AS_OF / "company_detail.json").read_text())["views"]["ttm"][-1]["values"]
    assert d["multiples"]["pe"] == A(d["market"]["market_cap"] / ttm["net_income"])
    assert d["rates"]["wacc"] is not None
