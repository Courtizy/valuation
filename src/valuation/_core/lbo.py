"""Leveraged buyout math (MBA 789 Week 7 LBO model and the Week 9 LBO review).

A financial sponsor replaces WACC with its target return r (15-25%, 20% default) and
values the equity it puts in from levered cash flows and an exit at an EBITDA multiple:

    PEMV(r) = sum_t (FCF_t - interest_t (1 - tax) - debt repaid_t) / (1 + r)^t
              + (EBITDA_H x exit multiple - remaining debt) / (1 + r)^H

  max price at the target IRR   PEMV(r_target) = what the sponsor can put in, so
                                max price = (PEMV + LBO debt - net debt - fees) / shares
  IRR at an offer price         the r where PEMV(r) = sponsor equity at that price
                                = offer x shares + net debt + fees - LBO debt

The offer premium changes neither the debt (set by coverage and collateral) nor the exit
multiple (today's multiple plus a change), so the max price doesn't depend on the premium,
and the IRR doesn't depend on the target IRR.

Debt (sized at close on base-year EBIT)
---------------------------------------
    senior        up to the securable assets x % secured (collateral caps it)
    subordinated  a share of senior (60% default)
    mezzanine     the rest, until EBIT / total interest = the target coverage (2.0x)
Rates step up by tranche: senior, + step for subordinated, + 2 steps for mezzanine.
If senior and subordinated alone would push coverage below the target, both shrink
together and there is no mezzanine.

Each year (cash interest on the average balance, solved by iteration: the model's circularity)
    EBITDA, D&A, EBIT from the operating plan (the DCF's projection plus the sponsor's steps)
    cash taxes = tax x max(EBIT - interest, 0)
    cash for debt repayment = EBITDA - capex - change in NWC - interest - cash taxes
    the sweep pays senior, then subordinated, then mezzanine; what's left after all debt is
    repaid goes to the sponsor that year
"""
from __future__ import annotations

TRANCHES = ("senior", "subordinated", "mezzanine")


def size_debt(*, ebit: float, securable_assets: float, pct_secured: float, sub_to_senior: float, coverage: float,
              senior_rate: float, rate_step: float) -> dict:
    rates = {"senior": senior_rate, "subordinated": senior_rate + rate_step, "mezzanine": senior_rate + 2 * rate_step}
    budget = max(ebit, 0.0) / coverage                       # the most interest the coverage target allows
    senior = max(securable_assets * pct_secured, 0.0)
    sub = senior * sub_to_senior
    base_interest = senior * rates["senior"] + sub * rates["subordinated"]
    if base_interest > budget:
        k = budget / base_interest if base_interest else 0.0
        senior, sub, mezz = senior * k, sub * k, 0.0
    else:
        mezz = (budget - base_interest) / rates["mezzanine"]
    amounts = {"senior": senior, "subordinated": sub, "mezzanine": mezz}
    interest = sum(amounts[t] * rates[t] for t in TRANCHES)
    return {"amounts": amounts, "rates": rates, "total": sum(amounts.values()),
            "coverage": ebit / interest if interest else None, "interest": interest}


def debt_schedule(plan: list[dict], debt: dict, tax_rate: float, iterations: int = 50) -> list[dict]:
    """plan: [{year, ebitda, ebit, capex, change_in_nwc}], years 1..H. Returns per-year rows."""
    bal = dict(debt["amounts"])
    rows = []
    for y in plan:
        begin = dict(bal)
        pay = {t: 0.0 for t in TRANCHES}
        for _ in range(iterations):                  # interest on the average balance: iterate to a fixed point
            interest = {t: debt["rates"][t] * (begin[t] + (begin[t] - pay[t])) / 2 for t in TRANCHES}
            total_int = sum(interest.values())
            taxes = tax_rate * max(y["ebit"] - total_int, 0.0)
            cash = y["ebitda"] - y["capex"] - y["change_in_nwc"] - total_int - taxes
            left, new = cash, {}
            for t in TRANCHES:
                new[t] = min(max(left, 0.0), begin[t])
                left -= new[t]
            if all(abs(new[t] - pay[t]) < 1e-9 for t in TRANCHES):
                break
            pay = new
        pay = new
        end = {t: begin[t] - pay[t] for t in TRANCHES}
        rows.append({**y, "interest": interest, "total_interest": total_int, "cash_taxes": taxes,
                     "cash_for_debt": cash, "repaid": pay, "begin": begin, "end": end,
                     "to_sponsor": max(left, 0.0), "shortfall": min(cash, 0.0),
                     "coverage": y["ebit"] / total_int if total_int else None,
                     "debt_end": sum(end.values())})
        bal = end
    return rows


