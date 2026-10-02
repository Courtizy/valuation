"""L1 stage 2, part 2: statement reformulation and ratios.

Two frameworks, kept side by side and labeled:

  managerial   Managerial balance sheet (cash, working-capital requirement,
               fixed assets = invested capital = capital employed), liquidity
               and operating-cycle ratios, and FCF built from the MBS.
  reformulated Operating vs financial split: NOA, NNO, CSE; NOPAT and net
               financial expense with tax allocated; RNOA, ROCE, FLEV, NBC,
               spread, OLLEV, ROOA, OLSPREAD, each on average and on beginning
               balances.
  traditional  Profit margin, asset turnover, ROA, leverage, ROE.
  risk         Altman Z (public and private), credit metrics.
  signals      Year-over-year fundamental signals and quality diagnostics.

Inputs are a period's `values` (concept id -> number) from periods.py and,
where a ratio needs it, the prior period's values. Every function returns
None for a figure whose inputs are missing; nothing is filled with zero.

Balance-sheet splits work from totals: operating assets = total assets -
financial assets, operating liabilities = total liabilities - financial
obligations. Detail lines are often untagged in companyfacts, so summing
them would undercount; the financial items (cash, investments, debt) are the
well-tagged ones.

Ratios are computed for 12-month periods only (annual and TTM views), so
flow-to-stock ratios need no annualizing.
"""
from __future__ import annotations

import json
from pathlib import Path

CLASSIFICATION_PATH = Path(__file__).with_name("classification.json")


def load_classification(overrides: dict | None = None) -> dict:
    cfg = json.loads(CLASSIFICATION_PATH.read_text())
    cfg.update(overrides or {})
    return cfg


# ---------------------------------------------------------------- helpers

def _div(a, b):
    if a is None or b is None or b == 0:
        return None
    return a / b


def _sub(a, b):
    return None if a is None or b is None else a - b


def _add(*xs):
    return None if any(x is None for x in xs) else sum(xs)


def _mul(a, b):
    return None if a is None or b is None else a * b


def _avg(a, b):
    return None if a is None or b is None else (a + b) / 2


def _sum_present(v: dict, ids) -> float:
    return sum(v[i] for i in ids if v.get(i) is not None)


def _one_year_apart(earlier: str, later: str) -> bool:
    from datetime import date
    gap = (date.fromisoformat(later) - date.fromisoformat(earlier)).days
    return 350 <= gap <= 380


def _pct_change(cur, prev):
    if cur is None or prev is None or prev == 0:
        return None
    return (cur - prev) / abs(prev)


# ------------------------------------------------------- line-item helpers

def total_liabilities(v: dict) -> tuple[float | None, str]:
    """Reported total, or liabilities & equity less equity and mezzanine."""
    if v.get("liabilities") is not None:
        return v["liabilities"], "reported"
    le, eq = v.get("liabilities_and_equity"), v.get("all_equity_balance_including_minority_interest")
    if eq is None and v.get("all_equity_balance") is not None:
        eq = v["all_equity_balance"] + (v.get("minority_interest_balance") or 0)
    if le is None or eq is None:
        return None, "missing"
    return le - eq - (v.get("temporary_and_mezzanine_financing") or 0), "from_equity"


def depreciation(v: dict) -> float | None:
    if v.get("depreciation_amortization_cf") is not None:
        return v["depreciation_amortization_cf"]
    d, a = v.get("depreciation_expense"), v.get("amortization_of_intangibles")
    if d is None and a is None:
        return None
    return (d or 0) + (a or 0)


def net_interest_expense(v: dict) -> float | None:
    ie, ii = v.get("interest_expense"), v.get("interest_income")
    if ie is None and ii is None:
        return None
    return (ie or 0) - (ii or 0)


def total_net_income(v: dict) -> float | None:
    """Net income including the noncontrolling interest's share."""
    if v.get("profit_loss") is not None:
        return v["profit_loss"]
    if v.get("net_income") is None:
        return None
    return v["net_income"] + (v.get("minority_interest_income_expense") or 0)


# ------------------------------------------------------ managerial (MBS)

