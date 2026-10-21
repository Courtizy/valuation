"""In-browser runs (Pyodide): one company, run in the visitor's browser and kept on their device.

The page's web worker loads this package and calls run(). Every request goes through
`fetch_text(url)`, which the worker implements as a synchronous request to the Cloudflare
proxy (worker/), since browsers can't call the SEC directly. Nothing is committed or
published: run() returns the visitor's own site/data files, which the page keeps in
IndexedDB and passes back in as `saved` next time, so earlier runs stay listed.

Market prices aren't fetched here (no price data passes through the proxy); the DCF values
the company on its own equity value, with Damodaran's industry beta and implied ERP.
"""
from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path
from typing import Callable

from valuation.L0_ingest.http import HttpError
from valuation.L0_ingest.market import MarketAdapter, MarketDataError
from valuation.L0_ingest.sec_sector import SecSectorAdapter
from valuation.L3_app.publish import publish
from valuation.runner.company import execute, plan
from valuation.runner.paths import Paths

ROOT = Path(__file__).resolve().parents[3]
ASSUMPTIONS = ROOT / "configs" / "public" / "assumptions"


class ProxyClient:
    """get_bytes() over the page's fetch_text(url) -> str (a sync request to the proxy)."""

    def __init__(self, fetch_text: Callable[[str], str]):
        self.fetch_text = fetch_text

    def get_bytes(self, url: str) -> bytes:
        try:
            return str(self.fetch_text(url)).encode("utf-8")
        except Exception as e:                       # a JS error or a non-2xx from the proxy
            raise HttpError(url, None, str(e)) from None


class NoPrices:
    """Stands in for Yahoo and Alpha Vantage: in the browser, prices come only from the visitor."""

    def get_bytes(self, url: str) -> bytes:
        raise HttpError(url, None, "market prices aren't fetched in the browser")


def run(ticker: str, fetch_text: Callable[[str], str], as_of: str | None = None, models: str = "dcf",
        saved: dict[str, str] | None = None, work: str = "/tmp/valuation") -> dict:
    """Run L0 -> L2 for one ticker and publish into this device's site data.

    Returns {"report": [[step, status, message], ...], "files": {path under data/: text}}."""
    as_of = as_of or date.today().isoformat()
    work_dir = Path(work)
    if work_dir.exists():
        shutil.rmtree(work_dir)
    site_data = work_dir / "site" / "data"
    for rel, text in (saved or {}).items():          # earlier runs on this device
        target = site_data / rel
        if site_data.resolve() not in target.resolve().parents:
            continue                                 # never write outside the site data folder
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    client = ProxyClient(fetch_text)
    paths = Paths(work_dir / "data", ASSUMPTIONS)
    steps = plan(ticker, [m.strip() for m in models.split(",") if m.strip()], as_of, paths,
                 lambda: SecSectorAdapter(client=client), "L2",
                 market_factory=lambda: MarketAdapter(yahoo=NoPrices(), alphavantage=NoPrices(), fred=client,
                                                      damodaran=client, av_key=""),
                 market_prices=False)
    report = [list(r) for r in execute(steps)]
    publish(work_dir / "data", work_dir / "site", "real")
    files = {str(p.relative_to(site_data)): p.read_text() for p in sorted(site_data.rglob("*.json"))}
    return {"report": report, "files": files}


def run_json(ticker: str, fetch_text: Callable[[str], str], as_of: str | None = None, models: str = "dcf",
             saved_json: str = "{}") -> str:
    """run() with JSON in and out, the simplest shape to pass across Pyodide's boundary."""
    return json.dumps(run(ticker, fetch_text, as_of, models, json.loads(saved_json or "{}")))


__all__ = ["run", "run_json", "ProxyClient", "MarketDataError"]
