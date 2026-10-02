"""Cross-model reconciliation. Reads model_results/*.json; imports no model.

Builds comparison.json with:
  - each model's value range (football-field data)
  - consistency warnings: different as_of dates or different input files
  - assumption differences: fields present in 2+ models whose values differ,
    which is how a value gap gets split into "inputs" vs "method"
"""
from __future__ import annotations

import json
from pathlib import Path

COMPARISON_SCHEMA_VERSION = "0.1.0"


def _flatten(d: dict, prefix: str = "") -> dict:
    out = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flatten(v, key + "."))
        else:
            out[key] = v
    return out


def build_comparison(result_paths: list[str | Path]) -> dict:
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

    return {
        "schema_version": COMPARISON_SCHEMA_VERSION,
        "ticker": tickers.pop(),
        "as_of": max(as_ofs),
        "football_field": [
            {"model": r["model"], **r["value_per_share"]}
            for r in sorted(results, key=lambda r: r["model"])
        ],
        "assumption_differences": differences,
        "warnings": warnings,
    }
