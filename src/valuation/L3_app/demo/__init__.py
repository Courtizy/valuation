"""The pre-loaded demo: synthetic companies run through the real pipeline code, published to its
own data root so it never mixes with real tickers.

  python -m valuation.L3_app.demo                 # writes site/demo/data (what the site's Demo switch loads)
  python -m valuation.L3_app.demo --site-dir X    # writes X/demo/data

What it shows (every feature the site has):
  DEMO   mature manufacturer: your own dcf.json (forecast mode, price and beta filled from market
         data), comps against a sector set (four industrial peers and a hand-entered one) and the
         four peers closest on fundamentals, an
         market price checked against the backup source, and a synthetic bid for the Deal view:
         synergies and transaction comps on a synthetic deal list
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

from valuation.L1_detail.build import build_detail
from valuation.L2_models.base import get_model
from valuation.L2_models.dcf import default_assumptions
from valuation.L2_models.reconcile import build_comparison
from valuation.L3_app.demo.companies import (AS_OF, DEMO_PRICES, DEMO_SIC, FEATURED, MANUAL_PEER, MARKET, PEERS,  # noqa: F401
                                   SPECS, synthetic_records)
from valuation.L3_app.demo.deals import demo_deal_list
from valuation.L3_app.demo.market import RISK_FREE, fundamentals_for_gaps, raw_market
from valuation.L3_app.demo.sector import write_demo_sector

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


def demo_deal(detail: dict) -> dict:
    """A synthetic bid for DEMO: cost synergies of 3% of revenue, revenue synergies a third of that,
    and an initial offer of $54.00 against the $45.00 pre-announcement price (a 20% premium)."""
    rev = detail["views"]["annual"][-1]["values"]["revenue"]
    return {"relative_power": 0.5, "sources": {"synergies": "synthetic demo assumption", "offer_price": "synthetic demo bid"},
            "pre_announcement_price": 45.0, "offer_price": 54.0,
            "synergies": {"annual_cost": round(rev * 0.03, -5), "revenue_pct_of_cost": 0.33, "years_to_full": 2,
                          "cost_forever": 0.1, "revenue_growth_add": 0.005, "cost_realized": 1.0}}


# a sponsor's view of DEMO: the course defaults, exit at today's multiple, and the operating
# improvements a sponsor would claim (a point of margin, a tenth of working capital released)
DEMO_LBO = {"sponsor_irr": 0.20, "hold_years": 5, "offer_premium": 0.20, "exit_multiple_change": 0.0, "coverage": 2.0,
            "steps": {"margin_add": 0.01, "nwc_change": -0.10},
            "sources": {"lbo": "synthetic demo assumptions (course defaults)"}}

SECTOR_PEERS = ("ZZA", "ZZB", "ZZC", "ZZF")


def closest_peers(detail: dict, details: dict, n: int = 4) -> list[str]:
    """The demo's closest-match set: the peers rated closest on the comps figures, nearest in size on ties."""
    from valuation._core.figures import company_figures
    from valuation.L2_models.comps import match, peer_row
    me = peer_row(company_figures(detail))
    scored = []
    for t in PEERS:
        row = peer_row(company_figures(details[t]))
        m = match(me, row)
        scored.append((-(m["closeness"] or 0), abs(m["size"] - 1) if m["size"] else 9, t))
    return [t for *_, t in sorted(scored)[:n]]


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
        a = dcf_a = DCF_ASSUMPTIONS.get(t) or default_assumptions(detail)
        if t not in FEATURED:
            a = {**a, "simulation": {"runs": 500}}          # peers: a lighter simulation keeps rebuilds quick
        dcf = get_model("dcf").run(detail, a).to_dict()
        results.append(_write(out / "model_results" / "dcf.json", {**dcf, "lineage": LINEAGE, "demo": True}))
        if t == "DEMO":
            # two peer sets: the sector set (machinery and freight, the traditional industrial pick, plus
            # one hand-entered peer) and the four closest on fundamentals among all six detailed
            # peers, whatever their industry (DEMOG and DEMOU are other sectors, so they're left out)
            others = list(PEERS)
            a = {"peers": list(SECTOR_PEERS) + [MANUAL_PEER], "closest": closest_peers(detail, details),
                 "sources": {"peers": "synthetic demo peers from the same sector; prices from the synthetic market data",
                             "closest": "the four synthetic peers rated closest on growth, discount rate, margin and leverage"}}
            comps = get_model("comps").run(detail, a, [details[o] for o in others]).to_dict()
            results.append(_write(out / "model_results" / "comps.json", {**comps, "lineage": LINEAGE, "demo": True}))
        deal = demo_deal(detail) if t == "DEMO" else None
        if deal:
            # transaction comps on a synthetic deal list (as pasted from an SDC export)
            prec = get_model("precedents").run(detail, {"csv": demo_deal_list(), "deal": deal,
                                                        "sources": {"deals": "synthetic demo deal list"}}).to_dict()
            results.append(_write(out / "model_results" / "precedents.json", {**prec, "lineage": LINEAGE, "demo": True}))
            # an acquisition case: synergies sized off the company's own revenue
            for m in ("dcf_synergy", "just_synergy", "lbo"):
                extra = {"lbo": DEMO_LBO} if m == "lbo" else {}
                r = get_model(m).run(detail, {**dcf_a, "deal": deal, **extra}).to_dict()
                results.append(_write(out / "model_results" / f"{m}.json", {**r, "lineage": LINEAGE, "demo": True}))
        comparison = build_comparison(results, detail, None, deal)
        _write(out / "comparison.json", {**comparison, "demo": True})

    write_demo_sector(data_dir, {t: details[t] for t in ("DEMO",) + PEERS})
    return details


def write_demo(root: Path) -> Path:
    """Build the demo and publish it under root/data (root = site/demo for the site's Demo switch).
    Returns the DEMO run folder."""
    from valuation.L3_app.publish import publish
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
