"""Copy pipeline outputs into site/data and write site/data/index.json.

  python -m L3_app.publish --data-dir data --site-dir site

For every data/{TICKER}/{as_of}/ it copies company_detail.json, comparison.json
and model_results/*.json when present, and every data/sectors/{id}/{as_of}/sector.json. Raw SEC files and canonical statements
stay out of the site. The index is rebuilt from what is in site/data, so runs
published earlier are kept.
"""
from __future__ import annotations

from core.num import div as _ratio

import argparse
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

AS_OF = re.compile(r"^\d{4}-\d{2}-\d{2}$")
KEEP_RUNS = 3        # latest as-of runs kept on the site per company and per sector (older ones stay in git history)
# Periods the page shows (plus the year before, for growth); the full history is published
# alongside as company_detail_full.json for download.
SITE_PERIODS = {"annual": 11, "quarterly": 16, "ttm": 16}
SITE_ANALYSIS = {"annual": 10, "ttm": 8}


def write_json(path: Path, doc) -> None:
    """Site files are written compact: same data, about a quarter smaller than indented."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, separators=(",", ":")))


def site_slice(detail: dict) -> dict:
    """company_detail.json trimmed to the periods the page shows."""
    d = dict(detail)
    d["views"] = {k: v[-SITE_PERIODS.get(k, len(v)):] for k, v in (detail.get("views") or {}).items()}
    d["analysis"] = {k: v[-SITE_ANALYSIS.get(k, len(v)):] for k, v in (detail.get("analysis") or {}).items()}
    d["site_slice"] = {"views": SITE_PERIODS, "analysis": SITE_ANALYSIS, "full": "company_detail_full.json"}
    return d
PUBLISHED = ("company_detail.json", "comparison.json")


NOT_TICKERS = {"sectors"}   # plus anything starting with "_" (raw screens)


def _ticker_dirs(root: Path):
    return sorted(p for p in root.iterdir() if p.is_dir() and p.name not in NOT_TICKERS and not p.name.startswith("_"))


def copy_sectors(data_dir: Path, site_data: Path) -> list[str]:
    copied = []
    for f in sorted((data_dir / "sectors").glob("*/*/sector.json")):
        if not AS_OF.match(f.parent.name):
            continue
        target = site_data / "sectors" / f.parent.parent.name / f.parent.name / "sector.json"
        write_json(target, json.loads(f.read_text()))
        copied.append(str(target.relative_to(site_data)))
    return copied


def build_sector_index(site_data: Path) -> list[dict]:
    """Latest screen per sector, with its member tickers so the site can find a company's sectors."""
    out = []
    for sdir in sorted(p for p in (site_data / "sectors").glob("*") if p.is_dir()):
        runs = sorted((p for p in sdir.iterdir() if p.is_dir() and AS_OF.match(p.name) and (p / "sector.json").exists()),
                      key=lambda p: p.name, reverse=True)
        if not runs:
            continue
        doc = json.loads((runs[0] / "sector.json").read_text())
        out.append({"id": doc["id"], "label": doc["label"], "kind": doc["kind"], "as_of": runs[0].name,
                    "year": doc.get("year"), "demo": bool(doc.get("demo")),
                    "path": f"sectors/{sdir.name}/{runs[0].name}/sector.json",
                    "count": len(doc["companies"]), "members": [c["ticker"] for c in doc["companies"]],
                    "as_of_all": [p.name for p in runs]})
    out.sort(key=lambda s: (s["demo"], s["kind"] != "sic", s["label"]))
    return out


