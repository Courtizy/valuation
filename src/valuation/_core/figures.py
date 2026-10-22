"""A company's latest figures from company detail (latest TTM, else latest fiscal year), shared by
the models that value a target off multiples (comps, precedents)."""
from __future__ import annotations


def _latest_values(detail: dict | None) -> dict:
    if not detail:
        return {}
    views = detail.get("views") or {}
    period = (views.get("ttm") or views.get("annual") or [None])[-1]
    return dict(period["values"]) if period else {}


def company_figures(detail: dict | None, manual: dict | None = None) -> dict:
    """Sales, EBITDA, net income, debt, cash, shares from detail; manual entries override."""
    v = _latest_values(detail)
    f = {
        "sales": v.get("revenue"),
        "ebitda": v.get("ebitda"),
        "net_income": v.get("net_income", v.get("profit_loss")),
        "debt": ((v.get("short_term_debt") or 0) + (v.get("long_term_debt") or 0))
        if v.get("long_term_debt") is not None or v.get("short_term_debt") is not None else None,
        "cash": v.get("cash_and_marketable_securities"),
        # newest filed count (10-K/10-Q cover page, carried in company detail), else the statements'
        "shares": ((detail or {}).get("shares_outstanding") or v.get("shares_year_end")
                   or v.get("shares_fully_diluted_average")),
        "revenue_growth": ((detail or {}).get("profile") or {}).get("vector", {}).get("revenue_cagr"),
    }
    mkt = (detail or {}).get("market") or {}
    if mkt.get("price") is not None:            # market data from L1; a price typed in comps.json still wins
        f["price"], f["price_source"] = mkt["price"], f"market data ({mkt.get('source')}, {mkt.get('price_date')})"
        if mkt.get("shares_outstanding"):
            f["shares"] = mkt["shares_outstanding"]
    if (mkt.get("beta") or {}).get("value") is not None:
        f["beta"] = mkt["beta"]["value"]
    for k, val in (manual or {}).items():
        if k in f or k in ("price", "beta", "name"):
            f[k] = val
            if k == "price":
                f["price_source"] = "comps.json"
    return f
