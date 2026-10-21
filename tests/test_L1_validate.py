"""SEC figures checked against themselves (tie-outs) and against Yahoo (L1_detail/validate.py)."""
from valuation.L1_detail.validate import cross_source, tie_outs, validation, warnings_for


def rec(concept, end, value, method="filed", months=12):
    return {"concept": concept, "end": end, "months": months, "period_type": "duration", "value": value, "method": method}


def fund(**series):
    return {"source": "yahoo", "series": {f"annual{k}": [{"end": e, "value": v, "currency": "USD"} for e, v in pts]
                                          for k, pts in series.items()}}


def test_cross_source_agrees_within_two_percent_and_lists_the_rest():
    records = [rec("revenue", "2025-09-27", 100.0), rec("net_income", "2025-09-27", 20.0),
               rec("capital_expenses", "2025-09-27", 5.0), rec("interest_expense", "2025-09-27", 1.0, method="yahoo_backup")]
    x = cross_source(records, fund(TotalRevenue=[("2025-09-30", 101.0)], NetIncome=[("2025-09-30", 25.0)],
                                   CapitalExpenditure=[("2025-09-30", -5.0)], InterestExpense=[("2025-09-30", 1.0)]))
    assert x["compared"] == 3 and x["agree"] == 2                       # Yahoo's own fill isn't compared
    assert [(d["concept"], d["sec"], d["other"]) for d in x["differ"]] == [("net_income", 20.0, 25.0)]
    assert cross_source(records, None) is None


def test_tie_outs_and_warnings():
    checks = [{"name": "balance_sheet_balances", "evaluated": 8, "failed": [{"end": "2025-09-27"}]},
              {"name": "gross_profit_ties", "evaluated": 8, "failed": []}]
    v = validation({"checks": checks}, [rec("net_income", "2025-09-27", 20.0)], fund(NetIncome=[("2025-09-27", 30.0)]))
    assert tie_outs(checks)[0] == {"name": "balance_sheet_balances", "evaluated": 8, "failed": 1, "periods_failed": ["2025-09-27"]}
    w = warnings_for(v)
    assert "balance sheet balances in 1 of 8 periods" in w[0] and "1 of 1 filed figures differ from Yahoo" in w[1]