def copy_outputs(data_dir: Path, site_data: Path) -> list[str]:
    copied = []
    for tdir in _ticker_dirs(data_dir):
        for adir in sorted(p for p in tdir.iterdir() if p.is_dir() and AS_OF.match(p.name)):
            dest = site_data / tdir.name / adir.name
            files = [adir / f for f in PUBLISHED if (adir / f).exists()]
            files += sorted((adir / "model_results").glob("*.json")) if (adir / "model_results").exists() else []
            if not files:
                continue
            for f in files:
                target = dest / f.relative_to(adir)
                doc = json.loads(f.read_text())
                if f.name == "company_detail.json":
                    write_json(dest / "company_detail_full.json", doc)
                    copied.append(str((dest / "company_detail_full.json").relative_to(site_data)))
                    doc = site_slice(doc)
                write_json(target, doc)
                copied.append(str(target.relative_to(site_data)))
    return copied


def prune(site_data: Path, keep: int = KEEP_RUNS) -> list[str]:
    """Drop all but the latest `keep` as-of runs per company and per sector from the site."""
    removed = []
    roots = list(_ticker_dirs(site_data)) + ([p for p in (site_data / "sectors").iterdir() if p.is_dir()]
                                             if (site_data / "sectors").exists() else [])
    for root in roots:
        runs = sorted((p for p in root.iterdir() if p.is_dir() and AS_OF.match(p.name)), reverse=True)
        for old in runs[keep:]:
            shutil.rmtree(old)
            removed.append(str(old.relative_to(site_data)))
    return removed


def build_index(site_data: Path) -> dict:
    companies = []
    for tdir in _ticker_dirs(site_data):
        runs = []
        name, demo = tdir.name, False
        for adir in sorted((p for p in tdir.iterdir() if p.is_dir() and AS_OF.match(p.name)), reverse=True):
            detail = adir / "company_detail.json"
            if not detail.exists():
                continue
            doc = json.loads(detail.read_text())
            name = doc.get("entity", {}).get("name") or name
            demo = demo or bool(doc.get("demo"))
            runs.append({
                "as_of": adir.name,
                "detail": f"{tdir.name}/{adir.name}/company_detail.json",
                "full": (f"{tdir.name}/{adir.name}/company_detail_full.json"
                         if (adir / "company_detail_full.json").exists() else None),
                "comparison": (f"{tdir.name}/{adir.name}/comparison.json"
                               if (adir / "comparison.json").exists() else None),
                "models": sorted(p.stem for p in (adir / "model_results").glob("*.json"))
                if (adir / "model_results").exists() else [],
                "latest": doc.get("latest", {}),
            })
        if runs:
            companies.append({"ticker": tdir.name, "name": name, "demo": demo, "runs": runs})
    companies.sort(key=lambda c: (c["demo"], c["ticker"]))
    return {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "companies": companies,
            "sectors": build_sector_index(site_data)}


def concept_labels() -> dict:
    """Display names for the site, from the L1 registry (the one source of labels)."""
    from L1_detail.registry import load_registry
    return {c.id: {"name": c.display_name, "statement": c.statement}
            for c in load_registry().concepts.values()}


def _classify(sic):
    from L1_detail.taxonomy import load
    c = load().classify(sic) if sic else None
    return {k: c[k] for k in ("sector", "group", "industry")} if c else None