def managerial_balance_sheet(v: dict) -> dict:
    """Cash + WCR + fixed assets = invested capital = STD + LT financing + equity."""
    ta, ca, cl = v.get("assets"), v.get("current_assets_total"), v.get("current_liabilities_total")
    cash, std = v.get("cash_and_marketable_securities"), v.get("short_term_debt") or 0
    tl, _ = total_liabilities(v)
    equity = _sub(ta, tl)
    wcr = _sub(_sub(ca, cash), _sub(cl, std))
    fixed = _sub(ta, ca)
    lt_fin = _sub(tl, cl)
    out = {
        "cash": cash,
        "wcr": wcr,
        "wcr_detail": {
            "receivables": v.get("trade_receivables"),
            "inventories": v.get("inventories"),
            "payables": v.get("trade_payables"),
        },
        "fixed_assets": fixed,
        "invested_capital": _add(cash, wcr, fixed),
        "short_term_debt": std if cl is not None else None,
        "long_term_financing": lt_fin,
        "long_term_debt": v.get("long_term_debt"),
        "equity": equity,
        "capital_employed": _add(std if cl is not None else None, lt_fin, equity),
    }
    return out


def managerial_ratios(v: dict, prev: dict | None, cfg: dict) -> dict:
    days = cfg["days_in_year"]
    mbs = managerial_balance_sheet(v)
    sales, cogs = v.get("revenue"), v.get("cost_of_goods_and_services_sold")
    inv, ar, ap = v.get("inventories"), v.get("trade_receivables"), v.get("trade_payables")
    prev_inv = (prev or {}).get("inventories")
    purchases = _add(cogs, _sub(inv, prev_inv)) if prev_inv is not None else None
    nlf = _sub(_add(mbs["equity"], mbs["long_term_financing"]), mbs["fixed_assets"])
    nsf = _sub(mbs["short_term_debt"], mbs["cash"])
    ca, cl = v.get("current_assets_total"), v.get("current_liabilities_total")
    return {
        "nlf": nlf,
        "nsf": nsf,
        "liquidity_ratio": _div(nlf, mbs["wcr"]),
        "wcr_to_sales": _div(mbs["wcr"], sales),
        "collection_period_days": _div(ar, _div(sales, days)),
        "days_inventory": _div(inv, _div(cogs, days)),
        "inventory_turnover": _div(cogs, inv),
        "payment_period_days": _div(ap, _div(purchases, days)),
        "current_ratio": _div(ca, cl),
        "acid_test": _div(_sub(ca, inv), cl),
    }


def mbs_free_cash_flow(v: dict, prev: dict | None, cfg: dict) -> dict:
    """FCF = EBIT(1-t) + depreciation - change in WCR - capex,
    with capex = change in fixed assets + depreciation (balance-sheet capex)."""
    if prev is None:
        return {}
    t = cfg["marginal_tax_rate"]
    cur_m, prev_m = managerial_balance_sheet(v), managerial_balance_sheet(prev)
    dep = depreciation(v)
    noplat = _mul(v.get("operating_income_loss"), 1 - t)
    d_wcr = _sub(cur_m["wcr"], prev_m["wcr"])
    capex_bs = _add(_sub(cur_m["fixed_assets"], prev_m["fixed_assets"]), dep)
    return {
        "noplat": noplat,
        "depreciation": dep,
        "change_in_wcr": d_wcr,
        "capex_from_balance_sheet": capex_bs,
        "capex_reported": v.get("capital_expenses"),
        "fcf": _sub(_sub(_add(noplat, dep), d_wcr), capex_bs),
    }


# ---------------------------------------------------------- reformulated

def reformulated_balance_sheet(v: dict, cfg: dict) -> dict:
    ta = v.get("assets")
    tl, tl_method = total_liabilities(v)
    fa = _sum_present(v, cfg["financial_assets"])
    fo_ids = list(cfg["financial_obligations"])
    if cfg.get("leases_are_financial"):
        fo_ids += cfg["lease_liabilities"]
    fo_liab = _sum_present(v, fo_ids)
    preferred = _sum_present(v, cfg["preferred_claims"])
    nci = v.get("minority_interest_balance") or 0
    oa = _sub(ta, fa)
    ol = _sub(tl, fo_liab)
    noa = _sub(oa, ol)
    nno = fo_liab + preferred - fa
    cse_incl_nci = _sub(noa, nno)
    return {
        "operating_assets": oa,
        "operating_liabilities": ol,
        "noa": noa,
        "financial_assets": fa,
        "financial_obligations": fo_liab + preferred,
        "nno": nno,
        "cse_incl_nci": cse_incl_nci,
        "nci": nci,
        "cse": _sub(cse_incl_nci, nci),
        "total_liabilities_method": tl_method,
    }


