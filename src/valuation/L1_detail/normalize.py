"""L1 stage 1: raw_filing.json -> canonical_statements.json.

For each concept and each period:
  1. Point-in-time: only facts with filed <= as_of are visible.
  2. Pick the value (registry aggregation rule):
       first  highest-priority tag with a value for that period
       sum    a total tag if present, else the sum of components
  3. Across filings for the same period:
       value          = latest filing (includes restatements)
       value_as_filed = earliest filing, across all of the concept's tags
       restated       = the two differ
  4. Fiscal labels (fiscal_year, fiscal_period) come from the earliest filing,
     because companyfacts' fy/fp describe the filing, not the period.
Then derived concepts are computed per period, and accounting identities are
checked. Quarterly/annual/TTM views are stage 2's job; stage 1 keeps every
duration (3, 6, 9, 12 months) with its length in `months`.
"""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from pathlib import Path

from valuation.lineage import lineage_block

from .formula import evaluate
from .registry import Concept, Registry, load_registry
from .schema import CANONICAL_SCHEMA_VERSION

UNIT_FOR = {"monetary": "USD", "shares": "shares", "per_share": "USD/shares", "ratio": "pure"}
RELATIVE_TOLERANCE = 0.005

# (name, left formula, right formula); a period is checked only if both sides evaluate.
CHECKS = [
    ("balance_sheet_balances", "assets", "liabilities_and_equity"),
    ("gross_profit_ties", "gross_profit", "revenue - cost_of_goods_and_services_sold"),
    ("net_income_split_ties", "profit_loss", "net_income + minority_interest_income_expense"),
]

Period = tuple  # (start or None, end)


def _months(start: str | None, end: str) -> int | None:
    if start is None:
        return None
    days = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    return round(days / 30.4375)


def _latest(facts: list[dict]) -> dict:
    return max(facts, key=lambda f: (f["filed"], f["accn"]))


def _earliest(facts: list[dict]) -> dict:
    return min(facts, key=lambda f: (f["filed"], f["accn"]))


def apply_pack(registry: Registry, pack: dict | None) -> Registry:
    """Return a registry with a sector pack's L1 tag overrides applied."""
    overrides = ((pack or {}).get("l1") or {}).get("tag_overrides") or {}
    if not overrides:
        return registry
    out = Registry(version=registry.version, concepts=dict(registry.concepts))
    for cid, tags in overrides.items():
        if cid not in out.concepts:
            raise KeyError(f"pack overrides unknown concept {cid!r}")
        out.concepts[cid] = replace(out.concepts[cid], primary_tags=tuple(tags))
    return out


class _FactIndex:
    """tag -> unit -> period -> facts, restricted to facts visible at as_of."""

    def __init__(self, facts: list[dict]):
        self.idx: dict[str, dict[str, dict[Period, list[dict]]]] = {}
        for f in facts:
            tag = f"{f['taxonomy']}:{f['tag']}"
            self.idx.setdefault(tag, {}).setdefault(f["unit"], {}) \
                .setdefault((f["start"], f["end"]), []).append(f)

    def periods(self, tag: str, unit: str, instant: bool) -> dict[Period, list[dict]]:
        by_period = self.idx.get(tag, {}).get(unit, {})
        return {p: fs for p, fs in by_period.items() if (p[0] is None) == instant}

    def units_for(self, tag: str) -> set[str]:
        return set(self.idx.get(tag, {}))


def _check_within_filing(tag: str, period: Period, facts: list[dict], warnings: list[str]) -> None:
    by_accn: dict[str, set] = {}
    for f in facts:
        by_accn.setdefault(f["accn"], set()).add(f["value"])
    for accn, values in by_accn.items():
        if len(values) > 1:
            warnings.append(f"{tag} {period}: filing {accn} reports conflicting values {sorted(values)}")


def _record(c: Concept, period: Period, unit: str, current: dict, first: dict,
            value: float, as_filed: float, method: str, tags: list[str], extra: dict | None = None) -> dict:
    rec = {
        "concept": c.id,
        "statement": c.statement,
        "period_type": c.period_type,
        "unit": unit,
        "start": period[0],
        "end": period[1],
        "months": _months(period[0], period[1]),
        "fiscal_year": first.get("fy"),
        "fiscal_period": first.get("fp"),
        "value": value,
        "value_as_filed": as_filed,
        "restated": value != as_filed,
        "method": method,
        "source": {"tags": tags, "accn": current["accn"], "filed": current["filed"], "form": current["form"]},
    }
    if extra:
        rec.update(extra)
    return rec


