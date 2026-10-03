"""Synthetic demo data for previewing the site. Not real data.

  python -m L3_app.demo --site-dir site
"""
from __future__ import annotations

import json
from pathlib import Path

from L2_models.reconcile import build_comparison
from L3_app.demo.companies import (AS_OF, DEMO_PRICES, MANUAL_PEER, SPECS, synthetic_records,  # noqa: F401
                                   write_company)
from L3_app.demo.sector import write_demo_sector

def write_demo(site_dir: Path) -> Path:
    """All synthetic companies; returns the main DEMO folder. After the details
    exist, the real comps model runs for each company against the others."""
    from L2_models.base import get_model
    for t in SPECS:
        write_company(site_dir, t)
    details = {t: json.loads((site_dir / "data" / t / AS_OF / "company_detail.json").read_text()) for t in SPECS}
    for t in SPECS:
        out = site_dir / "data" / t / AS_OF
        others = [o for o in SPECS if o != t]
        a = {"target": {"shares": DEMO_PRICES[t][1]}, "market": {"price": DEMO_PRICES[t][0]},
             "peers": [{"ticker": o, "price": DEMO_PRICES[o][0], "shares": DEMO_PRICES[o][1]} for o in others] + [MANUAL_PEER],
             "sources": {"all": "synthetic demo values"}}
        comps = get_model("comps").run(details[t], a, [details[o] for o in others]).to_dict()
        comps.update(lineage={"as_of": AS_OF, "inputs": []}, demo=True)
        (out / "model_results" / "comps.json").write_text(json.dumps(comps, indent=2))
        comparison = build_comparison(sorted((out / "model_results").glob("*.json")), details[t])
        comparison["demo"] = True
        (out / "comparison.json").write_text(json.dumps(comparison, indent=2))
    write_demo_sector(site_dir, details)
    return site_dir / "data" / "DEMO" / AS_OF
