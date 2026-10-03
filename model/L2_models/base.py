"""Common interface for every L2 model."""
from __future__ import annotations

import importlib
from dataclasses import asdict, dataclass, field
from typing import Protocol

RESULT_SCHEMA_VERSION = "0.1.0"
MODEL_NAMES = ("dcf", "comps", "lbo", "ipo", "precedents")


@dataclass
class ModelResult:
    model: str
    ticker: str
    as_of: str
    value_per_share: dict          # {"p10", "p50", "p90", "mean"}
    assumptions_used: dict         # standard block, see docs/architecture.md
    lineage: dict                  # from lineage.lineage_block()
    samples_ref: str | None = None
    notes: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)   # model-specific workings, for display and audit

    def to_dict(self) -> dict:
        return {"schema_version": RESULT_SCHEMA_VERSION, **asdict(self)}


class Model(Protocol):
    name: str
    needs_peers: bool

    def run(self, detail: dict, assumptions: dict, peers: list[dict] | None = None) -> ModelResult: ...


def get_model(name: str) -> Model:
    if name not in MODEL_NAMES:
        raise KeyError(f"unknown model {name!r}; choose from {MODEL_NAMES}")
    return importlib.import_module(f"L2_models.{name}").MODEL
