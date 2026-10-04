"""The pre-loaded demo: synthetic companies run through the real pipeline code, published to its
own data root so it never mixes with real tickers.

  python -m L3_app.demo                 # writes site/demo/data (what the site's Demo switch loads)
  python -m L3_app.demo --site-dir X    # writes X/demo/data

What it shows (every feature the site has):
  DEMO   mature manufacturer: your own dcf.json (forecast mode, price and beta filled from market
         data), comps against six detailed industrial peers plus a hand-entered one, an
         illustrative precedents row, market price checked against the backup source
  DEMOG  high-growth software: implied mode (growth solved to match the price), a price
         cross-check mismatch flag
  DEMOU  leveraged utility: no dcf.json, so the DCF default case; Yahoo was "down" so the backup
         source supplied the price; two years of D&A filled from fundamentals (marked y)
  ZZA-ZZF  comps peers with full company detail and default-case DCFs
  Demo Industrials (Synthetic): 23 companies across two industry groups and three industries
Everything is flagged demo: true and every name says "(synthetic)".
"""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from L1_detail.build import build_detail
from L2_models.base import get_model
from L2_models.dcf import default_assumptions
from L2_models.reconcile import build_comparison
from L3_app.demo.companies import (AS_OF, DEMO_PRICES, DEMO_SIC, FEATURED, MANUAL_PEER, MARKET, PEERS,  # noqa: F401
                                   SPECS, synthetic_records)
from L3_app.demo.market import RISK_FREE, fundamentals_for_gaps, raw_market
from L3_app.demo.sector import write_demo_sector

LINEAGE = {"as_of": AS_OF, "inputs": []}

# Your own dcf.json for two of the featured companies; DEMOU and the peers use the default case.
DCF_ASSUMPTIONS = {
    "DEMO": {"mode": "forecast", "market": {"price": None, "basic_shares": None},
             "forecast": {"years_to_terminal": 10, "revenue_growth": 0.08, "terminal_growth": 0.03, "tax_rate": 0.21},
             "cost_of_capital": {"risk_free": None, "risk_free_terminal": 0.05, "equity_risk_premium": 0.05,
                                 "beta": None, "pre_tax_cost_of_debt": 0.06},
             "sources": {"revenue_growth": "synthetic demo assumption", "terminal_growth": "synthetic demo assumption"}},
    "DEMOG": {"mode": "implied", "market": {"price": None, "basic_shares": None},
              "forecast": {"years_to_terminal": 10, "revenue_growth": 0.25, "terminal_growth": 0.03, "tax_rate": 0.21},
              "cost_of_capital": {"risk_free": None, "equity_risk_premium": 0.05, "beta": None},
              "sources": {"mode": "synthetic demo: implied growth solved to match the price"}},
}


def _canonical(ticker: str) -> tuple[dict, list[dict]]:
    """Synthetic filings; for DEMOU, two fiscal years of annual D&A are left out (the gap Yahoo fills)."""
    recs = synthetic_records(SPECS[ticker])
    removed = []
    if ticker == "DEMOU":
        keep = []
        for r in recs:
            gap = (r["concept"] == "depreciation_amortization_cf" and r["fiscal_year"] in (2022, 2023)
                   and r["fiscal_period"] == "FY")
            (removed if gap else keep).append(r)
        recs = keep
    entity = {"ticker": ticker, "name": SPECS[ticker]["name"], "cik": None, "sic": DEMO_SIC[ticker]}
    return {"stage": "L1.normalize", "as_of": AS_OF, "entity": entity, "records": recs}, removed


def _write(path: Path, doc: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2))
    return path


def build_demo_data(data_dir: Path) -> dict:
    """The pipeline's data/ layout for every synthetic company; returns the details by ticker."""
    details = {}
    for t in FEATURED + PEERS:
        canonical, removed = _canonical(t)
        raw = raw_market(t)
        if removed:
            raw["fundamentals"] = fundamentals_for_gaps(removed)
        detail = build_detail(canonical, AS_OF, raw, lineage=LINEAGE, risk_free=RISK_FREE)
        detail["demo"] = True
        details[t] = detail
        _write(data_dir / t / AS_OF / "company_detail.json", detail)

    for t, detail in details.items():
        out = data_dir / t / AS_OF
        results = []
        dcf = get_model("dcf").run(detail, DCF_ASSUMPTIONS.get(t) or default_assumptions(detail)).to_dict()
        results.append(_write(out / "model_results" / "dcf.json", {**dcf, "lineage": LINEAGE, "demo": True}))
        if t == "DEMO":
            # comps against the six industrial peers plus one hand-entered peer (DEMOG and DEMOU are
            # other industries, so they're left out, as an analyst would)
            others = list(PEERS)
            a = {"peers": others + [MANUAL_PEER],
                 "sources": {"peers": "synthetic demo peers; prices from the synthetic market data"}}
            comps = get_model("comps").run(detail, a, [details[o] for o in others]).to_dict()
            results.append(_write(out / "model_results" / "comps.json", {**comps, "lineage": LINEAGE, "demo": True}))
        if t == "DEMO":
            # precedents isn't built yet: an illustrative row so the football field shows a reference method
            mid = dcf["value_per_share"]["p50"]
            prec = {"schema_version": "0.1.0", "model": "precedents", "ticker": t, "as_of": AS_OF,
                    "value_per_share": {"p10": mid * 1.04, "p50": mid * 1.24, "p90": mid * 1.42, "mean": mid * 1.233},
                    "assumptions_used": {}, "lineage": LINEAGE, "samples_ref": None,
                    "notes": ["synthetic demo result, not a valuation"], "demo": True, "illustrative": True}
            results.append(_write(out / "model_results" / "precedents.json", prec))
        comparison = build_comparison(results, detail)
        _write(out / "comparison.json", {**comparison, "demo": True})

    write_demo_sector(data_dir, {t: details[t] for t in ("DEMO",) + PEERS})
    return details


def write_demo(root: Path) -> Path:
    """Build the demo and publish it under root/data (root = site/demo for the site's Demo switch).
    Returns the DEMO run folder."""
    from L3_app.publish import publish
    root = Path(root)
    if (root / "data").exists():
        shutil.rmtree(root / "data")
    with tempfile.TemporaryDirectory() as tmp:
        build_demo_data(Path(tmp))
        publish(Path(tmp), root, "real", keep_demo=True)
    index_path = root / "data" / "index.json"
    index = json.loads(index_path.read_text())
    index.update(demo=True, market_data="demo")
    index_path.write_text(json.dumps(index))
    return root / "data" / "DEMO" / AS_OF
