"""Synergy valuation: the two course methods.

Just synergies
--------------
Values only the synergies, then adds them to the pre-announcement price.
Year 0 is the closing year (undiscounted); year t is discounted at (1 + WACC)^t.

    cost synergy_t     = 0 in year 0; S * t / N while phasing in (t < N);
                         S * (1 + g)^(t - N) once fully realized; 0 after the terminal year T
    revenue synergy_t  = the same path times r (revenue synergies as a share of cost synergies)
    one-time cost_t    = C / N in each of the first N years (t = 0 .. N-1)
    after tax_t        = (cost_t + revenue_t - one-time_t) * (1 - tax)
    terminal (year T)  = (cost_T * f + revenue_T) * (1 - tax) * (1 + g_T) / (WACC_T - g_T)

f is the share of cost synergies that lasts forever (competitors catch up on
the rest); revenue synergies last. Value per share = sum of PVs / shares, and
the most a buyer could pay = pre-announcement price + that.

Whole firm with synergies
-------------------------
The standalone projection with synergies built into its drivers:
  - revenue grows faster by `revenue_growth_add` from year 1 on (not the closing year)
  - cost lines (COGS and SG&A) are cut by s = cost_pct * realized:
        year 0       +s     (integration costs: costs rise for a year)
        years 1..N-1 -s * t / N
        years N..T-1 -s
        year T       -s * f (only the lasting share feeds the terminal value)
The firm is then valued exactly like the standalone DCF.
"""
from __future__ import annotations

from copy import deepcopy

from valuation._core.projection import _per_year, revenue_path

COST_LINES = ("cogs", "sga")
ALL_COST_LINES = ("cogs", "sga", "rnd", "other_opex")


def just_synergies(*, annual_cost: float, revenue_pct_of_cost: float, one_time_cost: float, tax_rate: float,
                   terminal_growth: float, wacc: float, wacc_terminal: float, growth: float, years_to_full: int,
                   terminal_year: int, cost_forever: float, shares: float, pre_price: float,
                   exchange_rate: float = 1.0) -> dict:
    if wacc_terminal <= terminal_growth:
        raise ValueError(f"terminal WACC {wacc_terminal:.4f} must exceed terminal growth {terminal_growth:.4f}")
    S, r, N, T = annual_cost, revenue_pct_of_cost, years_to_full, terminal_year
    rows, total = [], 0.0
    for t in range(T + 1):
        if t == 0:
            cost = 0.0
        elif t > N - 1:
            cost = S * (1 + growth) ** (t - N)
        else:
            cost = S * t / N
        rev = cost * r
        once = one_time_cost / N if N and t + 1 <= N else 0.0
        after_tax = (cost + rev - once) * (1 - tax_rate)
        tv = ((cost * cost_forever + rev) * (1 - tax_rate) * (1 + terminal_growth) / (wacc_terminal - terminal_growth)
              if t == T else 0.0)
        pv = after_tax if t == 0 else (after_tax + tv) / (1 + wacc) ** t
        total += pv
        rows.append({"year": t, "cost": cost, "revenue": rev, "one_time": once, "after_tax": after_tax,
                     "terminal_value": tv, "pv": pv})
    per_share = total / exchange_rate / shares
    return {"years": rows, "total_value": total, "per_share": per_share, "value_per_share": pre_price + per_share,
            "max_premium": per_share / pre_price if pre_price else None,
            "terminal_value_share": rows[-1]["terminal_value"] / (1 + wacc) ** T / total if total else None}


def growth_rates(driver: dict, base_revenue: float, years: int) -> list[float]:
    """Year-by-year revenue growth implied by a revenue driver (any method)."""
    path = revenue_path(driver, base_revenue, years)
    prev = [base_revenue] + path[:-1]
    return [s / p - 1 for s, p in zip(path, prev)]


def cost_adjustments(cost_pct: float, realized: float, cost_forever: float, years_to_full: int, years: int) -> list[float]:
    """Per projection year (0 = closing year): the multiplier added to each cost line's ratio."""
    s, N, T = cost_pct * realized, years_to_full, years - 1
    out = []
    for t in range(years):
        if t == 0:
            out.append(s)
        elif t < N:
            out.append(-s * t / N)
        elif t < T:
            out.append(-s)
        else:
            out.append(-s * cost_forever)
    return out


def cost_lines(base: dict) -> tuple[str, ...]:
    """COGS and SG&A, as in the course; every cost line when neither is reported."""
    return COST_LINES if any(base.get(k) for k in COST_LINES) else ALL_COST_LINES


def synergy_drivers(drivers: dict, base: dict, years: int, *, revenue_growth_add: float, cost_pct: float,
                    realized: float, cost_forever: float, years_to_full: int) -> dict:
    d = deepcopy(drivers)
    rates = growth_rates(drivers["revenue"], base["revenue"], years)
    d["revenue"] = {"method": "growth", "rates": [g + (revenue_growth_add if t else 0.0) for t, g in enumerate(rates)]}
    adj = cost_adjustments(cost_pct, realized, cost_forever, years_to_full, years)
    for k in cost_lines(base):
        dr = d.get(k)
        if not dr or dr.get("method") != "pct_of_sales":
            continue
        dr["adjust"] = [a + _per_year(dr.get("adjust"), t) for t, a in enumerate(adj)]
    return d