def _map_first(c: Concept, tags: tuple[str, ...], fx: _FactIndex, unit: str, instant: bool,
               warnings: list[str]) -> dict[Period, dict]:
    per_tag = [(t, fx.periods(t, unit, instant)) for t in tags]
    all_periods = {p for _, pm in per_tag for p in pm}
    out = {}
    for period in all_periods:
        chosen_tag, chosen = next((t, pm[period]) for t, pm in per_tag if period in pm)
        _check_within_filing(chosen_tag, period, chosen, warnings)
        everything = [f for _, pm in per_tag for f in pm.get(period, [])]
        current, first = _latest(chosen), _earliest(everything)
        out[period] = _record(c, period, unit, current, first,
                              current["value"], first["value"], "reported", [chosen_tag])
    return out


def _map_sum(c: Concept, fx: _FactIndex, unit: str, instant: bool,
             warnings: list[str]) -> dict[Period, dict]:
    out = _map_first(c, c.primary_tags, fx, unit, instant, warnings) if c.primary_tags else {}
    comp_maps = [[(t, fx.periods(t, unit, instant)) for t in alts] for alts in c.components]
    comp_periods = {p for comp in comp_maps for _, pm in comp for p in pm}
    for period in comp_periods - set(out):
        parts, missing = [], 0
        for comp in comp_maps:
            hit = next(((t, pm[period]) for t, pm in comp if period in pm), None)
            if hit is None:
                missing += 1
                continue
            tag, facts = hit
            _check_within_filing(tag, period, facts, warnings)
            parts.append((tag, _latest(facts), _earliest(facts)))
        current = max((p[1] for p in parts), key=lambda f: (f["filed"], f["accn"]))
        first = min((p[2] for p in parts), key=lambda f: (f["filed"], f["accn"]))
        out[period] = _record(
            c, period, unit, current, first,
            sum(p[1]["value"] for p in parts), sum(p[2]["value"] for p in parts), "summed",
            [p[0] for p in parts],
            {"components": [{"tag": p[0], "value": p[1]["value"]} for p in parts],
             "components_missing": missing},
        )
    return out


def _derive(c: Concept, by_concept: dict[str, dict[Period, dict]]) -> dict[Period, dict]:
    inputs = c.formula_inputs()
    if any(i not in by_concept for i in inputs):
        return {}
    shared = set.intersection(*(set(by_concept[i]) for i in inputs))
    out = {}
    for period in shared:
        recs = [by_concept[i][period] for i in inputs]
        value = evaluate(c.formula, {i: r["value"] for i, r in zip(inputs, recs)})
        if value is None:
            continue
        as_filed = evaluate(c.formula, {i: r["value_as_filed"] for i, r in zip(inputs, recs)})
        latest = max(recs, key=lambda r: r["source"]["filed"])
        out[period] = {
            "concept": c.id, "statement": c.statement, "period_type": c.period_type,
            "unit": UNIT_FOR[c.unit_type], "start": period[0], "end": period[1],
            "months": recs[0]["months"], "fiscal_year": recs[0]["fiscal_year"],
            "fiscal_period": recs[0]["fiscal_period"],
            "value": value, "value_as_filed": as_filed,
            "restated": as_filed is not None and value != as_filed,
            "method": "derived",
            "source": {"formula": c.formula, "inputs": inputs, "filed": latest["source"]["filed"]},
        }
    return out


def _run_checks(by_concept: dict[str, dict[Period, dict]]) -> list[dict]:
    results = []
    for name, left, right in CHECKS:
        refs = {t for expr in (left, right) for t in expr.replace("-", " ").replace("+", " ").split()}
        if any(r not in by_concept for r in refs):
            results.append({"name": name, "evaluated": 0, "failed": []})
            continue
        periods = set.union(*(set(by_concept[r]) for r in refs))
        evaluated, failed = 0, []
        for period in sorted(periods, key=lambda p: (p[1], p[0] or "")):
            vals = {r: by_concept[r][period]["value"] for r in refs if period in by_concept[r]}
            lv, rv = evaluate(left, vals), evaluate(right, vals)
            if lv is None or rv is None:
                continue
            evaluated += 1
            if abs(lv - rv) > RELATIVE_TOLERANCE * max(abs(lv), abs(rv), 1):
                failed.append({"start": period[0], "end": period[1], "left": lv, "right": rv})
        results.append({"name": name, "evaluated": evaluated, "failed": failed})
    return results


