"""Backfill: statement items SEC filings lack, from Yahoo fundamentals (private runs only).

SEC filings stay the source. A Yahoo value is added only where no filed record exists
for the same concept and period, and only for periods the filings already define (the
fiscal year and quarter labels come from the SEC record with the same end date), so a
backfilled value can never move or relabel a period. Each added record has method
"yahoo_backup", and company detail lists them under "backfill".

Point-in-time: Yahoo gives the period end, not the filing date, so a period counts only
once it would have been filed: 60 days after a fiscal year end, 40 after a quarter end.

Not published on the public site (showcase mode skips any run that carries backfill).
"""
from __future__ import annotations

from datetime import date, timedelta

METHOD = "yahoo_backup"
FILING_LAG = {"12M": 60, "3M": 40}
# Yahoo item -> (concept id, sign): sign -1 flips Yahoo's negative capex to the filed convention
ITEMS = {
    "TotalRevenue": ("revenue", 1), "CostOfRevenue": ("cost_of_goods_and_services_sold", 1),
    "GrossProfit": ("gross_profit", 1), "OperatingIncome": ("operating_income_loss", 1),
    "ReconciledDepreciation": ("depreciation_amortization_cf", 1), "InterestExpense": ("interest_expense", 1),
    "InterestIncome": ("interest_income", 1), "PretaxIncome": ("pretax_income_loss", 1),
    "TaxProvision": ("income_taxes", 1), "NetIncome": ("net_income", 1),
    "ResearchAndDevelopment": ("research_and_development_expenses", 1),
    "SellingGeneralAndAdministration": ("selling_general_and_admin_expenses", 1),
    "OperatingCashFlow": ("operating_cash_flow", 1), "CapitalExpenditure": ("capital_expenses", -1),
    "CashCashEquivalentsAndShortTermInvestments": ("cash_and_marketable_securities", 1),
    "LongTermDebt": ("long_term_debt", 1), "CurrentDebt": ("short_term_debt", 1),
    "StockholdersEquity": ("all_equity_balance", 1), "TotalAssets": ("assets", 1),
    "TotalLiabilitiesNetMinorityInterest": ("liabilities", 1), "CurrentAssets": ("current_assets_total", 1),
    "CurrentLiabilities": ("current_liabilities_total", 1), "OrdinarySharesNumber": ("shares_year_end", 1),
    "DilutedAverageShares": ("shares_fully_diluted_average", 1),
}


def _close(a: str, b: str, days: int = 7) -> bool:      # 52/53-week years end up to 6 days off month-end
    return abs((date.fromisoformat(a) - date.fromisoformat(b)).days) <= days


def backfill_records(records: list[dict], fundamentals: dict | None, reg, as_of: str) -> list[dict]:
    """New records for (concept, period) pairs the filings don't have."""
    if not fundamentals or not fundamentals.get("series"):
        return []
    cutoff = date.fromisoformat(as_of)
    have = {(r["concept"], r["end"], r.get("months")) for r in records}
    have_instant = {(r["concept"], r["end"]) for r in records if r.get("period_type") == "instant"}
    # fiscal labels by period end, from the filings: 12-month and 3-month durations
    labels: dict[tuple[int, str], dict] = {}
    for r in records:
        if r.get("period_type") == "duration" and r.get("months") in (12, 3) and r.get("fiscal_year"):
            labels.setdefault((r["months"], r["end"]), r)
    added = []
    for name, rows in fundamentals["series"].items():
        freq = "12M" if name.startswith("annual") else "3M"
        item = name.removeprefix("annual").removeprefix("quarterly")
        if item not in ITEMS:
            continue
        cid, sign = ITEMS[item]
        c = reg.concepts.get(cid)
        if c is None:
            continue
        months = 12 if freq == "12M" else 3
        for row in rows:
            end, v = row["end"], row["value"]
            if row.get("currency") not in (None, "USD") or v is None:
                continue
            if date.fromisoformat(end) + timedelta(days=FILING_LAG[freq]) > cutoff:
                continue
            ref = next((r for (m, e), r in labels.items() if m == months and _close(e, end)), None)
            if ref is None:
                continue                      # a period the filings don't define: never invent one
            instant = c.period_type == "instant"
            if (instant and (cid, ref["end"]) in have_instant) or (not instant and (cid, ref["end"], months) in have):
                continue                      # filed value wins
            added.append({
                "concept": cid, "statement": c.statement, "period_type": c.period_type,
                "unit": "shares" if c.statement == "SHARES" else "USD",
                "start": None if instant else ref["start"], "end": ref["end"], "months": None if instant else months,
                "fiscal_year": ref["fiscal_year"], "fiscal_period": ref["fiscal_period"],
                "value": sign * v, "value_as_filed": None, "restated": False, "method": METHOD,
                "source": {"tags": [f"yahoo:{name}"], "accn": None, "filed": None, "form": None},
            })
            if instant:
                have_instant.add((cid, ref["end"]))
            else:
                have.add((cid, ref["end"], months))
    return added
