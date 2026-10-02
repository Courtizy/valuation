"""DCF model (forecast, WACC, terminal value, own Monte Carlo). Scaffold only."""
from __future__ import annotations

from L2_models.base import ModelResult


class DCF:
    name = "dcf"
    needs_peers = False

    def run(self, detail: dict, assumptions: dict, peers: list[dict] | None = None) -> ModelResult:
        raise NotImplementedError("dcf: not built yet")


MODEL = DCF()