def pemv(rows: list[dict], exit_ebitda: float, exit_multiple: float, r: float) -> float:
    h = len(rows)
    flows = sum(row["to_sponsor"] / (1 + r) ** (i + 1) for i, row in enumerate(rows))
    return flows + (exit_ebitda * exit_multiple - rows[-1]["debt_end"]) / (1 + r) ** h


def irr(rows: list[dict], exit_ebitda: float, exit_multiple: float, equity_in: float) -> float | None:
    """r with PEMV(r) = equity_in, by bisection; None when no rate in -99%..1000% fits."""
    if equity_in <= 0:
        return None
    f = lambda r: pemv(rows, exit_ebitda, exit_multiple, r) - equity_in  # noqa: E731
    lo, hi = -0.99, 10.0
    if f(lo) * f(hi) > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        if f(lo) * f(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def buyout(*, plan: list[dict], ebit0: float, ebitda0: float, price: float, shares: float, net_debt: float,
           tax_rate: float, sponsor_irr: float, offer_premium: float, exit_multiple_change: float,
           securable_assets: float, pct_secured: float = 1.0, sub_to_senior: float = 0.6, coverage: float = 2.0,
           senior_rate: float, rate_step: float = 0.03, fee_pct: float = 0.02) -> dict:
    debt = size_debt(ebit=ebit0, securable_assets=securable_assets, pct_secured=pct_secured,
                     sub_to_senior=sub_to_senior, coverage=coverage, senior_rate=senior_rate, rate_step=rate_step)
    fees = fee_pct * debt["total"]
    current_multiple = (price * shares + net_debt) / ebitda0 if ebitda0 > 0 else None
    offer = price * (1 + offer_premium)
    offer_multiple = (offer * shares + net_debt) / ebitda0 if ebitda0 > 0 else None
    exit_multiple = current_multiple + exit_multiple_change if current_multiple is not None else None
    rows = debt_schedule(plan, debt, tax_rate)
    exit_ebitda = plan[-1]["ebitda"]
    equity_offer = offer * shares
    sponsor_equity = equity_offer + net_debt + fees - debt["total"]
    pv = pemv(rows, exit_ebitda, exit_multiple, sponsor_irr)
    max_price = (pv + debt["total"] - net_debt - fees) / shares
    exit_ev = exit_ebitda * exit_multiple
    exit_equity = exit_ev - rows[-1]["debt_end"]
    return {
        "debt": {**debt, "fees": fees, "post_lbo_debt_to_pre_ev": debt["total"] / (price * shares + net_debt)
                 if price * shares + net_debt else None,
                 "leverage": {t: debt["amounts"][t] / ebitda0 for t in TRANCHES} if ebitda0 > 0 else None,
                 "total_leverage": debt["total"] / ebitda0 if ebitda0 > 0 else None},
        "purchase": {"price": price, "offer_premium": offer_premium, "offer_price": offer, "shares": shares,
                     "equity_offer": equity_offer, "multiple_at_offer": offer_multiple,
                     "multiple_at_current": current_multiple},
        "sources_uses": {"sources": {**debt["amounts"], "sponsor_equity": sponsor_equity},
                         "uses": {"purchase_equity": equity_offer, "refinance_net_debt": net_debt, "fees": fees},
                         "total": equity_offer + net_debt + fees},
        "schedule": rows,
        "exit": {"ebitda": exit_ebitda, "multiple": exit_multiple, "multiple_change": exit_multiple_change,
                 "enterprise_value": exit_ev, "debt": rows[-1]["debt_end"], "equity": exit_equity},
        "sponsor_irr": sponsor_irr,
        "pemv_at_target": pv,
        "max_price": max_price,
        "max_premium": max_price / price - 1 if price else None,
        "irr_at_offer": irr(rows, exit_ebitda, exit_multiple, sponsor_equity),
        "sponsor_equity": sponsor_equity,
        "money_multiple": (exit_equity + sum(r["to_sponsor"] for r in rows)) / sponsor_equity if sponsor_equity > 0 else None,
    }
