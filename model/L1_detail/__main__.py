"""CLI for L1.

  python -m L1_detail normalize data/AAPL/raw/raw_filing.json --as-of 2026-09-30 \
      --out data/AAPL/2026-09-30/canonical_statements.json
  python -m L1_detail validate data/AAPL/2026-09-30/canonical_statements.json
  python -m L1_detail build data/AAPL/2026-09-30/canonical_statements.json --as-of 2026-09-30 \
      --out data/AAPL/2026-09-30/company_detail.json [--market raw_market.json] [--pack inputs/packs/default.json]
  python -m L1_detail validate-detail data/AAPL/2026-09-30/company_detail.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .build import run as build_run
from .build import validate_detail
from .normalize import run as normalize_run
from .schema import validate_canonical


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="L1_detail")
    sub = p.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("normalize", help="raw_filing.json -> canonical_statements.json")
    n.add_argument("raw", type=Path)
    n.add_argument("--as-of", required=True)
    n.add_argument("--out", required=True, type=Path)
    n.add_argument("--pack", type=Path, help="sector pack JSON")
    v = sub.add_parser("validate", help="check a canonical_statements.json")
    v.add_argument("path", type=Path)
    b = sub.add_parser("build", help="canonical_statements.json -> company_detail.json")
    b.add_argument("canonical", type=Path)
    b.add_argument("--as-of", required=True)
    b.add_argument("--out", required=True, type=Path)
    b.add_argument("--market", type=Path, help="raw_market.json")
    b.add_argument("--pack", type=Path, help="sector pack JSON")
    vd = sub.add_parser("validate-detail", help="check a company_detail.json")
    vd.add_argument("path", type=Path)
    args = p.parse_args(argv)

    if args.cmd in ("build", "validate-detail"):
        if args.cmd == "build":
            pack = json.loads(args.pack.read_text()) if args.pack else None
            path = build_run(args.canonical, args.market, args.as_of, args.out, pack)
        else:
            path = args.path
        doc = json.loads(path.read_text())
        errors = validate_detail(doc)
        if args.cmd == "build":
            v = doc["views"]
            print(f"wrote {len(v['annual'])} annual, {len(v['quarterly'])} quarterly, "
                  f"{len(v['ttm'])} TTM periods -> {path}")
            for w in doc["warnings"]:
                print(f"warning: {w}", file=sys.stderr)
        for e in errors:
            print(e, file=sys.stderr)
        print("OK" if not errors else f"{len(errors)} problem(s)")
        return 0 if not errors else 1

    if args.cmd == "validate":
        errors = validate_canonical(json.loads(args.path.read_text()))
        for e in errors:
            print(e, file=sys.stderr)
        print("OK" if not errors else f"{len(errors)} problem(s)")
        return 0 if not errors else 1

    pack = json.loads(args.pack.read_text()) if args.pack else None
    out = normalize_run(args.raw, args.as_of, args.out, pack)
    doc = json.loads(out.read_text())
    errors = validate_canonical(doc)
    failed = [c for c in doc["checks"] if c["failed"]]
    print(f"wrote {len(doc['records'])} records, {doc['coverage']['concepts_with_data']} concepts -> {out}")
    for c in failed:
        print(f"CHECK FAILED {c['name']}: {len(c['failed'])} of {c['evaluated']} periods", file=sys.stderr)
    for w in doc["warnings"][:10]:
        print(f"warning: {w}", file=sys.stderr)
    for e in errors:
        print(e, file=sys.stderr)
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
