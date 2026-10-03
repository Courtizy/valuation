"""Discounted cash flow valuation on top of core.projection.

Timeline (course convention, "closing_year_zero")
--------------------------------------------------
Projection year 1 is the closing year. It is discounted with exponent 0, so
year t uses (1 + WACC)^(t-1). The terminal value sits in the last projected
year and is discounted with that year's exponent at the pre-terminal WACC.
Other conventions: "end_of_year" (exponent t) and "mid_year" (t - 0.5 for
cash flows, t for the terminal value).

Terminal value (steady state, Gordon growth)
--------------------------------------------
    FCF_T = EBITDA_N (1 - t) - Sales_N * (capex/sales) * (1 - t) - Sales_N * g * (dNWC/dSales)
    TV    = FCF_T * (1 + g) / (WACC_T - g) * tv_weight

Capex is taken net of its tax shield because in steady state it replaces
depreciation; NWC grows with sales at rate g. WACC_T is the terminal-year
rate from core.cost_of_capital.

Bridge
------
    equity = EV - net debt,  net debt = debt - excess cash
    price  = equity / diluted shares

Scenarios
---------
`scenario_range` gives conservative / expected / aggressive values the way the
course reads its two sensitivity tables: one moves near-term growth and the
pre-terminal WACC together, the other moves terminal growth and terminal
WACC together; the two are blended by the terminal value's share of EV.
"""
from __future__ import annotations

from typing import Callable

CONVENTIONS = ("closing_year_zero", "end_of_year", "mid_year")


def _exponents(t: int, convention: str) -> tuple[float, float]:
    """(cash-flow exponent, terminal-value exponent) for projection year t (1-based)."""
    if convention == "closing_year_zero":
        return t - 1, t - 1
    if convention == "end_of_year":
        return t, t
    if convention == "mid_year":
        return t - 0.5, t
    raise ValueError(f"convention must be one of {CONVENTIONS}")


def terminal_value(last: dict, *, terminal_growth: float, wacc_terminal: float, tax_rate: float,
                   capex_to_sales: float, nwc_to_sales_change: float, tv_weight: float = 1.0) -> dict:
    if wacc_terminal <= terminal_growth:
        raise ValueError(f"terminal WACC {wacc_terminal:.4f} must exceed terminal growth {terminal_growth:.4f}")
    s = last["revenue"]
    fcf_t = (last["ebitda"] * (1 - tax_rate) - s * capex_to_sales * (1 - tax_rate)
             - s * terminal_growth * nwc_to_sales_change)
    tv = fcf_t * (1 + terminal_growth) / (wacc_terminal - terminal_growth) * tv_weight
    return {"fcf_for_terminal": fcf_t, "terminal_value": tv}


def value_firm(projection: dict, *, wacc: float, wacc_terminal: float, terminal_growth: float, tax_rate: float,
               capex_to_sales_terminal: float, nwc_to_sales_change: float, net_debt: float, shares: float,
               tv_weight: float = 1.0, convention: str = "closing_year_zero",
               invested_capital_to_sales: float | None = None) -> dict:
    years = projection["years"]
    if not years:
        raise ValueError("projection has no years")
    last = years[-1]
    tv = terminal_value(last, terminal_growth=terminal_growth, wacc_terminal=wacc_terminal, tax_rate=tax_rate,
                        capex_to_sales=capex_to_sales_terminal, nwc_to_sales_change=nwc_to_sales_change,
                        tv_weight=tv_weight)
    rows, pv_fcf = [], 0.0
    for y in years:
        e_cf, e_tv = _exponents(y["year"], convention)
        fcf = y["free_cash_flow"]["fcf"]
        df = 1 / (1 + wacc) ** e_cf
        pv = fcf * df
        pv_fcf += pv
        rows.append({"year": y["year"], "fcf": fcf, "discount_factor": df, "pv": pv})
    _, e_tv = _exponents(last["year"], convention)
    pv_tv = tv["terminal_value"] / (1 + wacc) ** e_tv
    ev = pv_fcf + pv_tv
    equity = ev - net_debt
    out = {
        "enterprise_value": ev,
        "pv_fcf": pv_fcf,
        "pv_terminal_value": pv_tv,
        "terminal_value_share": pv_tv / ev if ev else None,
        "net_debt": net_debt,
        "equity_value": equity,
        "shares": shares,
        "value_per_share": equity / shares if shares else None,
        "terminal": {
            **tv,
            "growth": terminal_growth,
            "wacc": wacc_terminal,
            "ebitda_margin": last["ebitda"] / last["revenue"] if last["revenue"] else None,
            "ev_to_ebitda": tv["terminal_value"] / last["ebitda"] if last["ebitda"] else None,
            "roic": (last["ebit"] * (1 - tax_rate) / (invested_capital_to_sales * last["revenue"])
                     if invested_capital_to_sales else None),
        },
        "wacc": wacc,
        "convention": convention,
        "cash_flows": rows,
    }
    return out


