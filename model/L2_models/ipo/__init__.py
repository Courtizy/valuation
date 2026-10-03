"""IPO model (peer multiples, offering structure, IPO discount). Scaffold only."""
from __future__ import annotations

from L2_models.base import ModelResult


class IPO:
    name = "ipo"
    needs_peers = True

    def run(self, detail: dict, assumptions: dict, peers: list[dict] | None = None) -> ModelResult:
        raise NotImplementedError("ipo: not built yet")


MODEL = IPO()
