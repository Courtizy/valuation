"""Build every sector and company in configs/public/universe.json (the weekly Refresh workflow).

    python scripts/refresh_universe.py --as-of 2026-10-21 --market risk-free

Each company runs the DCF, plus comps when configs/public/assumptions/{TICKER}/comps.json
exists. One failure doesn't stop the rest; the summary lists them, and the exit code is
non-zero only when nothing at all was built.
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

UNIVERSE = ROOT / "configs" / "public" / "universe.json"
ASSUMPTIONS = ROOT / "configs" / "public" / "assumptions"


def models_for(ticker: str, assumptions: Path = ASSUMPTIONS) -> str:
    return "dcf,comps" if (assumptions / ticker / "comps.json").exists() else "dcf"


def jobs(universe: dict, as_of: str, market: str, assumptions: Path = ASSUMPTIONS) -> list[tuple[str, list[str]]]:
    out = [("SIC lists", ["sic-lists", "--as-of", as_of])]       # for in-browser screens (site/data/sic_members.json)
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
    for name, cmd in jobs(json.loads(args.universe.read_text()), args.as_of, args.market):
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
    print(summary)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(summary + "\n")
    return 0 if done else 1


if __name__ == "__main__":
    sys.exit(main())
