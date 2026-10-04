"""Sector taxonomy: Sector > Industry Group > Industry over SEC SIC codes.

configs/public/sectors/taxonomy.json holds the tree (GICS-style names, editable); every
industry lists the SIC codes it covers. The SEC assigns each filer one SIC
code, so a code places a company in exactly one industry, group and sector.
Codes the map doesn't list (or lists as excluded) classify as None.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parents[3] / "configs" / "public" / "sectors" / "taxonomy.json"


class Taxonomy:
    def __init__(self, doc: dict):
        self.doc = doc
        self.by_sic: dict[str, dict] = {}
        self.sectors = {s["id"]: s for s in doc["sectors"]}
        for s in doc["sectors"]:
            for g in s["groups"]:
                for i in g["industries"]:
                    for code in i["sic"]:
                        if code in self.by_sic:
                            raise ValueError(f"SIC {code} is listed in two industries")
                        self.by_sic[code] = {"sector": s["id"], "sector_name": s["name"], "group": g["id"],
                                             "group_name": g["name"], "industry": i["id"], "industry_name": i["name"]}
        self.excluded = set(doc.get("excluded") or {})

    def classify(self, sic: str | int | None) -> dict | None:
        if sic is None or sic == "":
            return None
        return self.by_sic.get(str(sic).zfill(4))

    def codes(self, sector_id: str) -> list[str]:
        s = self.sectors.get(sector_id)
        if not s:
            raise KeyError(f"unknown sector {sector_id!r}; choose from {sorted(self.sectors)}")
        return sorted(c for g in s["groups"] for i in g["industries"] for c in i["sic"])

    def name(self, sector_id: str) -> str:
        return self.sectors[sector_id]["name"]

    def typical_beta(self, sic: str | int | None) -> dict:
        """Illustrative sector beta (taxonomy.json "typical_beta") for when no price-based beta
        may be shown: {value, sector, basis}."""
        betas = self.doc.get("typical_beta") or {}
        c = self.classify(sic)
        sid = c["sector"] if c else None
        value = betas.get(sid, betas.get("_default", 1.0))
        return {"value": value, "sector": c["sector_name"] if c else None,
                "basis": f"industry-typical beta for {c['sector_name'] if c else 'an unclassified company'} (illustrative)"}


@lru_cache(maxsize=4)
def load(path: str | Path = DEFAULT_PATH) -> Taxonomy:
    return Taxonomy(json.loads(Path(path).read_text()))
