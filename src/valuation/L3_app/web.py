"""In-browser runs (Pyodide): companies and sector screens, run in the visitor's browser and kept on their device.

The page's web worker loads this package and calls run() or run_sector(). Every request goes
through `fetch_text(url)`, which the worker implements as a synchronous request: to the
Cloudflare proxy (worker/) for the SEC, FRED and Damodaran, since browsers can't call the SEC
directly, and straight to Alpha Vantage when the visitor gives their own key. Nothing is
committed or published: each call returns the visitor's own site/data files, which the page
keeps in IndexedDB and passes back in as `saved` next time, so earlier runs stay listed.

`assumptions` overlays configs/public/assumptions with the visitor's own files (comps peers
picked on the site, as {"TICKER/comps.json": text}). Without an Alpha Vantage key no prices are
fetched: the DCF uses Damodaran's industry beta and implied ERP, and comps needs peer prices
typed into the peer picker.
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
from valuation.runner.company import execute, load_peers, plan
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
    """Stands in for Yahoo (and for Alpha Vantage without a key): the browser never calls Yahoo."""

    def get_bytes(self, url: str) -> bytes:
        raise HttpError(url, None, "market prices aren't fetched in the browser without an Alpha Vantage key")


def _write_under(base: Path, rel: str, text: str) -> None:
    target = base / rel
    if base.resolve() not in target.resolve().parents:
        return                                       # never write outside base
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)


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


def run(ticker: str, fetch_text: Callable[[str], str], as_of: str | None = None, models: str = "dcf",
        saved: dict[str, str] | None = None, work: str = "/tmp/valuation",
        assumptions: dict[str, str] | None = None, av_key: str = "") -> dict:
    """Run L0 -> L2 for one ticker (and its comps peers) and publish into this device's site data.

    models: comma-separated, or "auto" = DCF, plus comps when the ticker has comps peers.
    Returns {"report": [[step, status, message], ...], "files": {path under data/: text}}."""
    as_of = as_of or date.today().isoformat()
    work_dir, paths = _start(work, saved, assumptions)
    client = ProxyClient(fetch_text)
    cache = FileCache(work_dir / "cache")
    names = [m.strip() for m in models.split(",") if m.strip()]
    if names == ["auto"]:
        names = ["dcf"] + (["comps"] if load_peers(paths, ticker.upper()) else [])
    steps = plan(ticker, names, as_of, paths, lambda: SecSectorAdapter(client=client), "L2",
                 market_factory=lambda: MarketAdapter(yahoo=NoPrices(), alphavantage=client if av_key else NoPrices(),
                                                      fred=client, damodaran=client, av_key=av_key, cache=cache),
                 market_prices=bool(av_key))
    report = [list(r) for r in execute(steps)]
    return {"report": report, "files": _finish(work_dir, "real")}


def run_sector(spec: str, fetch_text: Callable[[str], str], as_of: str | None = None,
               saved: dict[str, str] | None = None, work: str = "/tmp/valuation", limit: int | None = None) -> dict:
    """Screen one sector (sector:technology, sic:3674, sic-of:AAPL, traits:...) into this device's site data."""
    as_of = as_of or date.today().isoformat()
    work_dir, paths = _start(work, saved, None)
    client = ProxyClient(fetch_text)
    try:
        out = _run_sector(spec, as_of, paths, lambda: SecSectorAdapter(client=client), SECTOR_LISTS, limit)
        report = [[f"screen {spec}", "done", out.relative_to(work_dir).as_posix()]]
    except Exception as e:                           # reported to the page, like a failed step
        report = [[f"screen {spec}", "failed", f"{type(e).__name__}: {e}"]]
    return {"report": report, "files": _finish(work_dir, "real")}


def run_json(ticker: str, fetch_text: Callable[[str], str], as_of: str | None = None, models: str = "dcf",
             saved_json: str = "{}", assumptions_json: str = "{}", av_key: str = "") -> str:
    """run() with JSON in and out, the simplest shape to pass across Pyodide's boundary."""
    return json.dumps(run(ticker, fetch_text, as_of, models, json.loads(saved_json or "{}"),
                          assumptions=json.loads(assumptions_json or "{}"), av_key=av_key or ""))


def run_sector_json(spec: str, fetch_text: Callable[[str], str], as_of: str | None = None, saved_json: str = "{}") -> str:
    return json.dumps(run_sector(spec, fetch_text, as_of, json.loads(saved_json or "{}")))


__all__ = ["run", "run_json", "run_sector", "run_sector_json", "ProxyClient", "MarketDataError"]
