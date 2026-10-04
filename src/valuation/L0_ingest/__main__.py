"""CLI for L0.

  python -m valuation.L0_ingest sec-companyfacts --ticker AAPL --out data/raw/AAPL/raw_filing.json
  python -m valuation.L0_ingest validate data/raw/AAPL/raw_filing.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable

from .cache import FileCache
from .schema import validate_raw_filing
from .sec_companyfacts import SecCompanyFactsAdapter


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="L0_ingest")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("sec-companyfacts", help="fetch SEC companyfacts -> raw_filing.json")
    who = s.add_mutually_exclusive_group(required=True)
    who.add_argument("--ticker")
    who.add_argument("--cik")
    s.add_argument("--out", required=True, type=Path)
    s.add_argument("--cache-dir", type=Path, default=Path(".cache/sec"))
    s.add_argument("--ttl-hours", type=float, default=24.0)
    s.add_argument("--user-agent", help="defaults to $SEC_USER_AGENT")

    v = sub.add_parser("validate", help="check a raw_filing.json against the schema")
    v.add_argument("path", type=Path)
    return p


def _report(errors: list[str]) -> None:
    for e in errors:
        print(e, file=sys.stderr)


def main(
    argv: list[str] | None = None,
    adapter_factory: Callable[..., SecCompanyFactsAdapter] = SecCompanyFactsAdapter,
) -> int:
    args = _parser().parse_args(argv)

    if args.cmd == "validate":
        errors = validate_raw_filing(json.loads(args.path.read_text()))
        _report(errors)
        print("OK" if not errors else f"{len(errors)} problem(s)")
        return 0 if not errors else 1

    cache = FileCache(args.cache_dir, ttl_seconds=args.ttl_hours * 3600)
    adapter = adapter_factory(cache=cache, user_agent=args.user_agent)
    doc = adapter.fetch(ticker=args.ticker, cik=args.cik)
    errors = validate_raw_filing(doc)
    if errors:
        _report(errors)
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, indent=2))
    print(f"wrote {len(doc['facts'])} facts for {doc['entity']['name']} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
