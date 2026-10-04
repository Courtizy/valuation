"""Synthetic demo sector: DEMO and its six detailed peers plus sixteen screen-only companies,
across Capital Goods (Machinery, Electrical Equipment) and Transportation (Ground Transportation),
so the Sector > Group > Industry switch has real levels. Built by the real screen code."""
from __future__ import annotations

import json
import random
from pathlib import Path

from L3_app.demo.companies import AS_OF, DEMO_SIC

# Screen-only members (figures only, no company detail): seeded, so every rebuild is identical.
# ticker, SIC; tickers start ZZ so they can't be mistaken for real listings.
SCREEN_ONLY = [("ZZG", "3560"), ("ZZH", "3561"), ("ZZI", "3564"), ("ZZJ", "3569"), ("ZZK", "3530"), ("ZZL", "3560"),
               ("ZZM", "3612"), ("ZZN", "3620"), ("ZZO", "3621"), ("ZZP", "3612"),
               ("ZZQ", "4213"), ("ZZR", "4210"), ("ZZS", "4213"), ("ZZT", "4213"), ("ZZU", "4210"), ("ZZV", "4213")]


def _screen_peer(t: str, sic: str) -> tuple:
    """revenue, 3-yr growth, gross m., op. m., net m., D&A/s, capex/s, FCF wobble, assets/s, equity/assets, debt/assets"""
    rng = random.Random(sum(map(ord, t)) * 7)
    truck = sic.startswith("42")
    rev = rng.uniform(0.6e9, 9.5e9)
    g = rng.uniform(-0.03, 0.16)
    gm = rng.uniform(0.18, 0.30) if truck else rng.uniform(0.28, 0.52)
    om = gm - rng.uniform(0.10, 0.22)
    return (t, rev, g, gm, om, om * 0.72, rng.uniform(0.03, 0.09), rng.uniform(0.03, 0.12), rng.uniform(0.0, 0.05),
            rng.uniform(0.7, 1.5), rng.uniform(0.35, 0.70), rng.uniform(0.0, 0.35))


SECTOR_PEERS = [_screen_peer(t, sic) for t, sic in SCREEN_ONLY]
SECTOR_SIC = {**DEMO_SIC, **dict(SCREEN_ONLY)}


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
        cik, name = 9_910_001 + j, f"Synthetic Industrials {t[-1]} (synthetic)"
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


def write_demo_sector(data_dir: Path, details: dict) -> Path:
    """details: the detailed companies that belong to the sector (DEMO and its peers)."""
    from L1_detail.sector import build_sector
    from L1_detail.taxonomy import load
    raw, tickers = _demo_frames(details)
    doc = build_sector(raw, kind="list", value="demo-industrials", as_of=AS_OF, tickers=tickers,
                       members=[t["cik"] for t in tickers], label="Demo Industrials (Synthetic)",
                       member_sic={t["cik"]: SECTOR_SIC[t["ticker"]] for t in tickers}, taxonomy=load())
    doc["demo"] = True
    doc["notes"].insert(0, "synthetic demo sector: DEMO, six detailed peers (ZZA–ZZF) and sixteen screen-only companies (ZZG–ZZV)")
    out = data_dir / "sectors" / doc["id"] / AS_OF / "sector.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2))
    return out
