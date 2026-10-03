"""Where every layer's files live (see pipeline.py for the layout)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Paths:
    data: Path
    assumptions: Path

    def raw_filing(self, t: str) -> Path:
        return self.data / t / "raw" / "raw_filing.json"

    def asof_dir(self, t: str, as_of: str) -> Path:
        return self.data / t / as_of

    def raw_market(self, t: str, as_of: str) -> Path:
        return self.asof_dir(t, as_of) / "raw_market.json"

    def risk_free(self, as_of: str) -> Path:
        return self.data / "_market" / as_of / "risk_free.json"

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
