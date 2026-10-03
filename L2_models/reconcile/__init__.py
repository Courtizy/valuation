"""Cross-model reconciliation. Reads model_results/*.json; imports no model.

Builds comparison.json with:
  - the method plan from the company profile: primary, cross-check and
    reference methods with reasons and weights (methods.py), a blended
    bear / base / bull value, and upside against the price
  - each model's value range (football-field data)
  - consistency warnings: different as_of dates or different input files
  - assumption differences: fields present in 2+ models whose values differ,
    which is how a value gap gets split into "inputs" vs "method"
"""
from __future__ import annotations

import json
from pathlib import Path

from .methods import method_plan

COMPARISON_SCHEMA_VERSION = "0.2.0"


def _flatten(d: dict, prefix: str = "") -> dict:
    out = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flatten(v, key + "."))
        else:
            out[key] = v
    return out


def build_comparison(result_paths: list[str | Path], detail: dict | None = None,
                     overrides: dict | None = None) -> dict:
    """`detail` (company_detail.json) supplies the profile and price;
    `overrides` is assumptions/{TICKER}/reconcile.json (context, weights)."""
    results = [json.loads(Path(p).read_text()) for p in result_paths]
    if not results:
        raise ValueError("no model results to reconcile")

    warnings: list[str] = []
    tickers = {r["ticker"] for r in results}
    if len(tickers) > 1:
        raise ValueError(f"results cover different tickers: {sorted(tickers)}")
    as_ofs = {r["as_of"] for r in results}
    if len(as_ofs) > 1:
        warnings.append(f"models ran at different as_of dates: {sorted(as_ofs)}")

    # Same input file name with different hashes = models saw different data.
    seen: dict[str, dict[str, str]] = {}
    for r in results:
        for inp in r.get("lineage", {}).get("inputs", []):
            seen.setdefault(inp["file"], {})[r["model"]] = inp["sha256"]
    for fname, by_model in sorted(seen.items()):
        if len(set(by_model.values())) > 1:
            warnings.append(f"models used different versions of {fname}: {sorted(by_model)}")

    flat = {r["model"]: _flatten(r.get("assumptions_used", {})) for r in results}
    keys = sorted({k for f in flat.values() for k in f})
    differences = []
    for k in keys:
        present = {m: f[k] for m, f in flat.items() if k in f}
        if len(present) > 1 and len({json.dumps(v, sort_keys=True) for v in present.values()}) > 1:
            differences.append({"field": k, "values": present})

    by_model = {r["model"]: r for r in results}
    profile = (detail or {}).get("profile")
    plan = method_plan(profile, sorted(by_model), overrides)
    for m in plan["methods"]:
        vps = by_model.get(m["model"], {}).get("value_per_share")
        m["value_per_share"] = vps
    blend = {k: sum(m["weight"] * m["value_per_share"][k] for m in plan["methods"] if m["weight"] > 0)
             for k in ("p10", "p50", "p90")} if any(m["weight"] > 0 for m in plan["methods"]) else None
    price = ((detail or {}).get("market") or {}).get("price")
    price_source = "market data" if price else None
    if price is None:
        price = ((by_model.get("dcf") or {}).get("details") or {}).get("market_price")
        price_source = "dcf assumptions" if price else None
    upside = {k: v / price - 1 for k, v in blend.items()} if blend and price else None

    return {
        "schema_version": COMPARISON_SCHEMA_VERSION,
        "ticker": tickers.pop(),
        "profile": profile,
        "plan": plan,
        "blend": blend,
        "price": price,
        "price_source": price_source,
        "upside": upside,
        "as_of": max(as_ofs),
        "football_field": [
            {"model": r["model"], **r["value_per_share"]}
            for r in sorted(results, key=lambda r: r["model"])
        ],
        "assumption_differences": differences,
        "warnings": warnings,
    }