def scenario_range(price_at: Callable[..., float], *, g0: float, g_terminal: float, wacc: float,
                   wacc_terminal: float, tv_share: float, growth_step: float = 0.01, wacc_step: float = 0.01,
                   terminal_growth_step: float = 0.005, terminal_wacc_step: float = 0.005) -> dict:
    """Conservative / expected / aggressive per share.

    price_at(g0=, g_terminal=, wacc=, wacc_terminal=) must return the value per
    share for those four inputs with everything else held fixed.
    """
    base = price_at(g0=g0, g_terminal=g_terminal, wacc=wacc, wacc_terminal=wacc_terminal)
    near_low = price_at(g0=g0 - growth_step, g_terminal=g_terminal, wacc=wacc + wacc_step, wacc_terminal=wacc_terminal)
    near_high = price_at(g0=g0 + growth_step, g_terminal=g_terminal, wacc=wacc - wacc_step, wacc_terminal=wacc_terminal)
    term_low = price_at(g0=g0, g_terminal=g_terminal - terminal_growth_step, wacc=wacc,
                        wacc_terminal=wacc_terminal + terminal_wacc_step)
    term_high = price_at(g0=g0, g_terminal=g_terminal + terminal_growth_step, wacc=wacc,
                         wacc_terminal=wacc_terminal - terminal_wacc_step)
    w = tv_share
    return {
        "conservative": near_low * (1 - w) + term_low * w,
        "expected": base,
        "aggressive": near_high * (1 - w) + term_high * w,
        "components": {"near_term_low": near_low, "near_term_high": near_high,
                       "terminal_low": term_low, "terminal_high": term_high, "tv_share": w},
        "steps": {"growth": growth_step, "wacc": wacc_step, "terminal_growth": terminal_growth_step,
                  "terminal_wacc": terminal_wacc_step},
    }


def sensitivity_grid(price_at: Callable[..., float], *, wacc: float, wacc_terminal: float, g_terminal: float,
                     wacc_shifts=(-0.01, -0.005, 0.0, 0.005, 0.01),
                     growth_shifts=(-0.01, -0.005, 0.0, 0.005, 0.01)) -> dict:
    """Value per share across WACC (rows) and terminal growth (columns).

    A WACC shift moves the pre-terminal and terminal WACC together; the centre
    cell is the base case. A cell whose terminal WACC would not exceed terminal
    growth (no finite Gordon value) is None.
    """
    rows = []
    for dw in wacc_shifts:
        row = []
        for dg in growth_shifts:
            if wacc_terminal + dw <= g_terminal + dg:
                row.append(None)
            else:
                row.append(price_at(wacc=wacc + dw, wacc_terminal=wacc_terminal + dw, g_terminal=g_terminal + dg))
        rows.append(row)
    return {"wacc": [wacc + d for d in wacc_shifts], "wacc_terminal": [wacc_terminal + d for d in wacc_shifts],
            "terminal_growth": [g_terminal + d for d in growth_shifts], "values": rows}


def solve(f: Callable[[float], float], target: float, lo: float, hi: float, tol: float = 1e-10,
          max_iter: int = 200) -> float:
    """Bisection: x in [lo, hi] with f(x) = target. Requires a sign change."""
    flo, fhi = f(lo) - target, f(hi) - target
    if flo == 0:
        return lo
    if fhi == 0:
        return hi
    if flo * fhi > 0:
        raise ValueError(f"no solution in [{lo}, {hi}]: values {flo + target:.4g} and {fhi + target:.4g} vs {target:.4g}")
    for _ in range(max_iter):
        mid = (lo + hi) / 2
        fm = f(mid) - target
        if abs(fm) <= tol * max(1.0, abs(target)) or (hi - lo) / 2 < 1e-12:
            return mid
        if fm * flo < 0:
            hi = mid
        else:
            lo, flo = mid, fm
    return (lo + hi) / 2
