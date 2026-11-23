"""Balance-sheet coverage check, run by the Refresh before it publishes (backlog item 20a).

    python scripts/check_balance_sheets.py --as-of 2026-11-23 [--data-dir data]

For every company built for as_of, compares what the engine used with what the company filed:
  debt          the DCF bridge's debt is under half the largest total-debt tag the company filed
                for the same balance sheet (DebtAndCapitalLeaseObligations or an equivalent)
  receivables   no trade receivables in company detail, while the filer tags a current-receivables
  inventory     no inventory in company detail, while the filer tags an inventory figure
Rows listed in configs/public/balance_sheet_exceptions.json ({"TICKER": {"debt": "why"}}) are
explained. The exit code is 1 when any row is unexplained, which stops the publish step.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UNIVERSE = ROOT / "configs" / "public" / "universe.json"
EXCEPTIONS = ROOT / "configs" / "public" / "balance_sheet_exceptions.json"
DEBT_TOTALS = ("DebtAndCapitalLeaseObligations", "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities",
               "DebtLongtermAndShorttermCombinedAmount", "LongTermDebt")
RECEIVABLES = re.compile(r"^(Accounts|AccountsNotesAndLoans|Notes|Trade|)Receivables?.*Net.*Current$|^ReceivablesNetCurrent$"
                         r"|^AccountsReceivableNetCurrent$|^AccountsNotesAndLoansReceivableNetCurrent$")
INVENTORY = re.compile(r"^Inventory(Net|FinishedGoods.*|.*NetOfReserves)$")
DEBT_SHARE = 0.5


def _instants(facts: list[dict], as_of: str) -> dict[str, dict[str, float]]:
    """{tag: {end: value}} for USD balance-sheet facts filed on or before as_of (latest filing wins)."""
    out: dict[str, dict[str, tuple[str, float]]] = {}
    for f in facts:
        if f.get("start") or f.get("unit") != "USD" or f.get("taxonomy") != "us-gaap" or (f.get("filed") or "") > as_of:
            continue
        slot = out.setdefault(f["tag"], {})
        if f["end"] not in slot or f["filed"] >= slot[f["end"]][0]:
            slot[f["end"]] = (f["filed"], f["value"])
    return {t: {e: v for e, (_, v) in d.items()} for t, d in out.items()}


def check_company(ticker: str, data_dir: Path, as_of: str) -> list[dict]:
    run = data_dir / ticker / as_of
    raw, detail_p, dcf_p = data_dir / ticker / "raw" / "raw_filing.json", run / "company_detail.json", run / "model_results" / "dcf.json"
    if not (raw.exists() and detail_p.exists()):
        return []
    inst = _instants(json.loads(raw.read_text())["facts"], as_of)
    detail = json.loads(detail_p.read_text())
    latest = (detail["views"].get("ttm") or detail["views"].get("annual") or [{}])[-1]
    end, vals = latest.get("end"), latest.get("values") or {}
    rows = []
    if dcf_p.exists():
        bridge = json.loads(dcf_p.read_text())["details"]["bridge"]
        filed = {t: inst[t][end] for t in DEBT_TOTALS if end in inst.get(t, {})}
        if filed:
            tag, top = max(filed.items(), key=lambda kv: kv[1])
            used = bridge.get("debt") or 0
            if top > 0 and used < DEBT_SHARE * top:
                rows.append({"ticker": ticker, "item": "debt", "end": end,
                             "detail": f"bridge debt {used / 1e9:,.1f}B vs {tag} {top / 1e9:,.1f}B filed"})
    for item, key, pattern in (("receivables", "trade_receivables", RECEIVABLES), ("inventory", "inventories", INVENTORY)):
        if vals.get(key):
            continue
        tagged = sorted(t for t in inst if pattern.match(t) and inst[t].get(end))
        if tagged:
            rows.append({"ticker": ticker, "item": item, "end": end,
                         "detail": f"none in company detail; filed as {', '.join(tagged)}"})
    return rows


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--as-of", required=True)
    p.add_argument("--data-dir", type=Path, default=Path("data"))
    p.add_argument("--universe", type=Path, default=UNIVERSE)
    p.add_argument("--exceptions", type=Path, default=EXCEPTIONS)
    a = p.parse_args(argv)
    tickers = list(dict.fromkeys(json.loads(a.universe.read_text()).get("tickers", [])))
    known = json.loads(a.exceptions.read_text()) if a.exceptions.exists() else {}
    rows = [r for t in tickers for r in check_company(t, a.data_dir, a.as_of)]
    for r in rows:
        r["explained"] = (known.get(r["ticker"]) or {}).get(r["item"])
    open_rows = [r for r in rows if not r["explained"]]
    lines = [f"Balance-sheet check {a.as_of}: {len(tickers)} companies, {len(rows)} flagged, {len(open_rows)} unexplained"]
    lines += [f"- {r['ticker']} {r['item']} ({r['end']}): {r['detail']}" + (f". Explained: {r['explained']}" if r["explained"] else "")
              for r in rows]
    print("\n".join(lines))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write("\n".join(lines) + "\n")
    return 1 if open_rows else 0


if __name__ == "__main__":
    sys.exit(main())
