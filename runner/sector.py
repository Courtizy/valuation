"""Sector screens: sector:/sic-of:/sic:/traits:/list: specs -> data/sectors/{id}/{as_of}/sector.json."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from L0_ingest.sec_sector import SecSectorAdapter, screen_year
from L1_detail import sector as l1_sector
from L1_detail import taxonomy as l1_taxonomy
from lineage import lineage_block
from runner.paths import Paths


SECTOR_KINDS = ("sector", "sic", "sic-of", "traits", "list")


def parse_sector_spec(spec: str) -> tuple[str, str]:
    """'sector:technology' | 'sic-of:AAPL' | 'sic:3674' | 'traits:stage=high growth;...' | 'list:my_semis'
    -> (kind, value)."""
    kind, _, value = spec.partition(":")
    kind, value = kind.strip().lower(), value.strip()
    if kind not in SECTOR_KINDS or not value:
        raise ValueError("sector must look like sector:technology, sic-of:AAPL, sic:3674, traits:stage=high growth, "
                         f"or list:name; got {spec!r}")
    if kind == "sector" and value not in l1_taxonomy.load().sectors:
        raise ValueError(f"unknown sector {value!r}; choose from {', '.join(sorted(l1_taxonomy.load().sectors))}")
    if kind == "sic" and not (value.isdigit() and len(value) == 4):
        raise ValueError(f"SIC code must be 4 digits: {value!r}")
    if kind == "list" and not all(c.isalnum() or c in "_-" for c in value):
        raise ValueError(f"list name may use letters, digits, _ and -: {value!r}")
    return kind, value


def run_sector(spec: str, as_of: str, paths: Paths, adapter_factory: Callable[[], SecSectorAdapter],
               lists_dir: Path = Path("sectors"), limit: int | None = None) -> Path:
    """Screen one sector and write data/sectors/{id}/{as_of}/sector.json. Returns its path."""
    kind, value = parse_sector_spec(spec)
    ad = adapter_factory()
    raw_p = paths.raw_screen(as_of)
    if raw_p.exists():
        raw = json.loads(raw_p.read_text())
    else:
        raw = ad.fetch_frames(screen_year(as_of))
        raw_p.parent.mkdir(parents=True, exist_ok=True)
        raw_p.write_text(json.dumps(raw))
    tickers = ad.tickers()
    tax = l1_taxonomy.load()
    members, label, extra_notes, member_sic = None, None, [], {}

    if kind == "sic-of":
        who = value.upper()
        cik = ad.resolve_cik(who)[0]
        info = ad.industry(cik)
        if not info.get("sic"):
            raise ValueError(f"no SIC code on file for {who}")
        c = tax.classify(info["sic"])
        if not c:
            raise ValueError(f"SIC {info['sic']} for {who} isn't in sectors/taxonomy.json; add it, or screen sic:{info['sic']}")
        kind, value = "sector", c["sector"]
        extra_notes.append(f"{who} files under SIC {info['sic']} ({(info.get('description') or '').title()}): "
                           f"{c['sector_name']} › {c['group_name']} › {c['industry_name']}")
    if kind == "sector":
        members = []
        for code in tax.codes(value):
            lst = ad.sic_members(code)
            p = paths.sic_list(as_of, code)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(lst, indent=2))
            for cik in lst["ciks"]:
                if cik not in member_sic:
                    member_sic[cik] = code
                    members.append(cik)
        label = tax.name(value)
    elif kind == "sic":
        lst = ad.sic_members(value)
        p = paths.sic_list(as_of, value)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(lst, indent=2))
        members = lst["ciks"]
        member_sic = {c: value for c in members}
        label = f"SIC {value} · {lst['description'].title()}" if lst.get("description") else f"SIC {value}"
    elif kind == "list":
        f = lists_dir / f"{value}.json"
        if not f.exists():
            raise FileNotFoundError(f"{f} not found; see sectors/README.md")
        spec_doc = json.loads(f.read_text())
        by_ticker = {t["ticker"]: t["cik"] for t in tickers}
        want = [str(t).upper() for t in spec_doc.get("tickers", [])]
        unknown = [t for t in want if t not in by_ticker]
        if unknown:
            extra_notes.append(f"not in the SEC ticker list: {', '.join(unknown)}")
        members = [by_ticker[t] for t in want if t in by_ticker]
        member_sic = {c: s for c in members if (s := ad.industry(c).get("sic"))}
        label = spec_doc.get("label") or value
        tickers = [t for t in tickers if t["ticker"] in want] + tickers   # listed share class wins

    doc = l1_sector.build_sector(raw, kind=kind, value=value, as_of=as_of, tickers=tickers,
                                 members=members, label=label, limit=limit, member_sic=member_sic, taxonomy=tax)
    doc["notes"] = extra_notes + doc["notes"]
    doc["lineage"] = lineage_block(as_of, [raw_p] + sorted(paths.sic_list(as_of, c) for c in set(member_sic.values())
                                                          if paths.sic_list(as_of, c).exists()))
    out = paths.sector(doc["id"], as_of)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2))
    return out
