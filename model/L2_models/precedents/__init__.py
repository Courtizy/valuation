"""Precedents model (deal set and deal multiples). Scaffold only."""
from __future__ import annotations

from L2_models.base import ModelResult


class Precedents:
    name = "precedents"
    needs_peers = False

    def run(self, detail: dict, assumptions: dict, peers: list[dict] | None = None) -> ModelResult:
        raise NotImplementedError("precedents: not built yet")


MODEL = Precedents()
