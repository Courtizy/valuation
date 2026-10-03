"""Pipeline runner: sequences L0 -> L1 -> L2 for a ticker and its peers.

  python pipeline.py run AAPL --models dcf,comps --as-of 2026-09-30 --dry-run
  python pipeline.py run AAPL --models dcf
  python pipeline.py sector sic:3674                 # an SEC industry code
  python pipeline.py sector sic-of:AAPL              # the industry code a company files under
  python pipeline.py sector "traits:stage=high growth;asset_intensity=light"
  python pipeline.py sector list:my_semis            # tickers in sectors/my_semis.json

The runner holds sequencing only. Every layer stays runnable on its own, and
the app (L3) calls this instead of orchestrating inside Streamlit.

Data layout:
  data/{TICKER}/raw/raw_filing.json                        L0
  data/{TICKER}/{as_of}/canonical_statements.json          L1 stage 1
  data/{TICKER}/{as_of}/company_detail.json                L1 stage 2
  data/{TICKER}/{as_of}/model_results/{model}.json         L2 models
  data/{TICKER}/{as_of}/comparison.json                    L2 reconcile
  data/_screen/{as_of}/raw_screen.json                     L0 sector frames (all filers)
  data/_screen/{as_of}/sic_{code}.json                     L0 EDGAR company list for a SIC code
  data/sectors/{sector_id}/{as_of}/sector.json             L1 sector screen
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
from L0_ingest.sec_sector import SecSectorAdapter, screen_year
from L1_detail import build as l1_build
from L1_detail import sector as l1_sector
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

    def raw_screen(self, as_of: str) -> Path:
        return self.data / "_screen" / as_of / "raw_screen.json"

    def sic_list(self, as_of: str, sic: str) -> Path:
        return self.data / "_screen" / as_of / f"sic_{sic}.json"

    def sector(self, sector_id: str, as_of: str) -> Path:
        return self.data / "sectors" / sector_id / as_of / "sector.json"


@dataclass
class Step:
    name: str
    layer: str
    ticker: str
    outputs: list[Path]
    fn: Callable[[], None] = field(repr=False)
    soft: bool = False   # a failure here is reported but doesn't stop later steps (each model)


def load_peers(paths: Paths, ticker: str) -> list[str]:
    p = paths.model_assumptions(ticker, "comps")
    if not p.exists():
        return []
    out = []
    for e in json.loads(p.read_text()).get("peers", []):
        # a peer is a ticker, or {"ticker": ..., "price": ..., ...}; "sec": false = manual figures only
        if isinstance(e, str):
            out.append(e.upper())
        elif e.get("ticker") and e.get("sec", True):
            out.append(e["ticker"].upper())
    return out


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

        peer = c != ticker   # a peer that fails is reported but doesn't stop the target's run
        steps.append(Step(f"ingest {c}", "L0", c, [paths.raw_filing(c)], ingest, soft=peer))
        steps.append(Step(f"normalize {c}", "L1", c, [paths.canonical(c, as_of)],
                          lambda c=c: l1_normalize.run(paths.raw_filing(c), as_of, paths.canonical(c, as_of)),
                          soft=peer))
        steps.append(Step(f"build detail {c}", "L1", c, [paths.detail(c, as_of)],
                          lambda c=c: l1_build.run(paths.canonical(c, as_of), None, as_of, paths.detail(c, as_of)),
                          soft=peer))

    for m in models:
        def run_model(m=m):
            model = get_model(m)
            detail = _read_json(paths.detail(ticker, as_of))
            a_path = paths.model_assumptions(ticker, m)
            if not a_path.exists():
                raise FileNotFoundError(f"{a_path} not found; copy assumptions/_template/{m}.json and fill it in")
            assumptions = _read_json(a_path, {})
            peer_details = [d for d in (_read_json(paths.detail(p, as_of)) for p in peers) if d] if model.needs_peers else None
            result = model.run(detail, assumptions, peer_details)
            result.lineage = lineage_block(as_of, [paths.detail(ticker, as_of)])
            out = paths.result(ticker, as_of, m)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(result.to_dict(), indent=2))

        steps.append(Step(f"model {m}", "L2", ticker, [paths.result(ticker, as_of, m)], run_model, soft=True))

    def reconcile():
        if not any(paths.result(ticker, as_of, m).exists() for m in models):
            raise RuntimeError("no model produced a result to reconcile")
        done = [paths.result(ticker, as_of, m) for m in models if paths.result(ticker, as_of, m).exists()]
        overrides = _read_json(paths.model_assumptions(ticker, "reconcile"), None)
        comp = build_comparison(done, _read_json(paths.detail(ticker, as_of)), overrides)
        paths.comparison(ticker, as_of).write_text(json.dumps(comp, indent=2))

    steps.append(Step("reconcile", "L2", ticker, [paths.comparison(ticker, as_of)], reconcile))
    if stop_after:
        steps = [s for s in steps if s.layer <= stop_after]
    return steps


# ---------------------------------------------------------------- sectors

SECTOR_KINDS = ("sic", "sic-of", "traits", "list")


def parse_sector_spec(spec: str) -> tuple[str, str]:
    """'sic:3674' | 'sic-of:AAPL' | 'traits:stage=high growth;...' | 'list:my_semis' -> (kind, value)."""
    kind, _, value = spec.partition(":")
    kind, value = kind.strip().lower(), value.strip()
    if kind not in SECTOR_KINDS or not value:
        raise ValueError(f"sector must look like sic:3674, sic-of:AAPL, traits:stage=high growth, or list:name; got {spec!r}")
    if kind == "sic" and not (value.isdigit() and len(value) == 4):
        raise ValueError(f"SIC code must be 4 digits: {value!r}")
    if kind == "list" and not all(c.isalnum() or c in "_-" for c in value):
        raise ValueError(f"list name may use letters, digits, _ and -: {value!r}")
    return kind, value


def run_sector(spec: str, as_of: str, paths: Paths, adapter_factory: Callable[[], SecSectorAdapter],
               lists_dir: Path = Path("sectors"), limit: int = l1_sector.DEFAULT_LIMIT) -> Path:
    """Screen one sector and write data/sectors/{id}/{as_of}/sector.json. Returns its path."""
    kind, value = parse_sector_spec(spec)
    ad = adapter_factory()
    raw_p = paths.raw_screen(as_of)
    if raw_p.exists():
        raw = json.loads(raw_p.read_text())
    else:
        raw = ad.fetch_frames(screen_year(as_of))
        raw_p.parent.mkdir(parents=True, exist_ok=True)
        raw_p.write_text(json.dumps(raw))
    tickers = ad.tickers()
    members, label, extra_notes = None, None, []

    if kind == "sic-of":
        cik = ad.resolve_cik(value)[0]
        info = ad.industry(cik)
        if not info.get("sic"):
            raise ValueError(f"no SIC code on file for {value.upper()}")
        kind, value = "sic", info["sic"]
        extra_notes.append(f"{spec.split(':', 1)[1].upper()} files under SIC {value}")
    if kind == "sic":
        lst = ad.sic_members(value)
        p = paths.sic_list(as_of, value)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(lst, indent=2))
        members = lst["ciks"]
        label = f"SIC {value} · {lst['description'].title()}" if lst.get("description") else f"SIC {value}"
    elif kind == "list":
        f = lists_dir / f"{value}.json"
        if not f.exists():
            raise FileNotFoundError(f"{f} not found; see sectors/README.md")
        spec_doc = json.loads(f.read_text())
        by_ticker = {t["ticker"]: t["cik"] for t in tickers}
        want = [str(t).upper() for t in spec_doc.get("tickers", [])]
        unknown = [t for t in want if t not in by_ticker]
        if unknown:
            extra_notes.append(f"not in the SEC ticker list: {', '.join(unknown)}")
        members = [by_ticker[t] for t in want if t in by_ticker]
        label = spec_doc.get("label") or value
        tickers = [t for t in tickers if t["ticker"] in want] + tickers   # listed share class wins

    doc = l1_sector.build_sector(raw, kind=kind, value=value, as_of=as_of, tickers=tickers,
                                 members=members, label=label, limit=limit)
    doc["notes"] = extra_notes + doc["notes"]
    doc["lineage"] = lineage_block(as_of, [raw_p] + ([paths.sic_list(as_of, value)] if kind == "sic" else []))
    out = paths.sector(doc["id"], as_of)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2))
    return out


def execute(steps: list[Step]) -> list[tuple[str, str, str]]:
    """Run steps in order; stop at the first one that isn't built or fails.
    Models are soft steps: one model failing doesn't stop the other models or
    reconcile, which blends whatever finished.

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
            halted = not s.soft
        except Exception as e:  # noqa: BLE001 - surface any failure in the report
            report.append((s.name, "failed", f"{type(e).__name__}: {e}"))
            halted = not s.soft
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
    sc = sub.add_parser("sector", help="screen a sector: sic:3674 | sic-of:AAPL | traits:k=v;... | list:name")
    sc.add_argument("spec")
    sc.add_argument("--as-of", default=date.today().isoformat())
    sc.add_argument("--data-dir", type=Path, default=Path("data"))
    sc.add_argument("--lists-dir", type=Path, default=Path("sectors"))
    sc.add_argument("--cache-dir", type=Path, default=Path(".cache/sec"))
    sc.add_argument("--limit", type=int, default=l1_sector.DEFAULT_LIMIT)
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


if __name__ == "__main__":
    sys.exit(main())
