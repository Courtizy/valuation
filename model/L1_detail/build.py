"""L1 stage 2: canonical_statements.json (+ raw_market.json) -> company_detail.json.

  1. Frequency views (periods.py): annual, quarterly (Q4 = FY - 9M YTD,
     Q2/Q3 from YTD where not reported alone), TTM (four contiguous quarters).
  2. Analysis (analysis.py) on every 12-month period (annual and TTM):
     managerial balance sheet, reformulated statements, ratios in both
     frameworks, risk metrics and signals. Average-based ratios use the period
     one year earlier; the first year has none.
  3. Market join (raw_market.json from L0_ingest/market.py, when given): price,
     market cap (price x latest SEC share count), 5-year monthly beta and a
     market WACC estimate (core/market.py) with the risk-free rate. The statement
     date and the price date are recorded separately. The price history itself
     stays in raw_market.json; only derived figures go into company detail.

Classification (operating vs financial) comes from classification.json,
overridden by a sector pack's l1.classification block.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from core.market import beta as _beta, wacc_estimate
from lineage import lineage_block

from .analysis import _one_year_apart, analyze_view, load_classification
from .backfill import backfill_records
from .periods import build_views
from .forecast import trend_case
from .profile import build_profile, load_rules
from .registry import load_registry

DETAIL_SCHEMA_VERSION = "0.1.0"


def _latest(views: dict, key: str):
    for view in ("quarterly", "ttm", "annual"):
        for p in reversed(views.get(view) or []):
            if p["values"].get(key) is not None:
                return p["values"][key]
    return None


def _latest_share_count(records: list[dict], as_of: str):
    """Most recent shares-outstanding fact on or before as_of. The cover-page count (dei) is
    dated after the period end, so it never lands in a statement view, but it is the newest."""
    rows = [r for r in records or [] if r.get("concept") == "shares_year_end" and r.get("value") and (r.get("end") or "") <= as_of]
    return max(rows, key=lambda r: r["end"])["value"] if rows else None


def _market_block(raw_market: dict | None, as_of: str, views: dict, risk_free: dict | None = None,
                  records: list[dict] | None = None) -> dict | None:
    """Price, market cap, beta and a WACC estimate. Share count: raw_market's, else the newest filed count."""
    if not raw_market:
        return None
    price, price_date = raw_market.get("price"), raw_market.get("price_date")
    if price_date and price_date > as_of:
        raise ValueError(f"market price date {price_date} is after as_of {as_of}")
    shares = (raw_market.get("shares_outstanding") or _latest_share_count(records, as_of)
              or _latest(views, "shares_year_end") or _latest(views, "shares_fully_diluted_average"))
    mcap = price * shares if price is not None and shares else None
    b = _beta(raw_market.get("monthly") or [], (raw_market.get("index") or {}).get("monthly") or [])
    block = {"price": price, "price_date": price_date, "currency": raw_market.get("currency"),
             "shares_outstanding": shares, "market_cap": mcap,
             "beta": b and {**b, "index": (raw_market.get("index") or {}).get("symbol")},
             "source": raw_market.get("source"), "fallback": bool(raw_market.get("fallback")),
             "check": raw_market.get("check"), "wacc": None}
    if b and mcap and risk_free and risk_free.get("value") is not None:
        ttm = (views.get("ttm") or views.get("annual") or [{}])[-1].get("values", {})
        debt = (ttm.get("short_term_debt") or 0) + (ttm.get("long_term_debt") or 0)
        block["wacc"] = {**wacc_estimate(beta_value=b["value"], risk_free=risk_free["value"], market_cap=mcap, debt=debt,
                                         interest_expense=ttm.get("interest_expense"), tax_rate=ttm.get("effective_tax_rate")),
                         "risk_free_date": risk_free.get("date"), "risk_free_series": risk_free.get("series")}
    return block


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
                 lineage: dict | None = None, risk_free: dict | None = None) -> dict:
    date.fromisoformat(as_of)
    if canonical.get("as_of") and canonical["as_of"] != as_of:
        raise ValueError(f"canonical as_of {canonical['as_of']} != {as_of}")
    reg = load_registry()
    cfg = load_classification(((pack or {}).get("l1") or {}).get("classification"))
    # gaps in the filings filled from Yahoo fundamentals (private runs; raw_market carries them)
    backfill = backfill_records(canonical["records"], (raw_market or {}).get("fundamentals"), reg, as_of)
    records = canonical["records"] + backfill
    views = build_views(records, reg)
    if not any(p["values"].get("revenue") for p in views["annual"] + views["ttm"]):
        basis = canonical.get("reporting_basis") or {}
        if basis.get("taxonomy") not in (None, "us-gaap") or basis.get("currency") not in (None, "USD"):
            raise ValueError(
                f"no usable statements: this company reports under {basis['taxonomy']} in {basis['currency']} "
                "(typical of a 20-F foreign filer). Only us-gaap in USD is supported so far.")
        raise ValueError("no usable statements: no 12-month revenue found in the filings")
    market = _market_block(raw_market, as_of, views, risk_free, records)

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

    doc = {
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
    doc["risk_free"] = risk_free          # FRED rate, also present in showcase mode (no prices)
    doc["shares_outstanding"] = _latest_share_count(records, as_of)   # newest filed count (else Yahoo backup)
    doc["backfill"] = [{"concept": r["concept"], "end": r["end"], "months": r["months"], "source": r["source"]["tags"][0]}
                       for r in backfill]
    if backfill:
        doc["warnings"].append(f"{len(backfill)} value(s) the filings lack were filled from Yahoo fundamentals (marked y)")
    from .taxonomy import load as load_taxonomy
    doc["sector_beta"] = load_taxonomy().typical_beta((canonical.get("entity") or {}).get("sic"))
    doc["profile"] = build_profile(doc, load_rules(((pack or {}).get("l1") or {}).get("profile_rules")))
    doc["projection"] = trend_case(doc)
    return doc


def run(canonical: Path, raw_market: Path | None, as_of: str, out_path: Path,
        pack: dict | None = None, risk_free: Path | None = None) -> Path:
    doc = json.loads(Path(canonical).read_text())
    if doc.get("stage") != "L1.normalize":
        raise ValueError(f"{canonical} is not a canonical_statements.json")
    raw_market = raw_market if raw_market and Path(raw_market).exists() else None
    risk_free = risk_free if risk_free and Path(risk_free).exists() else None
    inputs = [canonical] + ([raw_market] if raw_market else []) + ([risk_free] if risk_free else [])
    market = json.loads(Path(raw_market).read_text()) if raw_market else None
    rf = json.loads(Path(risk_free).read_text()) if risk_free else None
    detail = build_detail(doc, as_of, market, pack, lineage_block(as_of, inputs), rf)
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
