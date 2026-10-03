"""Command line: python pipeline.py run|sector ..."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Callable

from L0_ingest.cache import FileCache
from L0_ingest.sec_companyfacts import SecCompanyFactsAdapter
from L0_ingest.sec_sector import SecSectorAdapter
from L2_models.base import MODEL_NAMES
from runner.company import execute, plan
from runner.paths import Paths
from runner.sector import run_sector


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
    sc = sub.add_parser("sector", help="screen a sector: sic-of:AAPL | sector:technology | sic:3674 | traits:k=v;... | list:name")
    sc.add_argument("spec")
    sc.add_argument("--as-of", default=date.today().isoformat())
    sc.add_argument("--data-dir", type=Path, default=Path("data"))
    sc.add_argument("--lists-dir", type=Path, default=Path("sectors"))
    sc.add_argument("--cache-dir", type=Path, default=Path(".cache/sec"))
    sc.add_argument("--limit", type=int, default=None, help="largest companies kept (default 300 for a sector, else 100)")
    sc.add_argument("--user-agent", help="defaults to $SEC_USER_AGENT")
    args = p.parse_args(argv)

    if args.cmd == "sector":
        fac = adapter_factory or (lambda: SecSectorAdapter(cache=FileCache(args.cache_dir), user_agent=args.user_agent))
        try:
            out = run_sector(args.spec, args.as_of, Paths(args.data_dir, Path("assumptions")), fac, args.lists_dir, args.limit)
        except (ValueError, FileNotFoundError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        doc = json.loads(out.read_text())
        print(f"{doc['label']}: {len(doc['companies'])} companies -> {out}")
        for n in doc["notes"]:
            print(f"  note: {n}")
        return 0

    paths = Paths(args.data_dir, args.assumptions_dir)
    if adapter_factory is None:
        def adapter_factory():
            return SecSectorAdapter(cache=FileCache(args.cache_dir), user_agent=args.user_agent)

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
