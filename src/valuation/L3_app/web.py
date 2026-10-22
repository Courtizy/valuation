"""In-browser runs (Pyodide): companies and sector screens, run in the visitor's browser and kept on their device.

The page's web worker loads this package and calls run() or run_sector(). Every request goes
through `fetch_text(url)`, which the worker implements as a synchronous request: to the
Cloudflare proxy (worker/) for the SEC, FRED, Damodaran and Yahoo, since browsers can't call
them directly, and straight to Alpha Vantage or Finnhub when the visitor gives their own key.
Yahoo (the page passes yahoo=True) supplies prices and beta, and statement items the filings
lack (L1_detail/backfill.py, marked y). Nothing is committed or published: each call returns the
visitor's own site/data files, which the page keeps in IndexedDB and passes back in as `saved`
next time, so earlier runs stay listed.

A company run with models="auto" is the whole pull: company detail, the DCF, and comps against
peers picked automatically from its sector (auto_peers) unless the visitor already chose some.
`assumptions` overlays configs/public/assumptions with the visitor's own files (comps peers
picked on the site, as {"TICKER/comps.json": text}).

The SEC refuses its company-lists-by-industry page (browse-edgar) to the proxy, so sector
screens read the lists the weekly Refresh publishes (site/data/sic_members.json), passed in
as `sic_lists`.
"""
from __future__ import annotations

import json
import re
import shutil
from datetime import date
from pathlib import Path
from typing import Callable

from valuation.L0_ingest.cache import FileCache
from valuation.L0_ingest.http import HttpError
from valuation.L0_ingest.market import MarketAdapter, MarketDataError
from valuation.L0_ingest.sec_sector import SecSectorAdapter
from valuation.L3_app.publish import publish
from valuation.L3_app.similar import pick_peers
from valuation.runner.company import DEAL_MODELS, execute, has_deal, has_deal_list, load_peers, plan
from valuation.runner.paths import Paths
from valuation.runner.sector import run_sector as _run_sector

ROOT = Path(__file__).resolve().parents[3]
ASSUMPTIONS = ROOT / "configs" / "public" / "assumptions"
SECTOR_LISTS = ROOT / "configs" / "public" / "sectors"


class ProxyClient:
    """get_bytes() over the page's fetch_text(url) -> str (a sync request to the proxy)."""

    def __init__(self, fetch_text: Callable[[str], str]):
        self.fetch_text = fetch_text

    def get_bytes(self, url: str) -> bytes:
        try:
            return str(self.fetch_text(url)).encode("utf-8")
        except Exception as e:                       # a JS error, or "404 from the proxy …" (pyworker.js)
            m = re.search(r"\b([1-5]\d\d) from the proxy", str(e))
            raise HttpError(url, int(m.group(1)) if m else None, str(e)) from None


class NoPrices:
    """Stands in for a price source this run may not use (Yahoo when not asked for, a provider without a key)."""

    def get_bytes(self, url: str) -> bytes:
        raise HttpError(url, None, "this price source isn't used in this browser run")


def _write_under(base: Path, rel: str, text: str) -> None:
    target = base / rel
    if base.resolve() not in target.resolve().parents:
        return                                       # never write outside base
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)


def _sector_adapter(client, sic_lists: dict | None):
    return lambda: SecSectorAdapter(client=client, sic_lists=sic_lists)


def _explain(e: Exception) -> str:
    """A failed screen, with what to do when it's the EDGAR page the SEC refuses to the proxy."""
    msg = f"{type(e).__name__}: {e}"
    if isinstance(e, HttpError) and "browse-edgar" in str(e):
        return ("the SEC doesn't let the proxy read its company lists by industry code, and the site hasn't "
                "published them yet; the weekly Refresh does, and screens work here after that.")
    return msg


