"""L1 stage 2: canonical_statements.json (+ raw_market.json) -> company_detail.json.

  1. Frequency views (periods.py): annual, quarterly (Q4 = FY - 9M YTD,
     Q2/Q3 from YTD where not reported alone), TTM (four contiguous quarters).
  2. Analysis (analysis.py) on every 12-month period (annual and TTM):
     managerial balance sheet, reformulated statements, ratios in both
     frameworks, risk metrics and signals. Average-based ratios use the period
     one year earlier; the first year has none.
  3. Market join: price-based items use raw_market.json when given. The
     statement date and the price date are recorded separately, so prices can
     refresh without rerunning stage 1.

Classification (operating vs financial) comes from classification.json,
overridden by a sector pack's l1.classification block.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from lineage import lineage_block

from .analysis import _one_year_apart, analyze_view, load_classification
from .periods import build_views
from .registry import load_registry

DETAIL_SCHEMA_VERSION = "0.1.0"


def _market_block(raw_market: dict | None, as_of: str) -> dict | None:
    """Accepts {"price", "price_date", "shares_outstanding"[, "source"]}; the
    market adapter (not built yet) will write this shape."""
    if not raw_market:
        return None
    price, shares = raw_market.get("price"), raw_market.get("shares_outstanding")
    price_date = raw_market.get("price_date")
    if price_date and price_date > as_of:
        raise ValueError(f"market price date {price_date} is after as_of {as_of}")
    return {"price": price, "price_date": price_date, "shares_outstanding": shares,
            "market_cap": price * shares if price is not None and shares is not None else None,
            "source": raw_market.get("source")}


def _ttm_priors(ttm: list[dict], annual: list[dict]) -> dict:
    """end date -> values of the 12-month period ending about a year earlier."""
    candidates = {p["end"]: p["values"] for p in annual}
    candidates.update({p["end"]: p["values"] for p in ttm})
    out = {}
    for p in ttm:
        prior = [e for e in candidates if _one_year_apart(e, p["end"])]
        if prior:
            out[p["end"]] = candidates[min(prior, key=lambda e: abs(
                (date.fromisoformat(p["end"]) - date.fromisoformat(e)).days - 365))]
    return out


def build_detail(canonical: dict, as_of: str, raw_market: dict | None = None, pack: dict | None = None,
                 lineage: dict | None = None) -> dict:
    date.fromisoformat(as_of)
    if canonical.get("as_of") and canonical["as_of"] != as_of:
        raise ValueError(f"canonical as_of {canonical['as_of']} != {as_of}")
    reg = load_registry()
    cfg = load_classification(((pack or {}).get("l1") or {}).get("classification"))
    views = build_views(canonical["records"], reg)
    market = _market_block(raw_market, as_of)

    statement_date = max((p["end"] for p in views["quarterly"] + views["annual"]), default=None)
    market_cap_at = {statement_date: market["market_cap"]} if market and market["market_cap"] else None

    warnings = []
    if not views["annual"]:
        warnings.append("no 12-month periods found; annual analysis is empty")
    if not views["ttm"]:
        warnings.append("no four contiguous quarters; TTM view is empty")
    latest_annual = views["annual"][-1] if views["annual"] else None
    if latest_annual and not any(latest_annual["values"].get(k) is not None
                                 for k in ("interest_expense", "interest_income")):
        warnings.append("interest not tagged in the latest year; NFE treated as zero in reformulation")

    return {
        "schema_version": DETAIL_SCHEMA_VERSION,
        "stage": "L1.build",
        "as_of": as_of,
        "entity": canonical.get("entity", {}),
        "registry_version": reg.version,
        "lineage": lineage or {"as_of": as_of, "inputs": []},
        "statement_date": statement_date,
        "market": market,
        "classification": cfg,
        "views": views,
        "analysis": {
            "annual": analyze_view(views["annual"], cfg, market_cap_at),
            "ttm": analyze_view(views["ttm"], cfg, market_cap_at,
                                prior_lookup=_ttm_priors(views["ttm"], views["annual"])),
        },
        "latest": {
            "annual": latest_annual["label"] if latest_annual else None,
            "ttm": views["ttm"][-1]["label"] if views["ttm"] else None,
        },
        "warnings": warnings,
    }


def run(canonical: Path, raw_market: Path | None, as_of: str, out_path: Path,
        pack: dict | None = None) -> Path:
    doc = json.loads(Path(canonical).read_text())
    if doc.get("stage") != "L1.normalize":
        raise ValueError(f"{canonical} is not a canonical_statements.json")
    inputs = [canonical] + ([raw_market] if raw_market else [])
    market = json.loads(Path(raw_market).read_text()) if raw_market else None
    detail = build_detail(doc, as_of, market, pack, lineage_block(as_of, inputs))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(detail, indent=2))
    return out_path


def validate_detail(doc: dict) -> list[str]:
    errors = []
    required = {"schema_version": str, "stage": str, "as_of": str, "entity": dict, "lineage": dict,
                "classification": dict, "views": dict, "analysis": dict, "latest": dict, "warnings": list}
    for k, typ in required.items():
        if not isinstance(doc.get(k), typ):
            errors.append(f"{k} missing or not {typ.__name__}")
    if errors:
        return errors
    if doc["schema_version"] != DETAIL_SCHEMA_VERSION:
        errors.append(f"schema_version {doc['schema_version']!r} != {DETAIL_SCHEMA_VERSION!r}")
    for view in ("annual", "quarterly", "ttm"):
        periods = doc["views"].get(view)
        if not isinstance(periods, list):
            errors.append(f"views.{view} missing")
            continue
        ends = [p.get("end") for p in periods]
        if ends != sorted(ends):
            errors.append(f"views.{view} not sorted by end date")
        for i, p in enumerate(periods):
            for k in ("label", "start", "end", "values", "methods"):
                if k not in p:
                    errors.append(f"views.{view}[{i}].{k} missing")
            if p.get("end", "") > doc["as_of"]:
                errors.append(f"views.{view}[{i}] ends after as_of")
    return errors
