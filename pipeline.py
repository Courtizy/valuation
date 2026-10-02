"""Pipeline runner: sequences L0 -> L1 -> L2 for a ticker and its peers.

  python pipeline.py run AAPL --models dcf,comps --as-of 2026-09-30 --dry-run
  python pipeline.py run AAPL --models dcf

The runner holds sequencing only. Every layer stays runnable on its own, and
the app (L3) calls this instead of orchestrating inside Streamlit.

Data layout:
  data/{TICKER}/raw/raw_filing.json                        L0
  data/{TICKER}/{as_of}/canonical_statements.json          L1 stage 1
  data/{TICKER}/{as_of}/company_detail.json                L1 stage 2
  data/{TICKER}/{as_of}/model_results/{model}.json         L2 models
  data/{TICKER}/{as_of}/comparison.json                    L2 reconcile
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

from L0_ingest.cache import FileCache
from L0_ingest.schema import validate_raw_filing
from L0_ingest.sec_companyfacts import SecCompanyFactsAdapter
from L1_detail import build as l1_build
from L1_detail import normalize as l1_normalize
from L2_models.base import MODEL_NAMES, get_model
from L2_models.reconcile import build_comparison
from lineage import lineage_block


@dataclass
class Paths:
    data: Path
    assumptions: Path

    def raw_filing(self, t: str) -> Path:
        return self.data / t / "raw" / "raw_filing.json"

    def asof_dir(self, t: str, as_of: str) -> Path:
        return self.data / t / as_of

    def canonical(self, t: str, as_of: str) -> Path:
        return self.asof_dir(t, as_of) / "canonical_statements.json"

    def detail(self, t: str, as_of: str) -> Path:
        return self.asof_dir(t, as_of) / "company_detail.json"

    def result(self, t: str, as_of: str, model: str) -> Path:
        return self.asof_dir(t, as_of) / "model_results" / f"{model}.json"

    def comparison(self, t: str, as_of: str) -> Path:
        return self.asof_dir(t, as_of) / "comparison.json"

    def model_assumptions(self, t: str, model: str) -> Path:
        return self.assumptions / t / f"{model}.json"


@dataclass
class Step:
    name: str
    layer: str
    ticker: str
    outputs: list[Path]
    fn: Callable[[], None] = field(repr=False)


def load_peers(paths: Paths, ticker: str) -> list[str]:
    p = paths.model_assumptions(ticker, "comps")
    if not p.exists():
        return []
    return [s.upper() for s in json.loads(p.read_text()).get("peers", [])]


def _read_json(p: Path, default=None):
    return json.loads(p.read_text()) if p.exists() else default


def plan(
    ticker: str,
    models: list[str],
    as_of: str,
    paths: Paths,
    adapter_factory: Callable[[], SecCompanyFactsAdapter],
    stop_after: str | None = None,
) -> list[Step]:
    """Build the step list. `stop_after` ("L0", "L1" or "L2") drops later layers,
    e.g. "L1" refreshes company detail without running models."""
    if stop_after not in (None, "L0", "L1", "L2"):
        raise KeyError(f"stop_after must be L0, L1 or L2, not {stop_after!r}")
    ticker = ticker.upper()
    for m in models:
        get_model(m)  # fail fast on unknown names

    peers = load_peers(paths, ticker) if any(get_model(m).needs_peers for m in models) else []
    companies = [ticker] + [p for p in peers if p != ticker]
    steps: list[Step] = []

    for c in companies:
        def ingest(c=c):
            doc = adapter_factory().fetch(ticker=c)
            errors = validate_raw_filing(doc)
            if errors:
                raise ValueError(f"{c}: raw_filing invalid: {errors[:3]}")
            out = paths.raw_filing(c)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(doc, indent=2))

        steps.append(Step(f"ingest {c}", "L0", c, [paths.raw_filing(c)], ingest))
        steps.append(Step(f"normalize {c}", "L1", c, [paths.canonical(c, as_of)],
                          lambda c=c: l1_normalize.run(paths.raw_filing(c), as_of, paths.canonical(c, as_of))))
        steps.append(Step(f"build detail {c}", "L1", c, [paths.detail(c, as_of)],
                          lambda c=c: l1_build.run(paths.canonical(c, as_of), None, as_of, paths.detail(c, as_of))))

    for m in models:
        def run_model(m=m):
            model = get_model(m)
            detail = _read_json(paths.detail(ticker, as_of))
            assumptions = _read_json(paths.model_assumptions(ticker, m), {})
            peer_details = [_read_json(paths.detail(p, as_of)) for p in peers] if model.needs_peers else None
            result = model.run(detail, assumptions, peer_details)
            result.lineage = lineage_block(as_of, [paths.detail(ticker, as_of)])
            out = paths.result(ticker, as_of, m)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(result.to_dict(), indent=2))

        steps.append(Step(f"model {m}", "L2", ticker, [paths.result(ticker, as_of, m)], run_model))

    def reconcile():
        comp = build_comparison([paths.result(ticker, as_of, m) for m in models])
        paths.comparison(ticker, as_of).write_text(json.dumps(comp, indent=2))

    steps.append(Step("reconcile", "L2", ticker, [paths.comparison(ticker, as_of)], reconcile))
    if stop_after:
        steps = [s for s in steps if s.layer <= stop_after]
    return steps


def execute(steps: list[Step]) -> list[tuple[str, str, str]]:
    """Run steps in order; stop at the first one that isn't built or fails.

    Returns (step name, status, message) for every step, with status
    done | not_implemented | failed | skipped.
    """
    report: list[tuple[str, str, str]] = []
    halted = False
    for s in steps:
        if halted:
            report.append((s.name, "skipped", "upstream step did not complete"))
            continue
        try:
            s.fn()
            report.append((s.name, "done", ""))
        except NotImplementedError as e:
            report.append((s.name, "not_implemented", str(e)))
            halted = True
        except Exception as e:  # noqa: BLE001 - surface any failure in the report
            report.append((s.name, "failed", f"{type(e).__name__}: {e}"))
            halted = True
    return report


def main(argv: list[str] | None = None,
         adapter_factory: Callable[..., SecCompanyFactsAdapter] | None = None) -> int:
    p = argparse.ArgumentParser(prog="pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run L0 -> L2 for a ticker")
    r.add_argument("ticker")
    r.add_argument("--models", default="dcf", help=f"comma list from {','.join(MODEL_NAMES)}")
    r.add_argument("--as-of", default=date.today().isoformat())
    r.add_argument("--data-dir", type=Path, default=Path("data"))
    r.add_argument("--assumptions-dir", type=Path, default=Path("assumptions"))
    r.add_argument("--cache-dir", type=Path, default=Path(".cache/sec"))
    r.add_argument("--user-agent", help="defaults to $SEC_USER_AGENT")
    r.add_argument("--dry-run", action="store_true", help="print the plan without running")
    r.add_argument("--stop-after", choices=["L0", "L1", "L2"], help="skip layers after this one")
    args = p.parse_args(argv)

    paths = Paths(args.data_dir, args.assumptions_dir)
    if adapter_factory is None:
        def adapter_factory():
            return SecCompanyFactsAdapter(cache=FileCache(args.cache_dir), user_agent=args.user_agent)

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    try:
        steps = plan(args.ticker, models, args.as_of, paths, adapter_factory, args.stop_after)
    except KeyError as e:
        print(f"error: {e.args[0]}", file=sys.stderr)
        return 2

    if args.dry_run:
        for i, s in enumerate(steps, 1):
            print(f"{i:>2}. [{s.layer}] {s.name} -> {', '.join(str(o) for o in s.outputs)}")
        return 0

    report = execute(steps)
    for name, status, msg in report:
        print(f"{status:<16} {name}" + (f"  ({msg})" if msg else ""))
    return 0 if all(st == "done" for _, st, _ in report) else 1


if __name__ == "__main__":
    sys.exit(main())