def _start(work: str, saved: dict[str, str] | None, assumptions: dict[str, str] | None) -> tuple[Path, Paths]:
    """A fresh work folder holding the device's earlier site data and its assumptions overlay."""
    work_dir = Path(work)
    if work_dir.exists():
        shutil.rmtree(work_dir)
    for rel, text in (saved or {}).items():          # earlier runs on this device
        _write_under(work_dir / "site" / "data", rel, text)
    mine = work_dir / "assumptions"
    shutil.copytree(ASSUMPTIONS, mine)
    for rel, text in (assumptions or {}).items():   # the visitor's own comps peers
        _write_under(mine, rel, text)
    return work_dir, Paths(work_dir / "data", mine)


def _finish(work_dir: Path, market: str) -> dict[str, str]:
    publish(work_dir / "data", work_dir / "site", market)
    site_data = work_dir / "site" / "data"
    return {p.relative_to(site_data).as_posix(): p.read_text() for p in sorted(site_data.rglob("*.json"))}


def _screens_with(ticker: str, work_dir: Path, screens: list[str] | None) -> list[dict]:
    """Sector screens that include the ticker: this device's (newest first), then the published
    ones the page passed in."""
    mine = sorted((work_dir / "site" / "data" / "sectors").glob("*/*/sector.json"), key=lambda p: p.parent.name, reverse=True)
    docs = [json.loads(p.read_text()) for p in mine] + [json.loads(t) for t in screens or []]
    return [d for d in docs if any(c.get("ticker") == ticker for c in d.get("companies") or [])]


def auto_peers(ticker: str, as_of: str, work_dir: Path, paths: Paths, client, screens: list[str] | None,
               sic_lists: dict | None = None) -> list:
    """Pick comps peers for a ticker that has none: from a sector screen that includes it (this
    device's, else a published one), else screen its sector first. Writes comps.json into the
    run's assumptions and returns a report row."""
    try:
        found = _screens_with(ticker, work_dir, screens)
        how = "from the sector screen"
        if not found:
            out = _run_sector(f"sic-of:{ticker}", as_of, paths, _sector_adapter(client, sic_lists), SECTOR_LISTS)
            found, how = [json.loads(out.read_text())], "screened its sector, then picked"
        pick = next((p for p in (pick_peers(d, ticker) for d in found) if p), None)
        if not pick:
            return ["pick peers", "warning", f"no peers found for {ticker} in {found[0].get('label')}"]
        doc = {"multiples": ["ev_ebitda", "ev_sales"], "range": "auto", "peers": [{"ticker": p["ticker"]} for p in pick["peers"]],
               "closest": [{"ticker": p["ticker"]} for p in pick["closest"]],
               "sources": {"peers": f"picked automatically: the {len(pick['peers'])} nearest in size in {pick['sector']} "
                                    f"({pick['level']}: {pick['label']}) on {as_of}; change them in the peer picker",
                           "closest": f"picked automatically: the {len(pick['closest'])} closest on growth, margins, cash-flow "
                                      f"stability, capital intensity, leverage and size anywhere in {pick['sector']} on {as_of}"}}
        target = paths.model_assumptions(ticker, "comps")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(doc, indent=2))
        return ["pick peers", "done", f"{how}: sector set {', '.join(p['ticker'] for p in pick['peers'])}; "
                                      f"closest match {', '.join(p['ticker'] for p in pick['closest'])}"]
    except Exception as e:                           # comps is skipped; the DCF still runs
        return ["pick peers", "warning", f"comps skipped: {_explain(e)}"]


