"""Build every sector and company in configs/public/universe.json (the weekly Refresh workflow).

    python scripts/refresh_universe.py --as-of 2026-10-21 --market risk-free

Each company runs the DCF, plus comps when configs/public/assumptions/{TICKER}/comps.json
exists. One failure doesn't stop the rest; the summary lists them, and the exit code is
non-zero only when nothing at all was built.

Companies without a hand-picked comps.json get peers picked automatically, once the sector screens
are built (auto_comps): the sector set from the screen the company is in, nearest on size and
margin, and the closest set on the value drivers (growth and margin, in the comps stoplight's
tolerances) from every screen, so a like company in another sector can qualify. The picks go
into a copy of the assumptions (.cache/assumptions/{as_of}); configs/public is never written.

Two guards keep one slow source from using up the job's 90 minutes:
- The SIC lists stop after SIC_BUDGET_MINUTES (EDGAR's company-list pages stalled the whole run on 2026-11-16).
- The risk-free rate is fetched once before the companies. If FRED can't be reached, the companies are
  skipped at once and keep their last published results: every DCF needs the rate, and fetching it per
  company cost about two minutes each (2026-10-26 and 2026-11-02).
- Damodaran's industry betas and ERP are fetched once too. They are optional (the DCF falls back to the
  taxonomy's sector beta and the default ERP), so if the site is down the companies still run, with
  --no-damodaran so none of them retries it.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from valuation.runner.cli import main as pipeline  # noqa: E402
from valuation.runner.paths import Paths  # noqa: E402

UNIVERSE = ROOT / "configs" / "public" / "universe.json"
ASSUMPTIONS = ROOT / "configs" / "public" / "assumptions"
SIC_BUDGET_MINUTES = 20


def fetch_risk_free(as_of: str, data_dir: Path = Path("data"), cache_dir: Path = Path(".cache/market")) -> None:
    """Write data/_market/{as_of}/risk_free.json once, where each company's run looks for it first.
    Raises MarketDataError when FRED can't be reached."""
    from valuation.L0_ingest.cache import FileCache
    from valuation.L0_ingest.market import MarketAdapter
    out = Paths(data_dir, ASSUMPTIONS).risk_free(as_of)
    if out.exists():
        return
    rf = MarketAdapter(cache=FileCache(cache_dir, ttl_seconds=6 * 3600)).risk_free(as_of)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rf, indent=2))


def fetch_damodaran(as_of: str, data_dir: Path = Path("data"), cache_dir: Path = Path(".cache/market")) -> None:
    """Write data/_market/{as_of}/damodaran.json once, where each company's run looks for it first.
    Raises when Damodaran's pages can't be read."""
    from valuation.L0_ingest.cache import FileCache
    from valuation.L0_ingest.market import MarketAdapter
    out = Paths(data_dir, ASSUMPTIONS).damodaran(as_of)
    if out.exists():
        return
    doc = MarketAdapter(cache=FileCache(cache_dir, ttl_seconds=6 * 3600)).damodaran(as_of)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2))


def auto_comps(tickers: list[str], as_of: str, data_dir: Path = Path("data"), source: Path = ASSUMPTIONS,
               out: Path | None = None) -> tuple[Path, dict[str, str]]:
    """Copy the assumptions and add a comps.json for each ticker that has none, picked from this
    run's sector screens. Returns (the copy, {ticker: what happened})."""
    import shutil
    from valuation.L3_app.similar import closest_on_drivers, pick_peers
    out = out or Path(".cache") / "assumptions" / as_of
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(source, out)
    screens = [json.loads(p.read_text()) for p in sorted((data_dir / "sectors").glob(f"*/{as_of}/sector.json"))]
    everyone = [r for d in screens for r in d.get("companies") or []]
    report = {}
    for t in tickers:
        if (out / t / "comps.json").exists():
            continue
        pick = next((p for p in (pick_peers(d, t) for d in screens) if p), None)
        if not pick:
            report[t] = "no sector screen includes it: DCF only"
            continue
        me = next(r for d in screens for r in d.get("companies") or [] if r.get("ticker") == t)
        like = closest_on_drivers(me, everyone)
        doc = {"multiples": ["ev_ebitda", "ev_sales"], "range": "auto",
               "peers": [{"ticker": p["ticker"]} for p in pick["peers"]],
               "sources": {"peers": f"picked automatically by the Refresh: the {len(pick['peers'])} nearest on size and "
                                    f"margin in {pick['sector']} ({pick['level']}: {pick['label']}) on {as_of}"}}
        if like:
            doc["closest"] = [{"ticker": p["ticker"]} for p in like]
            doc["sources"]["closest"] = (f"picked automatically by the Refresh: the {len(like)} closest on five-year revenue "
                                         "growth and operating margin (in steps of 5 and 3 points), any sector screened "
                                         f"({', '.join(d.get('label', '?') for d in screens)}), at least 1/20 of its revenue, "
                                         f"on {as_of}")
        (out / t).mkdir(parents=True, exist_ok=True)
        (out / t / "comps.json").write_text(json.dumps(doc, indent=2))
        report[t] = (f"peers {', '.join(p['ticker'] for p in pick['peers'])}; "
                     f"like companies {', '.join(p['ticker'] for p in like) or 'none with both drivers'}")
    return out, report


