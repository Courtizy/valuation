"""Freeze the SEC facts this study uses into inputs.json (needs network once).

    SEC_USER_AGENT="Your Name you@example.com" python studies/sysco-fy2026/build_inputs.py
    python studies/sysco-fy2026/build_inputs.py --facts path/to/CIK0000096021.json   # offline

Point in time: the "known" block keeps only facts filed on or before CUTOFF
(the FY2025 10-K), first-filed value per period, so later restatements can't
leak in. The "outcome" block holds the FY2026 10-K values, used only to score
the forecast. Market inputs are typed in below with their source and date.
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.request
from pathlib import Path

CIK = "0000096021"
CUTOFF = "2025-08-22"                       # FY2025 10-K filed, accession 0000096021-25-000099
OUTCOME_FILED = "2026-08-21"                # FY2026 10-K
FY = {"FY2022": "2022-07-02", "FY2023": "2023-07-01", "FY2024": "2024-06-29", "FY2025": "2025-06-28",
      "FY2026": "2026-06-27"}

# line -> us-gaap tag (sign as filed; IncreaseDecrease* > 0 means the asset grew, a use of cash)
DURATION = {
    "revenue": "RevenueFromContractWithCustomerExcludingAssessedTax",
    "operating_income": "OperatingIncomeLoss",
    "net_income": "NetIncomeLoss",
    "pretax_income": "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    "income_tax": "IncomeTaxExpenseBenefit",
    "net_interest_expense": "InterestIncomeExpenseNonoperatingNet",      # filed negative
    "depreciation_amortization": "DepreciationAndAmortization",
    "share_based_comp": "ShareBasedCompensation",
    "capex": "PaymentsToAcquireProductiveAssets",
    "operating_cash_flow": "NetCashProvidedByUsedInOperatingActivities",
    "chg_receivables": "IncreaseDecreaseInAccountsAndNotesReceivable",
    "chg_inventory": "IncreaseDecreaseInFinishedGoodsAndWorkInProcessInventories",
    "chg_payables": "IncreaseDecreaseInAccountsPayable",
}
INSTANT = {
    "receivables": "AccountsNotesAndLoansReceivableNetCurrent",
    "inventory": "InventoryFinishedGoodsNetOfReserves",
    "payables": "AccountsPayableCurrent",
    "debt_total": "DebtAndCapitalLeaseObligations",
    "cash": "CashAndCashEquivalentsAtCarryingValue",
    "operating_lease_liability": "OperatingLeaseLiability",
}
# Market inputs as they stood on CUTOFF. "available_at_cutoff" is False where the
# vintage published before the cutoff could not be retrieved and a later one stands in.
MARKET = {
    "risk_free": {"value": 0.0426, "source": "FRED DGS10, 2025-08-22 close", "available_at_cutoff": True},
    "equity_risk_premium": {"value": 0.0433, "source": "Damodaran implied ERP (FCFE) at start of 2025, histimpl.xls",
                            "available_at_cutoff": True},
    "unlevered_beta_food_wholesalers": {"value": 0.65, "source": "Damodaran US 'Food Wholesalers' (13 firms), cash-corrected, "
                                        "January 2026 file; the January 2025 file is not online", "available_at_cutoff": False},
    "unlevered_beta_retail_grocery": {"value": 0.85, "source": "Damodaran US 'Retail (Grocery and Food)' (15 firms), "
                                      "cash-corrected, January 2026 file: the industry the engine maps SIC 5140 to",
                                      "available_at_cutoff": False},
    "industry_debt_to_equity": {"value": 0.47, "source": "Damodaran 'Food Wholesalers' market D/E, January 2026 file",
                                "available_at_cutoff": False},
}


def _load(path: str | None) -> dict:
    if path:
        return json.loads(Path(path).read_text())
    ua = os.environ.get("SEC_USER_AGENT") or exit("set SEC_USER_AGENT (the SEC requires contact details)")
    req = urllib.request.Request(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{CIK}.json", headers={"User-Agent": ua})
    return json.load(urllib.request.urlopen(req, timeout=60))


def _pick(units: list[dict], end: str, duration: bool, filed_max: str | None, filed_exact: str | None) -> dict | None:
    rows = [x for x in units if x["end"] == end and x.get("form") == "10-K"
            and (not duration or x.get("fp") == "FY")
            and (filed_max is None or x["filed"] <= filed_max)
            and (filed_exact is None or x["filed"] == filed_exact)]
    if duration:
        rows = [x for x in rows if x.get("start") and int(x["end"][:4]) * 12 + int(x["end"][5:7])
                - int(x["start"][:4]) * 12 - int(x["start"][5:7]) >= 11]
    if not rows:
        return None
    x = min(rows, key=lambda r: r["filed"])            # first filed = what a reader saw then
    return {"value": x["val"] / 1e6, "accn": x["accn"], "filed": x["filed"], "end": x["end"]}


def build(facts: dict) -> dict:
    g = facts["facts"]["us-gaap"]
    known, outcome = {}, {}
    for kind, table in (("duration", DURATION), ("instant", INSTANT)):
        for line, tag in table.items():
            units = g[tag]["units"]["USD"]
            known[line] = {"tag": f"us-gaap:{tag}", **{fy: _pick(units, end, kind == "duration", CUTOFF, None)
                                                     for fy, end in FY.items() if fy != "FY2026"}}
            outcome[line] = {"tag": f"us-gaap:{tag}", "FY2026": _pick(units, FY["FY2026"], kind == "duration", None,
                                                                    OUTCOME_FILED)}
    sh = [x for x in facts["facts"]["dei"]["EntityCommonStockSharesOutstanding"]["units"]["shares"]
          if x["filed"] == CUTOFF][0]
    known["shares_outstanding"] = {"tag": "dei:EntityCommonStockSharesOutstanding",
                                   "cover": {"value": sh["val"] / 1e6, "accn": sh["accn"], "filed": sh["filed"], "end": sh["end"]}}
    return {"company": "Sysco Corporation", "ticker": "SYY", "cik": CIK, "units": "USD millions; shares in millions",
            "cutoff": CUTOFF, "cutoff_filing": "10-K for fiscal 2025, accession 0000096021-25-000099",
            "outcome_filing": "10-K for fiscal 2026, accession 0000096021-26-000033 (scoring only)",
            "known": known, "outcome": outcome, "market": MARKET}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--facts", help="a saved companyfacts JSON instead of fetching")
    a = ap.parse_args()
    out = Path(__file__).with_name("inputs.json")
    out.write_text(json.dumps(build(_load(a.facts)), indent=1) + "\n")
    print(f"wrote {out}")