def run(ticker: str, fetch_text: Callable[[str], str], as_of: str | None = None, models: str = "dcf",
        saved: dict[str, str] | None = None, work: str = "/tmp/valuation",
        assumptions: dict[str, str] | None = None, av_key: str = "", finnhub_key: str = "",
        yahoo: bool = False, screens: list[str] | None = None, sic_lists: dict | None = None) -> dict:
    """Run L0 -> L2 for one ticker (and its comps peers) and publish into this device's site data.

    models: comma-separated, or "auto" = DCF and comps, picking comps peers first when the ticker
    has none (auto_peers). screens: published sector.json texts that may include the ticker;
    sic_lists: the site's published EDGAR lists by SIC code (sic_members.json "sic").
    Returns {"report": [[step, status, message], ...], "files": {path under data/: text},
    "assumptions": {"TICKER/comps.json": text} when peers were picked, for the page to keep}."""
    as_of = as_of or date.today().isoformat()
    work_dir, paths = _start(work, saved, assumptions)
    client = ProxyClient(fetch_text)
    cache = FileCache(work_dir / "cache")
    names = [m.strip() for m in models.split(",") if m.strip()]
    first, picked = [], {}
    if names == ["auto"]:
        t = ticker.upper()
        if not load_peers(paths, t):
            first.append(auto_peers(t, as_of, work_dir, paths, client, screens, sic_lists))
            if first[-1][1] == "done":
                picked = {f"{t}/comps.json": paths.model_assumptions(t, "comps").read_text()}
        names = (["dcf"] + (["comps"] if load_peers(paths, t) else [])
                 + (["precedents"] if has_deal_list(paths, t) else [])
                 + (list(DEAL_MODELS) if has_deal(paths, t) else []))
    steps = plan(ticker, names, as_of, paths, _sector_adapter(client, sic_lists), "L2",
                 market_factory=lambda: MarketAdapter(yahoo=client if yahoo else NoPrices(),
                                                      alphavantage=client if av_key else NoPrices(),
                                                      finnhub=client if finnhub_key else NoPrices(),
                                                      fred=client, damodaran=client, av_key=av_key,
                                                      finnhub_key=finnhub_key, cache=cache),
                 market_prices=bool(av_key or finnhub_key or yahoo))
    report = first + [list(r) for r in execute(steps)]
    for r in report:                                 # say what to do, not just what failed
        if r[0] == "model comps" and "no peer has a price" in r[2]:
            r[2] = ("comps needs peer prices, and none of Yahoo, Alpha Vantage or Finnhub had them: add a key under "
                    "Run ▸ Settings, or type prices in the peer picker and press Run Comps")
    return {"report": report, "files": _finish(work_dir, "real"), "assumptions": picked}


def run_sector(spec: str, fetch_text: Callable[[str], str], as_of: str | None = None,
               saved: dict[str, str] | None = None, work: str = "/tmp/valuation", limit: int | None = None,
               sic_lists: dict | None = None) -> dict:
    """Screen one sector (sector:technology, sic:3674, sic-of:AAPL, traits:...) into this device's site data."""
    as_of = as_of or date.today().isoformat()
    work_dir, paths = _start(work, saved, None)
    client = ProxyClient(fetch_text)
    try:
        out = _run_sector(spec, as_of, paths, _sector_adapter(client, sic_lists), SECTOR_LISTS, limit)
        report = [[f"screen {spec}", "done", out.relative_to(work_dir).as_posix()]]
    except Exception as e:                           # reported to the page, like a failed step
        report = [[f"screen {spec}", "failed", _explain(e)]]
    return {"report": report, "files": _finish(work_dir, "real")}


def run_json(ticker: str, fetch_text: Callable[[str], str], as_of: str | None = None, models: str = "dcf",
             saved_json: str = "{}", assumptions_json: str = "{}", av_key: str = "", finnhub_key: str = "",
             yahoo: bool = False, screens_json: str = "[]", sic_json: str = "{}") -> str:
    """run() with JSON in and out, the simplest shape to pass across Pyodide's boundary."""
    return json.dumps(run(ticker, fetch_text, as_of, models, json.loads(saved_json or "{}"),
                          assumptions=json.loads(assumptions_json or "{}"), av_key=av_key or "",
                          finnhub_key=finnhub_key or "", yahoo=bool(yahoo), screens=json.loads(screens_json or "[]"),
                          sic_lists=json.loads(sic_json or "{}")))


def run_sector_json(spec: str, fetch_text: Callable[[str], str], as_of: str | None = None, saved_json: str = "{}",
                    sic_json: str = "{}") -> str:
    return json.dumps(run_sector(spec, fetch_text, as_of, json.loads(saved_json or "{}"), sic_lists=json.loads(sic_json or "{}")))


__all__ = ["run", "run_json", "run_sector", "run_sector_json", "ProxyClient", "MarketDataError"]