def models_for(ticker: str, assumptions: Path = ASSUMPTIONS) -> str:
    return "dcf,comps" if (assumptions / ticker / "comps.json").exists() else "dcf"


def jobs(universe: dict, as_of: str, market: str, assumptions: Path = ASSUMPTIONS) -> list[tuple[str, list[str]]]:
    out = [("SIC lists", ["sic-lists", "--as-of", as_of, "--time-budget", str(SIC_BUDGET_MINUTES)])]       # for in-browser screens (site/data/sic_members.json)
    out += [(spec, ["sector", spec, "--as-of", as_of]) for spec in universe.get("sectors", [])]
    for t in dict.fromkeys(universe.get("tickers", [])):       # de-duplicated, order kept
        out.append((t, ["run", t, "--as-of", as_of, "--models", models_for(t, assumptions),
                        "--stop-after", "L2", "--market", market]))
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--as-of", default=date.today().isoformat())
    p.add_argument("--market", choices=["all", "risk-free", "none"], default="risk-free")
    p.add_argument("--universe", type=Path, default=UNIVERSE)
    args = p.parse_args(argv)

    done, failed = [], []
    rate_checked, no_rate, no_dam = args.market == "none", None, None
    universe = json.loads(args.universe.read_text())
    assumptions = None
    for name, cmd in jobs(universe, args.as_of, args.market):
        if cmd[0] == "run" and assumptions is None:
            assumptions = ASSUMPTIONS
            if args.market == "all":          # comps need peer prices
                print("== comps peers for companies without a comps.json", flush=True)
                try:
                    assumptions, picks = auto_comps(list(dict.fromkeys(universe.get("tickers", []))), args.as_of)
                    for t, msg in picks.items():
                        print(f"   {t}: {msg}", flush=True)
                except Exception as e:          # the companies still run, with the hand-picked comps only
                    print(f"warning: automatic peers not picked ({type(e).__name__}: {e})", file=sys.stderr)
        if cmd[0] == "run":
            t = cmd[1]
            cmd = [*cmd[:4], "--models", models_for(t, assumptions), *cmd[6:], "--assumptions-dir", str(assumptions)]
        if cmd[0] == "run" and not rate_checked:
            rate_checked = True
            print("== risk-free rate", flush=True)
            try:
                fetch_risk_free(args.as_of)
            except Exception as e:
                no_rate = f"{type(e).__name__}: {e}"
                print(f"error: no risk-free rate ({no_rate}); companies keep their last published results",
                      file=sys.stderr)
            print("== industry betas and ERP (Damodaran)", flush=True)
            try:
                if not no_rate:          # no companies will run, so there's nothing to fetch it for
                    fetch_damodaran(args.as_of)
            except Exception as e:
                no_dam = f"{type(e).__name__}: {e}"
                print(f"warning: no Damodaran data ({no_dam}); companies use the sector beta and default ERP",
                      file=sys.stderr)
        if cmd[0] == "run" and no_rate:
            failed.append(name)
            continue
        if cmd[0] == "run" and no_dam:
            cmd = cmd + ["--no-damodaran"]
        print(f"== {name}", flush=True)
        try:
            code = pipeline(cmd)
        except Exception as e:                 # one company's bad filing shouldn't stop the refresh
            print(f"error: {type(e).__name__}: {e}", file=sys.stderr)
            code = 1
        if name != "SIC lists":                 # not a build: only companies and sectors count
            (done if code == 0 else failed).append(name)
        elif code:
            print("warning: SIC lists not fetched; in-browser screens keep the last published ones", file=sys.stderr)

    summary = f"Refresh {args.as_of}: {len(done)} built, {len(failed)} failed" + (f" ({', '.join(failed)})" if failed else "")
    if no_rate:
        summary += f". Companies skipped: no risk-free rate from FRED ({no_rate})"
    elif no_dam:
        summary += f". Damodaran unavailable ({no_dam}): sector betas and the default ERP were used"
    print(summary)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(summary + "\n")
    return 0 if done else 1


if __name__ == "__main__":
    sys.exit(main())
