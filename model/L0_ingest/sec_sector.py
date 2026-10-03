"""Adapter for sector screening: who is in a sector, and a few figures for all of them.

Sources (all SEC, all free):
  frames       https://data.sec.gov/api/xbrl/frames/us-gaap/{tag}/USD/{period}.json
               one line item for every filer in one call; period CY2025 (a ~year
               duration mapped to that calendar year) or CY2025Q4I (an instant)
  SIC members  https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&SIC={sic}...
               EDGAR's company list for an industry code, 100 per page; includes
               filers that stopped reporting (the screen drops anyone without frames data)
  submissions  a company's own SIC code (SecCompanyFactsAdapter.industry)

L0 stays faithful: frames rows are kept as returned (slimmed to the fields used),
and a frame the SEC doesn't have (404) is recorded as missing, not guessed.
"""
from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone

from .http import HttpError
from .schema import SCHEMA_VERSION
from .sec_companyfacts import TICKERS_URL, SecCompanyFactsAdapter, normalize_cik  # noqa: F401

FRAMES_URL = "https://data.sec.gov/api/xbrl/frames/us-gaap/{tag}/USD/{period}.json"
SIC_URL = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&SIC={sic}"
           "&owner=include&start={start}&count=100&hidefilings=0")
MAX_SIC_PAGES = 40

# Line items for the screen. Duration tags are read for calendar years: revenue and
# cash flow for four years (growth, 3-year CAGR, FCF-margin stability), the rest
# for the latest year and the one before (a filer that is late falls back a year).
REVENUE_TAGS = ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet",
                "RevenueFromContractWithCustomerIncludingAssessedTax"]
DA_TAGS = ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization",
           "DepreciationAmortizationAndAccretionNet"]
# when none of DA_TAGS is reported, D&A = Depreciation + AmortizationOfIntangibleAssets
DA_PARTS = ["Depreciation", "AmortizationOfIntangibleAssets"]
LATEST_ONLY = ["GrossProfit", "OperatingIncomeLoss", "NetIncomeLoss", *DA_TAGS, *DA_PARTS]
CFO_TAG = "NetCashProvidedByUsedInOperatingActivities"
CAPEX_TAGS = ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"]
CASH_FLOW = [CFO_TAG, *CAPEX_TAGS]
TAG_GROUPS = {"revenue": REVENUE_TAGS, "depreciation": DA_TAGS, "depreciation_parts": DA_PARTS,
              "cfo": CFO_TAG, "capex": CAPEX_TAGS}
INSTANT = ["Assets", "Liabilities", "StockholdersEquity", "CashAndCashEquivalentsAtCarryingValue",
           "LongTermDebt", "LongTermDebtNoncurrent", "LongTermDebtCurrent", "ShortTermBorrowings"]


def frame_plan(year: int) -> list[tuple[str, str]]:
    """(tag, period) pairs the screen needs for a latest calendar year."""
    plan = [(t, f"CY{y}") for y in (year, year - 1, year - 2, year - 3) for t in REVENUE_TAGS]
    plan += [(t, f"CY{y}") for y in (year, year - 1) for t in LATEST_ONLY]   # year-1: fallback when a filer is late
    plan += [(t, f"CY{y}") for y in (year, year - 1, year - 2, year - 3) for t in CASH_FLOW]
    plan += [(t, f"CY{y}Q4I") for y in (year, year - 1) for t in INSTANT]
    return list(dict.fromkeys(plan))


def screen_year(as_of: str) -> int:
    """Latest calendar year most annual reports cover by as_of (10-Ks land by ~March)."""
    d = datetime.strptime(as_of, "%Y-%m-%d")
    return d.year - 1 if d.month >= 4 else d.year - 2


def parse_sic_page(page: str) -> tuple[list[str], str | None]:
    """CIKs on one EDGAR SIC results page, and the SIC description if shown."""
    ciks = list(dict.fromkeys(m.zfill(10) for m in re.findall(r"CIK=(\d{1,10})", page)))
    m = re.search(r"SIC\s*(?:<[^>]+>\s*)*(\d{4})\s*-\s*([^<\n]+)", page)
    return ciks, (html.unescape(m.group(2)).strip() if m else None)


class SecSectorAdapter(SecCompanyFactsAdapter):
    name = "sec_frames"

    def frame(self, tag: str, period: str) -> list[list] | None:
        """Rows [cik, name, start, end, val] for one frame; None if the SEC has no such frame."""
        url = FRAMES_URL.format(tag=tag, period=period)
        try:
            data, _, _ = self._get(url, f"frames_{tag}_{period}.json")
        except HttpError as e:
            if e.status == 404:
                return None
            raise
        rows = json.loads(data).get("data") or []
        return [[r.get("cik"), r.get("entityName"), r.get("start"), r.get("end"), r.get("val")] for r in rows]

    def fetch_frames(self, year: int) -> dict:
        """raw_screen document: every frame in frame_plan(year)."""
        frames, missing = {}, []
        for tag, period in frame_plan(year):
            rows = self.frame(tag, period)
            if rows is None:
                missing.append(f"{tag}/{period}")
            else:
                frames[f"{tag}/{period}"] = rows
        return {
            "schema_version": SCHEMA_VERSION, "source": self.name,
            "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "year": year, "tags": TAG_GROUPS, "frames": frames, "missing_frames": missing,
        }

    def sic_members(self, sic: str) -> dict:
        """{"sic", "description", "ciks"} from EDGAR's company list for an industry code."""
        if not re.fullmatch(r"\d{4}", str(sic)):
            raise ValueError(f"SIC code must be 4 digits: {sic!r}")
        ciks: list[str] = []
        desc = None
        for page in range(MAX_SIC_PAGES):
            data, _, _ = self._get(SIC_URL.format(sic=sic, start=page * 100), f"sic_{sic}_{page}.html")
            found, d = parse_sic_page(data.decode("utf-8", "replace"))
            desc = desc or d
            new = [c for c in found if c not in ciks]
            ciks += new
            if len(found) < 100 or not new:
                break
        return {"sic": str(sic), "description": desc, "ciks": ciks}

    def tickers(self) -> list[dict]:
        data, _, _ = self._get(TICKERS_URL, "company_tickers.json")
        return [{"cik": normalize_cik(r["cik_str"]), "ticker": r["ticker"].upper(), "name": r.get("title")}
                for r in json.loads(data).values()]
