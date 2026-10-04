"""Private door: the same pipeline on your own inputs, with real market data, kept on your machine.

    python app/run_private.py                         # private/inputs.json
    python app/run_private.py --config private/inputs.json
    python -m http.server -d private/site             # then open http://localhost:8000

Reads private/inputs.json ({"tickers", "models", "as_of", "market"}), uses
private/assumptions/{TICKER}/*.json before configs/public/assumptions, writes pipeline outputs
to private/data/ and a local copy of the site to private/site/ with real market figures
(Yahoo, checked against Alpha Vantage when ALPHAVANTAGE_API_KEY is set). Everything under
private/ is gitignored. Same engine and seeds as the public site.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from valuation.L0_ingest.cache import FileCache  # noqa: E402
from valuation.L0_ingest.market import MarketAdapter  # noqa: E402
from valuation.L0_ingest.sec_sector import SecSectorAdapter  # noqa: E402
from valuation.L3_app.publish import publish  # noqa: E402
from valuation.runner import Paths, execute, plan  # noqa: E402

PRIVATE = ROOT / "private"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--config", type=Path, default=PRIVATE / "inputs.json")
    args = p.parse_args(argv)
    if not args.config.exists():
        print(f"no {args.config}: copy private/inputs.example.json to private/inputs.json and edit it", file=sys.stderr)
        return 2
    cfg = json.loads(args.config.read_text())
    as_of = cfg.get("as_of") or date.today().isoformat()
    scope = cfg.get("market", "all")
    paths = Paths(PRIVATE / "data", PRIVATE / "assumptions", fallback=ROOT / "configs" / "public" / "assumptions")
    sec_cache, market_cache = FileCache(ROOT / ".cache" / "sec"), FileCache(ROOT / ".cache" / "market", ttl_seconds=6 * 3600)
    ok = True
    for t in cfg.get("tickers", []):
        steps = plan(t, cfg.get("models", ["dcf"]), as_of, paths, lambda: SecSectorAdapter(cache=sec_cache),
                     market_factory=None if scope == "none" else (lambda: MarketAdapter(cache=market_cache)),
                     market_prices=scope == "all")
        for name, status, msg in execute(steps):
            print(f"{status:<16} {name}" + (f"  ({msg})" if msg else ""))
            ok &= status in ("done", "warning")
    site = PRIVATE / "site"
    for part in ("index.html", "assets"):
        src, dst = ROOT / "site" / part, site / part
        if dst.exists():
            shutil.rmtree(dst) if dst.is_dir() else dst.unlink()
        (shutil.copytree if src.is_dir() else shutil.copy2)(src, dst)
    if (site / "brand").exists():
        shutil.rmtree(site / "brand")
    for part in ("css", "js", "icons"):
        shutil.copytree(ROOT / "brand" / part, site / "brand" / part)
    publish(PRIVATE / "data", site, "real")
    print(f"private site: python -m http.server -d {site.relative_to(ROOT)}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
