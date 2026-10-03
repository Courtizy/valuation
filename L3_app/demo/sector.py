"""Synthetic demo sector: the three demo companies plus ten made-up peers, built by the real screen code."""
from __future__ import annotations

import json
from pathlib import Path

from L3_app.demo.companies import AS_OF, DEMO_SIC

# Synthetic sector peers (screen figures only, no company detail). Tickers start with
# "ZZ" so they can't be mistaken for real listings.
SECTOR_PEERS = [
    # ticker, revenue (CY2025), 3-yr growth, gross m., op. m., net m., D&A/s, capex/s, FCF wobble, assets/s, equity/assets, debt/assets
    ("ZZA", 9.2e9, 0.06, 0.40, 0.17, 0.12, 0.05, 0.06, 0.01, 1.1, 0.55, 0.18),
    ("ZZB", 7.5e9, 0.11, 0.47, 0.21, 0.15, 0.04, 0.04, 0.02, 0.9, 0.60, 0.12),
    ("ZZC", 6.1e9, 0.03, 0.33, 0.11, 0.07, 0.05, 0.07, 0.01, 1.2, 0.45, 0.28),
    ("ZZD", 4.8e9, 0.19, 0.52, 0.09, 0.05, 0.03, 0.03, 0.05, 0.8, 0.65, 0.05),
    ("ZZE", 3.9e9, -0.02, 0.29, 0.06, 0.03, 0.06, 0.08, 0.03, 1.4, 0.40, 0.33),
    ("ZZF", 3.1e9, 0.08, 0.44, 0.19, 0.14, 0.04, 0.05, 0.01, 1.0, 0.58, 0.15),
    ("ZZG", 2.4e9, 0.25, 0.61, -0.04, -0.07, 0.02, 0.02, 0.09, 0.7, 0.70, 0.00),
    ("ZZH", 1.8e9, 0.05, 0.38, 0.14, 0.10, 0.05, 0.06, 0.02, 1.1, 0.50, 0.20),
    ("ZZI", 1.2e9, 0.14, 0.49, 0.16, 0.12, 0.03, 0.04, 0.03, 0.9, 0.62, 0.08),
    ("ZZJ", 0.7e9, 0.01, 0.31, 0.08, 0.05, 0.06, 0.09, 0.02, 1.3, 0.48, 0.25),
]


def _demo_frames(details: dict) -> tuple[dict, list[dict]]:
    """Frames-shaped rows for the demo companies (from their annual statements)
    and the synthetic peers, so the real screen code builds the demo sector."""
    frames: dict[str, list] = {}
    tickers = []

    def put(tag, period, cik, name, val):
        if val is not None:
            frames.setdefault(f"{tag}/{period}", []).append([cik, name, None, None, val])

    for i, (t, d) in enumerate(details.items()):
        cik, name = 9_900_001 + i, d["entity"]["name"]
        tickers.append({"cik": str(cik).zfill(10), "ticker": t, "name": name})
        for p in d["views"]["annual"]:
            v, y = p["values"], p["fiscal_year"]
            put("Revenues", f"CY{y}", cik, name, v.get("revenue"))
            put("GrossProfit", f"CY{y}", cik, name, v.get("gross_profit"))
            put("OperatingIncomeLoss", f"CY{y}", cik, name, v.get("operating_income_loss"))
            put("NetIncomeLoss", f"CY{y}", cik, name, v.get("net_income"))
            put("DepreciationDepletionAndAmortization", f"CY{y}", cik, name, v.get("depreciation_amortization_cf"))
            put("NetCashProvidedByUsedInOperatingActivities", f"CY{y}", cik, name, v.get("operating_cash_flow"))
            put("PaymentsToAcquirePropertyPlantAndEquipment", f"CY{y}", cik, name, v.get("capital_expenses"))
            put("Assets", f"CY{y}Q4I", cik, name, v.get("assets"))
            put("StockholdersEquity", f"CY{y}Q4I", cik, name, v.get("all_equity_balance"))
            put("Liabilities", f"CY{y}Q4I", cik, name, v.get("liabilities"))
            put("CashAndCashEquivalentsAtCarryingValue", f"CY{y}Q4I", cik, name, v.get("cash_and_marketable_securities"))
            put("LongTermDebtNoncurrent", f"CY{y}Q4I", cik, name, v.get("long_term_debt"))
            put("ShortTermBorrowings", f"CY{y}Q4I", cik, name, v.get("short_term_debt"))
    for j, (t, rev, g, gm, om, nm, da, cx, wob, a_s, e_a, d_a) in enumerate(SECTOR_PEERS):
        cik, name = 9_910_001 + j, f"Synthetic peer {t[-1]} (synthetic)"
        tickers.append({"cik": str(cik).zfill(10), "ticker": t, "name": name})
        for k, y in enumerate(range(2022, 2026)):
            r = rev / (1 + g) ** (2025 - y)
            w = wob * (1 if k % 2 else -1)
            put("Revenues", f"CY{y}", cik, name, r)
            put("GrossProfit", f"CY{y}", cik, name, r * gm)
            put("OperatingIncomeLoss", f"CY{y}", cik, name, r * om)
            put("NetIncomeLoss", f"CY{y}", cik, name, r * nm)
            put("DepreciationDepletionAndAmortization", f"CY{y}", cik, name, r * da)
            put("NetCashProvidedByUsedInOperatingActivities", f"CY{y}", cik, name, r * (nm + da + w))
            put("PaymentsToAcquirePropertyPlantAndEquipment", f"CY{y}", cik, name, r * cx)
            assets = r * a_s
            put("Assets", f"CY{y}Q4I", cik, name, assets)
            put("StockholdersEquity", f"CY{y}Q4I", cik, name, assets * e_a)
            put("CashAndCashEquivalentsAtCarryingValue", f"CY{y}Q4I", cik, name, assets * 0.08)
            put("LongTermDebt", f"CY{y}Q4I", cik, name, assets * d_a)
    return {"year": 2025, "frames": frames}, tickers


def write_demo_sector(site_dir: Path, details: dict) -> Path:
    from L1_detail.sector import build_sector
    from L1_detail.taxonomy import load
    raw, tickers = _demo_frames(details)
    doc = build_sector(raw, kind="list", value="demo", as_of=AS_OF, tickers=tickers,
                       members=[t["cik"] for t in tickers], label="Demo Sector (Synthetic)",
                       member_sic={t["cik"]: DEMO_SIC[t["ticker"]] for t in tickers}, taxonomy=load())
    doc["demo"] = True
    doc["notes"].insert(0, "synthetic demo sector: three demo companies plus ten made-up peers (tickers ZZA–ZZJ)")
    out = site_dir / "data" / "sectors" / doc["id"] / AS_OF / "sector.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2))
    return out