def reformulated_income_statement(v: dict, cfg: dict) -> dict:
    t = cfg["marginal_tax_rate"]
    nie = net_interest_expense(v)
    nfe = _mul(nie, 1 - t) if nie is not None else 0.0
    ni = total_net_income(v)
    nopat = _add(ni, nfe)
    taxes = v.get("income_taxes")
    transitory = sum(v.get(k) or 0 for k in ("restructuring_expense_benefit", "goodwill_writeoffs"))
    return {
        "operating_income_before_tax": v.get("operating_income_loss"),
        "tax_on_operating_income": _add(taxes, _mul(nie or 0, t)) if taxes is not None else None,
        "nopat": nopat,
        "core_nopat": _add(nopat, transitory * (1 - t)) if nopat is not None else None,
        "net_interest_expense_pretax": nie,
        "nfe_after_tax": nfe,
        "net_income_incl_nci": ni,
        "interest_missing": nie is None,
    }


def reformulated_ratios(v: dict, prev: dict | None, cfg: dict) -> dict:
    """RNOA = ROOA + OLLEV x OLSPREAD; ROCE = RNOA + FLEV x (RNOA - NBC)."""
    bs, is_ = reformulated_balance_sheet(v, cfg), reformulated_income_statement(v, cfg)
    sales = v.get("revenue")
    out = {"nopm": _div(is_["nopat"], sales), "core_nopm": _div(is_["core_nopat"], sales)}
    if prev is None:
        return out
    pbs = reformulated_balance_sheet(prev, cfg)
    r = cfg["implicit_borrowing_rate_after_tax"]
    for basis, pick in (("avg", _avg), ("beg", lambda cur, beg: beg)):
        noa = pick(bs["noa"], pbs["noa"])
        nno = pick(bs["nno"], pbs["nno"])
        ce = pick(bs["cse_incl_nci"], pbs["cse_incl_nci"])
        oa = pick(bs["operating_assets"], pbs["operating_assets"])
        ol = pick(bs["operating_liabilities"], pbs["operating_liabilities"])
        rnoa = _div(is_["nopat"], noa)
        nbc = _div(is_["nfe_after_tax"], nno)
        implicit_cost = _mul(ol, r)
        rooa = _div(_add(is_["nopat"], implicit_cost), oa)
        out[basis] = {
            "noat": _div(sales, noa),
            "rnoa": rnoa,
            "roce": _div(is_["net_income_incl_nci"], ce),
            "flev": _div(nno, ce),
            "nbc": nbc,
            "spread": _sub(rnoa, nbc),
            "ollev": _div(ol, noa),
            "rooa": rooa,
            "olspread": _sub(rooa, r),
        }
    out["fcf"] = _sub(is_["nopat"], _sub(bs["noa"], pbs["noa"]))
    return out


# ------------------------------------------------------------ traditional

def traditional_ratios(v: dict, prev: dict | None, cfg: dict) -> dict:
    if prev is None:
        return {}
    t = cfg["marginal_tax_rate"]
    ni = total_net_income(v)
    tl, _ = total_liabilities(v)
    ptl, _ = total_liabilities(prev)
    eq, peq = _sub(v.get("assets"), tl), _sub(prev.get("assets"), ptl)
    avg_ta, avg_eq = _avg(v.get("assets"), prev.get("assets")), _avg(eq, peq)
    sales = v.get("revenue")
    pm = _div(_add(ni, _mul(v.get("interest_expense") or 0, 1 - t)), sales)
    ato = _div(sales, avg_ta)
    return {
        "profit_margin": pm,
        "asset_turnover": ato,
        "roa": _mul(pm, ato),
        "leverage": _div(avg_ta, avg_eq),
        "roe": _div(ni, avg_eq),
    }


# ------------------------------------------------------------------- risk

def altman_z(v: dict, market_cap: float | None = None) -> dict:
    ta, ca, cl = v.get("assets"), v.get("current_assets_total"), v.get("current_liabilities_total")
    tl, _ = total_liabilities(v)
    re, ebit, sales = v.get("retained_earnings"), v.get("operating_income_loss"), v.get("revenue")
    wc = _sub(ca, cl)
    parts = [_div(wc, ta), _div(re, ta), _div(ebit, ta), _div(sales, ta)]
    out = {"public": None, "public_zone": None, "private": None, "private_zone": None}
    if all(p is not None for p in parts):
        x1, x2, x3, x5 = parts
        if market_cap is not None and tl:
            z = 1.2 * x1 + 1.4 * x2 + 3.3 * x3 + 0.6 * market_cap / tl + 1.0 * x5
            out["public"] = z
            out["public_zone"] = "distress" if z < 1.8 else "grey" if z < 2.99 else "safe"
        book_eq = _sub(ta, tl)
        if book_eq is not None and tl:
            z = 0.717 * x1 + 0.847 * x2 + 3.107 * x3 + 0.420 * book_eq / tl + 0.998 * x5
            out["private"] = z
            out["private_zone"] = "distress" if z < 1.2 else "grey" if z < 2.9 else "safe"
    return out