def company_card(site_data: Path, ticker: str, run: dict) -> dict:
    """Traits, rates and (when a price is known) multiples for the similar-companies table."""
    detail = json.loads((site_data / run["detail"]).read_text())
    prof = detail.get("profile") or {}
    vec = prof.get("vector") or {}
    views = detail.get("views") or {}
    ttm = (views.get("ttm") or views.get("annual") or [{}])[-1].get("values", {})
    dcf_path = site_data / ticker / run["as_of"] / "model_results" / "dcf.json"
    dcf = json.loads(dcf_path.read_text()) if dcf_path.exists() else {}
    d = dcf.get("details") or {}
    price = ((detail.get("market") or {}).get("price")) or d.get("market_price")
    shares = (d.get("bridge") or {}).get("shares") or ttm.get("shares_year_end")
    debt = (ttm.get("short_term_debt") or 0) + (ttm.get("long_term_debt") or 0)
    cash = ttm.get("cash_and_marketable_securities") or 0
    mcap = price * shares if price and shares else None
    ev = mcap + debt - cash if mcap is not None else None
    equity = ttm.get("all_equity_balance")
    return {
        "ticker": ticker, "name": detail.get("entity", {}).get("name", ticker), "demo": bool(detail.get("demo")),
        "sic": detail.get("entity", {}).get("sic"), "sic_description": detail.get("entity", {}).get("sic_description"),
        "classification": _classify(detail.get("entity", {}).get("sic")),
        "as_of": run["as_of"], "period": prof.get("as_of_period"),
        "traits": {k: v["label"] for k, v in (prof.get("traits") or {}).items()},
        "vector": vec,
        "rates": {"revenue_cagr": vec.get("revenue_cagr"), "operating_margin": vec.get("operating_margin"),
                  "rnoa": vec.get("rnoa"), "capex_to_sales": vec.get("capex_to_sales"),
                  "debt_to_ebitda": vec.get("debt_to_ebitda"),
                  "wacc": (d.get("rates") or {}).get("wacc"), "beta": (d.get("rates") or {}).get("beta_levered_observed")},
        "market": {"price": price, "market_cap": mcap, "enterprise_value": ev},
        "multiples": {"pe": _ratio(mcap, ttm.get("net_income")), "ev_ebitda": _ratio(ev, ttm.get("ebitda")),
                      "ev_sales": _ratio(ev, ttm.get("revenue")), "pb": _ratio(mcap, equity),
                      "fcf_yield": _ratio(ttm.get("free_cash_flow"), mcap)},
    }


def add_rankings(site_data: Path, cards: list[dict], sectors: list[dict]) -> None:
    """card["similar"]: the 10 closest published companies; card["peers"][sector_id]:
    the 25 closest members of each sector the company belongs to (same ranking)."""
    from L3_app.similar import from_card, rank
    pool = [from_card(c) for c in cards]
    docs = {}
    for c, me in zip(cards, pool):
        c["similar"] = rank(me, pool, 10)
        c["peers"] = {}
        for sec in sectors:
            if c["ticker"] not in sec["members"]:
                continue
            if sec["id"] not in docs:
                docs[sec["id"]] = json.loads((site_data / sec["path"]).read_text())["companies"]
            rows = docs[sec["id"]]
            own = next((r for r in rows if r["ticker"] == c["ticker"]), me)
            c["peers"][sec["id"]] = rank(own, rows, 25)


def publish(data_dir: Path, site_dir: Path) -> dict:
    site_data = site_dir / "data"
    site_data.mkdir(parents=True, exist_ok=True)
    copied = (copy_outputs(data_dir, site_data) + copy_sectors(data_dir, site_data)) if data_dir.exists() else []
    removed = prune(site_data)
    index = build_index(site_data)
    (site_data / "index.json").write_text(json.dumps(index, indent=2))
    (site_data / "concepts.json").write_text(json.dumps(concept_labels(), indent=2))
    from L1_detail.taxonomy import DEFAULT_PATH
    shutil.copy2(DEFAULT_PATH, site_data / "taxonomy.json")
    cards = [company_card(site_data, c["ticker"], c["runs"][0]) for c in index["companies"]]
    add_rankings(site_data, cards, index.get("sectors") or [])
    (site_data / "companies.json").write_text(json.dumps({"companies": cards}, indent=2))
    return {"copied": copied, "removed": removed, "companies": [c["ticker"] for c in index["companies"]]}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="L3_app.publish")
    p.add_argument("--data-dir", type=Path, default=Path("data"))
    p.add_argument("--site-dir", type=Path, default=Path("site"))
    args = p.parse_args(argv)
    out = publish(args.data_dir, args.site_dir)
    print(f"copied {len(out['copied'])} file(s); index lists {', '.join(out['companies']) or 'nothing'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
