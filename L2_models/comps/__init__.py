"""Comps model (peer multiples, calendarized periods). Scaffold only."""
from __future__ import annotations

from L2_models.base import ModelResult


class Comps:
    name = "comps"
    needs_peers = True

    def run(self, detail: dict, assumptions: dict, peers: list[dict] | None = None) -> ModelResult:
        raise NotImplementedError("comps: not built yet")


MODEL = Comps()
