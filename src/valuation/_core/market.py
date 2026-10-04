"""Market math: beta from monthly returns and a market-based WACC estimate.

Beta (the common 5-year monthly convention):
    r_t = adj_close_t / adj_close_{t-1} - 1 for the stock and the index,
    over the months both have; beta = cov(r_stock, r_index) / var(r_index).
    Needs at least MIN_MONTHS returns, else None.

WACC estimate (for comparing companies, not the DCF's own rate):
    r_E = r_f + beta x ERP
    r_D = interest expense / total debt when that lands between r_f and r_f + 10%,
          else r_f + DEFAULT_SPREAD
    weights from market equity and book debt today; tax = effective rate if 0-50%, else 21%
The DCF keeps its own cost of capital (assumptions file); this fills tables.
"""
from __future__ import annotations

MIN_MONTHS = 24
DEFAULT_ERP = 0.05            # course convention
DEFAULT_SPREAD = 0.015
DEFAULT_TAX = 0.21


def monthly_returns(points: list[dict]) -> dict[str, float]:
    """[{month, adj_close}] oldest first -> {month: return over the prior month}."""
    out, prev = {}, None
    for p in points:
        v = p.get("adj_close")
        if prev and v and prev[1] and _next_month(prev[0]) == p["month"]:
            out[p["month"]] = v / prev[1] - 1
        prev = (p["month"], v)
    return out


def _next_month(m: str) -> str:
    y, mo = int(m[:4]), int(m[5:7])
    return f"{y + (mo == 12)}-{1 if mo == 12 else mo + 1:02d}"


def beta(stock: list[dict], index: list[dict], months: int = 60) -> dict | None:
    rs, ri = monthly_returns(stock), monthly_returns(index)
    common = sorted(set(rs) & set(ri))[-months:]
    if len(common) < MIN_MONTHS:
        return None
    xs, ys = [ri[m] for m in common], [rs[m] for m in common]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    var = sum((x - mx) ** 2 for x in xs)
    if not var:
        return None
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return {"value": cov / var, "months": len(common), "from": common[0], "to": common[-1]}


def wacc_estimate(*, beta_value: float, risk_free: float, market_cap: float, debt: float,
                  interest_expense: float | None, tax_rate: float | None, erp: float = DEFAULT_ERP) -> dict:
    t = tax_rate if tax_rate is not None and 0 <= tax_rate <= 0.5 else DEFAULT_TAX
    implied = interest_expense / debt if interest_expense and debt else None
    rd_basis = "interest / debt" if implied is not None and risk_free <= implied <= risk_free + 0.10 else "risk-free + spread"
    rd = implied if rd_basis == "interest / debt" else risk_free + DEFAULT_SPREAD
    re = risk_free + beta_value * erp
    e, d = market_cap, max(debt or 0, 0)
    we, wd = e / (e + d), d / (e + d)
    return {"value": re * we + rd * (1 - t) * wd, "cost_of_equity": re, "pre_tax_cost_of_debt": rd,
            "cost_of_debt_basis": rd_basis, "tax_rate": t, "equity_weight": we, "debt_weight": wd,
            "risk_free": risk_free, "equity_risk_premium": erp}