def credit_metrics(v: dict) -> dict:
    debt = _add(v.get("short_term_debt") or 0, v.get("long_term_debt")) if v.get("long_term_debt") is not None else None
    ebitda, ebit, dep = v.get("ebitda"), v.get("operating_income_loss"), depreciation(v)
    tl, _ = total_liabilities(v)
    equity = _sub(v.get("assets"), tl)
    dtl = v.get("deferred_tax_non_current_liabilities") or 0
    ni = total_net_income(v)
    return {
        "ebit_to_interest": _div(ebit, v.get("interest_expense")),
        "debt_to_ebitda": _div(debt, ebitda),
        "ffo_to_debt": _div(_add(ni, dep), debt),
        "return_on_capital": _div(ebit, _add(debt, equity)),
        "ebit_margin": _div(ebit, v.get("revenue")),
        "debt_to_book_capital": _div(debt, _add(debt, equity, dtl)),
        "capex_to_depreciation": _div(v.get("capital_expenses"), dep),
    }


# ---------------------------------------------------------------- signals

def signals(v: dict, prev: dict | None, cfg: dict) -> dict:
    out = {
        "cfo_to_operating_income": _div(v.get("operating_cash_flow"), v.get("operating_income_loss")),
        "sales_to_receivables": _div(v.get("revenue"), v.get("trade_receivables")),
        "depreciation_to_capex": _div(depreciation(v), v.get("capital_expenses")),
        "sales_to_deferred_revenue": _div(v.get("revenue"), v.get("deferred_revenue_current")),
        "allowance_to_receivables": _div(v.get("allowance_for_doubtful_accounts"),
                                         _add(v.get("trade_receivables"), v.get("allowance_for_doubtful_accounts"))),
    }
    if prev is None:
        return out
    ds = _pct_change(v.get("revenue"), prev.get("revenue"))
    out.update({
        "gross_margin_signal": _sub(_pct_change(v.get("gross_profit"), prev.get("gross_profit")), ds),
        "sga_signal": _sub(ds, _pct_change(v.get("selling_general_and_admin_expenses"),
                                           prev.get("selling_general_and_admin_expenses"))),
        "rnd_signal": _sub(_pct_change(v.get("research_and_development_expenses"),
                                       prev.get("research_and_development_expenses")), ds),
        "receivables_signal": _sub(ds, _pct_change(v.get("trade_receivables"), prev.get("trade_receivables"))),
        "inventory_signal": _sub(ds, _pct_change(v.get("inventories"), prev.get("inventories"))),
        "accruals_to_sales_change": _div(_sub(total_net_income(v), v.get("operating_cash_flow")),
                                         _sub(v.get("revenue"), prev.get("revenue"))),
    })
    noa, pnoa = reformulated_balance_sheet(v, cfg)["noa"], reformulated_balance_sheet(prev, cfg)["noa"]
    out["cfo_to_avg_noa"] = _div(v.get("operating_cash_flow"), _avg(noa, pnoa))
    return out


# ------------------------------------------------------------ assemble

def analyze_period(v: dict, prev: dict | None, cfg: dict, market_cap: float | None = None) -> dict:
    return {
        "managerial_balance_sheet": managerial_balance_sheet(v),
        "reformulated_balance_sheet": reformulated_balance_sheet(v, cfg),
        "reformulated_income_statement": reformulated_income_statement(v, cfg),
        "ratios": {
            "managerial": managerial_ratios(v, prev, cfg),
            "reformulated": reformulated_ratios(v, prev, cfg),
            "traditional": traditional_ratios(v, prev, cfg),
            "risk": {"altman_z": altman_z(v, market_cap), "credit": credit_metrics(v)},
            "signals": signals(v, prev, cfg),
        },
        "fcf_managerial": mbs_free_cash_flow(v, prev, cfg),
    }


def analyze_view(periods: list[dict], cfg: dict, market_cap_at: dict | None = None,
                 prior_lookup: dict | None = None) -> list[dict]:
    """Analyze each 12-month period. `prior_lookup` maps a period's end date to
    the values of the period one year earlier (for TTM views); otherwise the
    previous element of `periods` is used."""
    out = []
    for i, p in enumerate(periods):
        if prior_lookup is not None:
            prev = prior_lookup.get(p["end"])
        else:
            prev = periods[i - 1]["values"] if i > 0 and _one_year_apart(periods[i - 1]["end"], p["end"]) else None
        mc = (market_cap_at or {}).get(p["end"])
        out.append({"label": p["label"], "end": p["end"], **analyze_period(p["values"], prev, cfg, mc)})
    return out
