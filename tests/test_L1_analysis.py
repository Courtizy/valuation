"""L1 stage 2 reformulation and ratios. Run: pytest tests/test_L1_analysis.py"""
from __future__ import annotations

import pytest

from valuation.L1_detail.analysis import (altman_z, analyze_view, credit_metrics, load_classification,
                                managerial_balance_sheet, managerial_ratios, mbs_free_cash_flow,
                                reformulated_balance_sheet, reformulated_ratios, signals,
                                total_liabilities, traditional_ratios)

A = pytest.approx


def at_year(sales, cogs, dep, ebit, interest, tax, ni, cash, ar, inv, prepaid, fa, ap, std, accrued, ltd):
    """A small manufacturing company in the managerial-balance-sheet worked example."""
    ca = cash + ar + inv + prepaid
    cl = ap + std + accrued
    return {
        "revenue": sales, "cost_of_goods_and_services_sold": cogs, "gross_profit": sales - cogs,
        "depreciation_expense": dep, "operating_income_loss": ebit, "interest_expense": interest,
        "pretax_income_loss": ebit - interest, "income_taxes": tax, "net_income": ni,
        "cash_and_marketable_securities": cash, "trade_receivables": ar, "inventories": inv,
        "current_assets_total": ca, "assets": ca + fa, "trade_payables": ap, "short_term_debt": std,
        "current_liabilities_total": cl, "long_term_debt": ltd, "liabilities": cl + ltd,
        "ebitda": ebit + dep,
    }


T1 = at_year(1100, 772, 40, 288, 54, 117, 117, 200, 357.5, 460, 55, 480, 337.5, 158, 55, 425)
T = at_year(1350, 975, 45, 330, 70, 130, 130, 160, 445, 580, 60, 560, 435, 218, 60, 415)
CFG = load_classification({"marginal_tax_rate": 0.5})


def test_managerial_balance_sheet_balances():
    m = managerial_balance_sheet(T)
    assert m["cash"] == 160 and m["wcr"] == A(590) and m["fixed_assets"] == A(560)
    assert m["invested_capital"] == A(1310) == m["capital_employed"]
    assert m["equity"] == A(677)


def test_managerial_ratios_worked_example():
    r = managerial_ratios(T, T1, CFG)
    assert r["nsf"] == A(58)
    assert r["nlf"] == A(532)
    assert r["liquidity_ratio"] == A(532 / 590)
    assert r["wcr_to_sales"] == A(590 / 1350)
    assert r["collection_period_days"] == A(120.3148, rel=1e-5)
    assert r["days_inventory"] == A(217.1282, rel=1e-5)
    assert r["inventory_turnover"] == A(975 / 580)
    assert r["payment_period_days"] == A(435 / ((975 + 580 - 460) / 365))
    assert r["current_ratio"] == A(1245 / 713)
    assert r["acid_test"] == A((1245 - 580) / 713)


def test_mbs_fcf_worked_example():
    f = mbs_free_cash_flow(T, T1, CFG)
    assert f["noplat"] == A(165) and f["change_in_wcr"] == A(110)
    assert f["capex_from_balance_sheet"] == A(125)
    assert f["fcf"] == A(-25)
    assert mbs_free_cash_flow(T, None, CFG) == {}


def test_reformulated_identities_hold():
    r = reformulated_ratios(T, T1, CFG)
    for basis in ("avg", "beg"):
        b = r[basis]
        assert b["roce"] == A(b["rnoa"] + b["flev"] * (b["rnoa"] - b["nbc"]))
        assert b["rnoa"] == A(b["rooa"] + b["ollev"] * b["olspread"])
        assert b["rnoa"] == A(r["nopm"] * b["noat"])


def test_reformulated_balance_sheet_split():
    bs = reformulated_balance_sheet(T, CFG)
    assert bs["financial_assets"] == 160
    assert bs["financial_obligations"] == 218 + 415
    assert bs["noa"] == A(1805 - 160 - (1128 - 633))
    assert bs["cse_incl_nci"] == A(677)


def test_leases_can_be_financial():
    v = dict(T, operating_lease_non_current_debt_equivalent=50)
    op = reformulated_balance_sheet(v, CFG)
    fin = reformulated_balance_sheet(v, {**CFG, "leases_are_financial": True})
    assert fin["noa"] == op["noa"] + 50 and fin["nno"] == op["nno"] + 50


def test_total_liabilities_fallback():
    v = {"liabilities_and_equity": 100, "all_equity_balance": 30, "minority_interest_balance": 5}
    assert total_liabilities(v) == (65, "from_equity")
    assert total_liabilities({})[1] == "missing"


def test_traditional_ratios_decompose():
    r = traditional_ratios(T, T1, CFG)
    assert r["roa"] == A(r["profit_margin"] * r["asset_turnover"])
    assert r["profit_margin"] == A((130 + 70 * 0.5) / 1350)
    assert r["roe"] == A(130 / ((677 + 577) / 2))


def test_missing_inputs_give_none_not_zero():
    r = managerial_ratios({"revenue": 10}, None, CFG)
    assert r["collection_period_days"] is None and r["payment_period_days"] is None
    assert reformulated_ratios({"revenue": 10}, None, CFG)["nopm"] is None


def test_altman_z_public_and_private():
    v = {"assets": 2733253, "liabilities": 1427890, "retained_earnings": 48404,
         "current_assets_total": 266913, "current_liabilities_total": 205249,
         "operating_income_loss": 877251, "revenue": 975889}
    z = altman_z(v, market_cap=54.35 * 53000)
    expected = (1.2 * (266913 - 205249) / 2733253 + 1.4 * 48404 / 2733253 + 3.3 * 877251 / 2733253
                + 0.6 * 54.35 * 53000 / 1427890 + 975889 / 2733253)
    assert z["public"] == A(expected)
    assert z["public_zone"] == ("distress" if expected < 1.8 else "grey" if expected < 2.99 else "safe")
    assert z["private"] is not None
    assert altman_z(v)["public"] is None


def test_credit_metrics():
    c = credit_metrics(T)
    assert c["ebit_to_interest"] == A(330 / 70)
    assert c["debt_to_ebitda"] == A((218 + 415) / 375)


def test_signals_yoy():
    s = signals(T, T1, CFG)
    ds = (1350 - 1100) / 1100
    assert s["receivables_signal"] == A(ds - (445 - 357.5) / 357.5)
    assert s["gross_margin_signal"] == A((375 - 328) / 328 - ds)


def test_analyze_view_skips_prior_when_not_a_year_apart():
    periods = [{"label": "FY1", "end": "2020-12-31", "values": T1},
               {"label": "FY3", "end": "2022-12-31", "values": T}]
    out = analyze_view(periods, CFG)
    assert out[1]["ratios"]["traditional"] == {}
    periods[0]["end"] = "2021-12-31"
    assert analyze_view(periods, CFG)[1]["ratios"]["traditional"]["roe"] is not None
