"""A company's latest figures from company detail (latest TTM, else latest fiscal year), shared by
the models that value a target off multiples (comps, precedents)."""
from __future__ import annotations


def _latest_values(detail: dict | None) -> dict:
    if not detail:
        return {}
    views = detail.get("views") or {}
    period = (views.get("ttm") or views.get("annual") or [None])[-1]
    return dict(period["values"]) if period else {}


def _past_growth(detail: dict | None, years: int = 5) -> tuple[float | None, str | None]:
    """Earnings growth per year over up to `years` fiscal years: diluted EPS, else net income
    (both ends positive), from the filings."""
    ann = (((detail or {}).get("views") or {}).get("annual") or [])[-(years + 1):]
    for key in ("eps_diluted", "net_income"):
        pts = [(p["label"], p["values"].get(key)) for p in ann if isinstance(p["values"].get(key), (int, float))]
        if len(pts) >= 3 and pts[0][1] > 0 and pts[-1][1] > 0:
            n = len(pts) - 1
            return (pts[-1][1] / pts[0][1]) ** (1 / n) - 1, f"{'EPS' if key == 'eps_diluted' else 'net income'} {pts[0][0]}–{pts[-1][0]} (filings)"
    return None, None


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
        # the course's comparison rows: analysts' five-year earnings growth, past five-year growth,
        # discount rate (the market WACC estimate from beta)
        "growth_5y": None, "growth_past_5y": None, "discount_rate": None,
    }
    sources = {}
    mkt = (detail or {}).get("market") or {}
    if mkt.get("price") is not None:            # market data from L1; a price typed in comps.json still wins
        f["price"], f["price_source"] = mkt["price"], f"market data ({mkt.get('source')}, {mkt.get('price_date')})"
        if mkt.get("shares_outstanding"):
            f["shares"] = mkt["shares_outstanding"]
    if (mkt.get("beta") or {}).get("value") is not None:
        f["beta"] = mkt["beta"]["value"]
    est = mkt.get("estimates") or {}
    if est.get("growth_5y") is not None:
        f["growth_5y"], sources["growth_5y"] = est["growth_5y"], f"analysts, next 5 years ({est.get('source')}, {est.get('fetched') or 'today'})"
    elif est.get("growth_1y") is not None:
        f["growth_5y"], sources["growth_5y"] = est["growth_1y"], f"analysts, next year only ({est.get('source')}, {est.get('fetched') or 'today'})"
    f["growth_past_5y"], sources["growth_past_5y"] = _past_growth(detail)
    if f["growth_past_5y"] is None and est.get("growth_past_5y") is not None:
        f["growth_past_5y"], sources["growth_past_5y"] = est["growth_past_5y"], f"past 5 years ({est.get('source')})"
    if (mkt.get("wacc") or {}).get("value") is not None:
        f["discount_rate"], sources["discount_rate"] = mkt["wacc"]["value"], "WACC estimate from beta (market data)"
    for k, val in (manual or {}).items():
        if k in f or k in ("price", "beta", "name"):
            f[k] = val
            if k == "price":
                f["price_source"] = "comps.json"
            if k in ("growth_5y", "growth_past_5y", "discount_rate"):
                sources[k] = "typed in comps.json"
    f["figure_sources"] = {k: v for k, v in sources.items() if v and f.get(k) is not None}
    return f
