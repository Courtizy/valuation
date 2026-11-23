"""The Refresh's balance-sheet check (backlog item 20a)."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_bs", ROOT / "scripts" / "check_balance_sheets.py")
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)

AS_OF, END = "2026-11-23", "2026-06-27"


def _company(tmp_path, ticker, bridge_debt, values, facts):
    run = tmp_path / ticker / AS_OF
    (run / "model_results").mkdir(parents=True)
    (tmp_path / ticker / "raw").mkdir()
    fact = lambda tag, v: {"taxonomy": "us-gaap", "tag": tag, "unit": "USD", "value": v, "start": None,  # noqa: E731
                           "end": END, "filed": "2026-08-21"}
    (tmp_path / ticker / "raw" / "raw_filing.json").write_text(json.dumps({"facts": [fact(t, v) for t, v in facts.items()]}))
    (run / "company_detail.json").write_text(json.dumps({"views": {"ttm": [{"end": END, "values": values}]}}))
    (run / "model_results" / "dcf.json").write_text(json.dumps({"details": {"bridge": {"debt": bridge_debt}}}))


def test_flags_missing_debt_receivables_and_inventory(tmp_path):
    # Sysco before registry 0.3.1: no debt in the bridge, no receivables or inventory in detail
    _company(tmp_path, "SYY", 0, {}, {"DebtAndCapitalLeaseObligations": 13.3e9,
                                      "AccountsNotesAndLoansReceivableNetCurrent": 5.9e9,
                                      "InventoryFinishedGoodsNetOfReserves": 5.3e9})
    _company(tmp_path, "OK", 13.2e9, {"trade_receivables": 1, "inventories": 1}, {"DebtAndCapitalLeaseObligations": 13.3e9})
    rows = check.check_company("SYY", tmp_path, AS_OF) + check.check_company("OK", tmp_path, AS_OF)
    assert sorted(r["item"] for r in rows if r["ticker"] == "SYY") == ["debt", "inventory", "receivables"]
    assert not [r for r in rows if r["ticker"] == "OK"]


def test_unexplained_rows_stop_the_publish(tmp_path):
    _company(tmp_path, "SYY", 0, {"trade_receivables": 1, "inventories": 1}, {"LongTermDebt": 10e9})
    u = tmp_path / "u.json"
    u.write_text(json.dumps({"tickers": ["SYY"]}))
    exc = tmp_path / "exc.json"
    args = ["--as-of", AS_OF, "--data-dir", str(tmp_path), "--universe", str(u), "--exceptions", str(exc)]
    assert check.main(args) == 1
    exc.write_text(json.dumps({"SYY": {"debt": "debt is held by a finance subsidiary"}}))
    assert check.main(args) == 0
