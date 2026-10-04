"""Canonical concept registry (L1, normalize stage).

The registry is data (concepts.json), not code, so sector packs can extend or
override it. Three kinds of concept:

  reported  one of edgartools' 95 standard concepts
  memo      valuation additions that may overlap reported concepts
            (e.g. share-based comp also sits inside other operating expense);
            never sum memo items into statement totals
  derived   computed from other concepts by `formula`; never read from tags

Aggregation (reported and memo concepts):
  first     use the highest-priority tag in `primary_tags` that has a value
  sum       use a `primary_tags` total if one has a value; otherwise sum
            `components`, where each component is a priority list of
            alternative tags (e.g. [[cash], [marketable securities, short-term
            investments]]). Missing components count as absent, not zero,
            and are recorded so the sum can be audited.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PATH = Path(__file__).with_name("concepts.json")

KINDS = {"reported", "memo", "derived"}
AGGREGATIONS = {"first", "sum"}
STATEMENTS = {"BS", "IS", "CF", "SHARES", "DISCLOSURE", "DERIVED"}
PERIOD_TYPES = {"instant", "duration"}
UNIT_TYPES = {"monetary", "shares", "per_share", "ratio"}
SNAKE = re.compile(r"^[a-z][a-z0-9_]*$")
TAG = re.compile(r"^[a-z-]+:[A-Za-z0-9]+$")
FORMULA_TOKEN = re.compile(r"[a-z][a-z0-9_]*")


@dataclass(frozen=True)
class Concept:
    id: str
    display_name: str
    statement: str
    section: str
    period_type: str
    unit_type: str
    kind: str
    source: str
    edgartools_concept: str | None = None
    primary_tags: tuple[str, ...] = ()
    formula: str | None = None
    aggregation: str = "first"
    components: tuple[tuple[str, ...], ...] = ()

    def all_tags(self) -> list[str]:
        return list(self.primary_tags) + [t for comp in self.components for t in comp]

    def formula_inputs(self) -> list[str]:
        return FORMULA_TOKEN.findall(self.formula or "")


@dataclass
class Registry:
    version: str
    concepts: dict[str, Concept] = field(default_factory=dict)

    def __getitem__(self, cid: str) -> Concept:
        return self.concepts[cid]

    def __len__(self) -> int:
        return len(self.concepts)

    def of_kind(self, kind: str) -> list[Concept]:
        return [c for c in self.concepts.values() if c.kind == kind]

    def tag_index(self) -> dict[str, list[tuple[str, int]]]:
        """'us-gaap:Revenues' -> [(concept_id, priority), ...]; lower priority wins."""
        idx: dict[str, list[tuple[str, int]]] = {}
        for c in self.concepts.values():
            for rank, tag in enumerate(c.all_tags()):
                idx.setdefault(tag, []).append((c.id, rank))
        return idx

    def derived_order(self) -> list[Concept]:
        """Derived concepts in dependency order (inputs before outputs)."""
        done: set[str] = set()
        order: list[Concept] = []
        pending = self.of_kind("derived")
        while pending:
            ready = [c for c in pending
                     if all(r in done or r not in self.concepts or self[r].kind != "derived"
                            for r in c.formula_inputs())]
            if not ready:
                raise ValueError(f"cycle among derived concepts: {[c.id for c in pending]}")
            for c in ready:
                order.append(c)
                done.add(c.id)
            pending = [c for c in pending if c.id not in done]
        return order

    def unmapped(self) -> list[str]:
        """Reported/memo concepts with no companyfacts tags yet (need pack or mapping file)."""
        return sorted(c.id for c in self.concepts.values()
                      if c.kind != "derived" and not c.all_tags())


def load_registry(path: str | Path = DEFAULT_PATH) -> Registry:
    doc = json.loads(Path(path).read_text())
    reg = Registry(version=doc["registry_version"])
    for raw in doc["concepts"]:
        c = Concept(**{
            **raw,
            "primary_tags": tuple(raw.get("primary_tags") or ()),
            "components": tuple(tuple(comp) for comp in raw.get("components") or ()),
            "aggregation": raw.get("aggregation") or "first",
        })
        if c.id in reg.concepts:
            raise ValueError(f"duplicate concept id: {c.id}")
        reg.concepts[c.id] = c
    return reg


def validate_registry(reg: Registry) -> list[str]:
    """Structural and integrity checks; empty list means valid."""
    errors: list[str] = []
    for c in reg.concepts.values():
        where = f"concept {c.id!r}"
        if not SNAKE.match(c.id):
            errors.append(f"{where}: id is not snake_case")
        if c.kind not in KINDS:
            errors.append(f"{where}: bad kind {c.kind!r}")
        if c.statement not in STATEMENTS:
            errors.append(f"{where}: bad statement {c.statement!r}")
        if c.period_type not in PERIOD_TYPES:
            errors.append(f"{where}: bad period_type {c.period_type!r}")
        if c.unit_type not in UNIT_TYPES:
            errors.append(f"{where}: bad unit_type {c.unit_type!r}")
        if c.statement == "BS" and c.period_type != "instant":
            errors.append(f"{where}: balance-sheet items must be instant")
        if c.statement in {"IS", "CF"} and c.period_type != "duration":
            errors.append(f"{where}: IS/CF items must be duration")
        if c.kind == "reported" and not c.edgartools_concept:
            errors.append(f"{where}: reported concept missing edgartools_concept")
        if c.aggregation not in AGGREGATIONS:
            errors.append(f"{where}: bad aggregation {c.aggregation!r}")
        if c.aggregation == "sum" and not c.components:
            errors.append(f"{where}: sum aggregation needs components")
        if c.aggregation != "sum" and c.components:
            errors.append(f"{where}: components only allowed with sum aggregation")
        if any(not comp for comp in c.components):
            errors.append(f"{where}: empty component")
        for t in c.all_tags():
            if not TAG.match(t):
                errors.append(f"{where}: tag {t!r} not 'taxonomy:Name'")
        if c.kind == "derived":
            if not c.formula:
                errors.append(f"{where}: derived concept missing formula")
            if c.all_tags():
                errors.append(f"{where}: derived concept must not read tags")
            for ref in c.formula_inputs():
                if ref not in reg.concepts:
                    errors.append(f"{where}: formula references unknown {ref!r}")
                elif ref == c.id:
                    errors.append(f"{where}: formula references itself")
        elif c.formula:
            errors.append(f"{where}: only derived concepts may have a formula")

    try:
        reg.derived_order()
    except ValueError as e:
        errors.append(str(e))

    # A tag claimed by two reported concepts would double count.
    for tag, owners in reg.tag_index().items():
        reported = [cid for cid, _ in owners if reg[cid].kind == "reported"]
        if len(reported) > 1:
            errors.append(f"tag {tag} claimed by multiple reported concepts: {reported}")
    return errors
