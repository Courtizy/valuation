"""Company runs: L0 -> L1 -> L2 steps for a ticker and its comps peers, and the executor."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from L0_ingest.schema import validate_raw_filing
from L0_ingest.sec_companyfacts import SecCompanyFactsAdapter
from L1_detail import build as l1_build
from L1_detail import normalize as l1_normalize
from L2_models.base import get_model
from L2_models.reconcile import build_comparison
from lineage import lineage_block
from runner.paths import Paths


@dataclass
class Step:
    name: str
    layer: str
    ticker: str
    outputs: list[Path]
    fn: Callable[[], None] = field(repr=False)
    soft: bool = False      # a failure here is reported but doesn't stop later steps (each model)
    optional: bool = False  # a failure is only a warning (market data): it never fails the run


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
    market_factory: Callable[[], object] | None = None,
    market_prices: bool = True,
) -> list[Step]:
    """Build the step list. `stop_after` ("L0", "L1" or "L2") drops later layers,
    e.g. "L1" refreshes company detail without running models.

    `market_factory` (L0_ingest.market.MarketAdapter) adds the market steps: the
    risk-free rate once per as-of date, then each company's prices, cross-checked
    against the backup source for the company and its comps peers. Market steps
    are optional: if both sources fail the run continues without market figures.
    `market_prices=False` (showcase mode) keeps only the risk-free rate: no prices,
    so nothing price-derived can reach the public site."""
    if stop_after not in (None, "L0", "L1", "L2"):
        raise KeyError(f"stop_after must be L0, L1 or L2, not {stop_after!r}")
    ticker = ticker.upper()
    for m in models:
        get_model(m)  # fail fast on unknown names

    peers = load_peers(paths, ticker) if any(get_model(m).needs_peers for m in models) else []
    companies = [ticker] + [p for p in peers if p != ticker]
    steps: list[Step] = []

    if market_factory and not paths.risk_free(as_of).exists():
        def risk_free():
            out = paths.risk_free(as_of)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(market_factory().risk_free(as_of), indent=2))
        steps.append(Step("risk-free rate", "L0", ticker, [paths.risk_free(as_of)], risk_free, soft=True, optional=True))

    for c in companies:
        peer = c != ticker   # a peer that fails is reported but doesn't stop the target's run
        if peer and paths.detail(c, as_of).exists():
            continue         # this peer's company detail was already built for this as-of date: reuse it

        def ingest(c=c):
            doc = adapter_factory().fetch(ticker=c)
            errors = validate_raw_filing(doc)
            if errors:
                raise ValueError(f"{c}: raw_filing invalid: {errors[:3]}")
            out = paths.raw_filing(c)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(doc, indent=2))

        steps.append(Step(f"ingest {c}", "L0", c, [paths.raw_filing(c)], ingest, soft=peer))
        if market_factory and market_prices:
            def market(c=c):
                doc = market_factory().fetch(c, as_of, cross_check=True)
                out = paths.raw_market(c, as_of)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(json.dumps(doc, indent=2))
            steps.append(Step(f"market {c}", "L0", c, [paths.raw_market(c, as_of)], market, soft=True, optional=True))
        steps.append(Step(f"normalize {c}", "L1", c, [paths.canonical(c, as_of)],
                          lambda c=c: l1_normalize.run(paths.raw_filing(c), as_of, paths.canonical(c, as_of)),
                          soft=peer))
        steps.append(Step(f"build detail {c}", "L1", c, [paths.detail(c, as_of)],
                          lambda c=c: l1_build.run(paths.canonical(c, as_of), paths.raw_market(c, as_of), as_of,
                                                   paths.detail(c, as_of), risk_free=paths.risk_free(as_of)),
                          soft=peer))

    for m in models:
        def run_model(m=m):
            model = get_model(m)
            detail = _read_json(paths.detail(ticker, as_of))
            a_path = paths.model_assumptions(ticker, m)
            if a_path.exists():
                assumptions = _read_json(a_path, {})
            elif m == "dcf":
                from L2_models.dcf import default_assumptions   # no dcf.json: the default case from the data
                assumptions = default_assumptions(detail)
            else:
                raise FileNotFoundError(f"{a_path} not found; copy inputs/assumptions/_template/{m}.json and fill it in")
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


def execute(steps: list[Step]) -> list[tuple[str, str, str]]:
    """Run steps in order; stop at the first one that isn't built or fails.
    Models are soft steps: one model failing doesn't stop the other models or
    reconcile, which blends whatever finished.

    Returns (step name, status, message) for every step, with status
    done | not_implemented | failed | warning (optional step failed) | skipped.
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
            # optional steps (market data) and expected gaps (comps with no peer prices) are warnings
            warn = s.optional or getattr(e, "is_warning", False)
            report.append((s.name, "warning" if warn else "failed", f"{type(e).__name__}: {e}"))
            halted = not s.soft
    return report