def reporting_basis(facts: list[dict]) -> dict:
    """The taxonomy and currency most monetary facts use, e.g. us-gaap/USD or ifrs-full/TWD.

    Foreign private issuers filing 20-Fs under IFRS tag with ifrs-full in their
    home currency; the registry maps us-gaap tags in USD."""
    counts: dict[tuple[str, str], int] = {}
    for f in facts:
        if f["taxonomy"] == "dei" or "/" in f["unit"] or f["unit"] in ("shares", "pure"):
            continue
        k = (f["taxonomy"], f["unit"])
        counts[k] = counts.get(k, 0) + 1
    if not counts:
        return {"taxonomy": "none", "currency": "none", "facts": 0, "breakdown": {}}
    (tax, cur), n = max(counts.items(), key=lambda kv: kv[1])
    return {"taxonomy": tax, "currency": cur, "facts": n,
            "breakdown": {f"{t}/{u}": c for (t, u), c in sorted(counts.items(), key=lambda kv: -kv[1])}}


def normalize(raw: dict, as_of: str, registry: Registry | None = None,
              lineage: dict | None = None) -> dict:
    registry = registry or load_registry()
    date.fromisoformat(as_of)  # fail fast on a bad date
    visible = [f for f in raw["facts"] if f["filed"] <= as_of]
    fx = _FactIndex(visible)
    warnings: list[str] = []
    by_concept: dict[str, dict[Period, dict]] = {}

    for c in registry.concepts.values():
        if c.kind == "derived":
            continue
        unit = UNIT_FOR[c.unit_type]
        instant = c.period_type == "instant"
        mapped = (_map_sum(c, fx, unit, instant, warnings) if c.aggregation == "sum"
                  else _map_first(c, c.primary_tags, fx, unit, instant, warnings))
        if mapped:
            by_concept[c.id] = mapped
        else:
            other_units = {u for t in c.all_tags() for u in fx.units_for(t)} - {unit}
            if other_units:
                warnings.append(f"{c.id}: tags found only in units {sorted(other_units)}, expected {unit}")

    for c in registry.derived_order():
        derived = _derive(c, by_concept)
        if derived:
            by_concept[c.id] = derived

    basis = reporting_basis(visible)
    if basis["taxonomy"] != "us-gaap" or basis["currency"] != "USD":
        warnings.append(
            f"financials are reported under {basis['taxonomy']} in {basis['currency']} "
            f"({basis['facts']} facts); only us-gaap in USD is mapped so far, so most statement lines are missing")

    records = sorted(
        (r for periods in by_concept.values() for r in periods.values()),
        key=lambda r: (r["concept"], r["end"], r["start"] or ""),
    )
    missing = sorted(set(registry.concepts) - set(by_concept))
    return {
        "schema_version": CANONICAL_SCHEMA_VERSION,
        "stage": "L1.normalize",
        "as_of": as_of,
        "registry_version": registry.version,
        "entity": raw.get("entity", {}),
        "source": {"name": raw.get("source"), "url": raw.get("source_url"),
                   "content_sha256": raw.get("content_sha256")},
        "lineage": lineage or {"as_of": as_of, "inputs": []},
        "reporting_basis": basis,
        "facts_visible": len(visible),
        "facts_excluded_after_as_of": len(raw["facts"]) - len(visible),
        "records": records,
        "checks": _run_checks(by_concept),
        "coverage": {"concepts_with_data": len(by_concept), "missing": missing},
        "warnings": sorted(set(warnings)),
    }


def run(raw_filing: Path, as_of: str, out_path: Path, pack: dict | None = None) -> Path:
    raw = json.loads(Path(raw_filing).read_text())
    if "facts" not in raw or "schema_version" not in raw:
        raise ValueError(f"{raw_filing} is not a raw_filing.json")
    registry = apply_pack(load_registry(), pack)
    doc = normalize(raw, as_of, registry, lineage_block(as_of, [raw_filing]))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(doc, indent=2))
    return out_path
