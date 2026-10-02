"""LBO model (entry/exit multiples, debt tranches, fees). Scaffold only."""
from __future__ import annotations

from L2_models.base import ModelResult


class LBO:
    name = "lbo"
    needs_peers = False

    def run(self, detail: dict, assumptions: dict, peers: list[dict] | None = None) -> ModelResult:
        raise NotImplementedError("lbo: not built yet")


MODEL = LBO()
