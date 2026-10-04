"""Where every layer's files live.

  data/{TICKER}/raw/raw_filing.json                        L0
  data/{TICKER}/{as_of}/raw_market.json                    L0 market data
  data/{TICKER}/{as_of}/canonical_statements.json          L1 stage 1
  data/{TICKER}/{as_of}/company_detail.json                L1 stage 2
  data/{TICKER}/{as_of}/model_results/{model}.json         L2 models
  data/{TICKER}/{as_of}/comparison.json                    L2 reconcile
  data/_market/{as_of}/risk_free.json                      L0 FRED rate
  data/_screen/{as_of}/raw_screen.json, sic_{code}.json    L0 sector frames, EDGAR SIC lists
  data/sectors/{sector_id}/{as_of}/sector.json             L1 sector screen
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Paths:
    data: Path
    assumptions: Path
    fallback: Path | None = None      # e.g. private/assumptions first, then configs/public/assumptions

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
        own = self.assumptions / t / f"{model}.json"
        if not own.exists() and self.fallback and (self.fallback / t / f"{model}.json").exists():
            return self.fallback / t / f"{model}.json"
        return own

    def raw_screen(self, as_of: str) -> Path:
        return self.data / "_screen" / as_of / "raw_screen.json"

    def sic_list(self, as_of: str, sic: str) -> Path:
        return self.data / "_screen" / as_of / f"sic_{sic}.json"

    def sector(self, sector_id: str, as_of: str) -> Path:
        return self.data / "sectors" / sector_id / as_of / "sector.json"
