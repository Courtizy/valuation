"""Three-statement projection: income statement, balance sheet, cash flow
statement, managerial balance sheet and unlevered free cash flow.

Shared math for every L2 model. A model owns its drivers (assumptions); this
module only turns a base year plus drivers into projected statements, so the
same inputs always give the same statements.

Base year
---------
A flat dict of line items (see BASE_ITEMS). `base_from_detail()` builds it
from a company_detail period. Drivers whose value is null use the base-year
ratio, so "keep last year's margin" needs no number.

Drivers (all optional except revenue)
-------------------------------------
revenue          {"method": "growth", "rates": [..]}
                 {"method": "fade", "g0": .2, "g_terminal": .04, "fade_years": 10}
                     g_t = g0 - (t-1) * (g0 - g_terminal) / fade_years, t = 1..
                     optional "adjust": [..] replaces the fade: g_t = g0 + adjust_t
                     (all zeros = constant growth at g0)
                 {"method": "values", "values": [..]}
cost lines       cogs, sga, rnd, other_opex
                 {"method": "pct_of_sales", "value": x | null, "adjust": [..]}
                     value * sales * (1 + adjust_t)
                 {"method": "same_as_base"}
depreciation,    pct_of_sales | same_as_base |
amortization     {"method": "pct_of_fixed_assets", "value": x | null}  (beginning FA)
costs_include_da true: cost lines already contain D&A, so
                     EBITDA = sales - costs + D&A and EBIT = sales - costs
                 false: EBIT = sales - costs - D&A
interest         {"method": "rate_on_debt", "rate": r, "basis": "beginning" | "average",
                  "cash_rate": r_cash}   (average basis iterates to a fixed point)
                 pct_of_sales | same_as_base
tax_rate         number (applied to EBT)
nonrecurring     list per year (pre-tax, tax deductible), default 0
cash             pct_of_sales | same_as_base | {"method": "min", "value": x}  (plug floor)
receivables      pct_of_sales | {"method": "days", "value": d} | same_as_base
inventory        pct_of_sales | {"method": "turnover", "value": cogs/inv} | days | same_as_base
other_current_assets, accrued     pct_of_sales | same_as_base
payables         pct_of_sales | {"method": "days_purchases", "value": d} | same_as_base
                     purchases = COGS + change in inventory
nwc              {"method": "items"} (default) or
                 {"method": "incremental", "ratio": k}: WCR_t = WCR_t-1 + k * (S_t - S_t-1)
capex            pct_of_sales | same_as_base | {"method": "replacement"} (= D&A)
fixed_assets     {"method": "roll_forward"} (default): FA_t = FA_t-1 + capex - D - A
                 same_as_base | pct_of_sales   (capex is then implied: dFA + D + A)
short_term_debt, long_term_debt   same_as_base (default) | {"method": "schedule", "values": [..]}
other_lt_liabilities              same_as_base (default) | pct_of_sales
dividends        {"payout": p} share of net income, default 0
plug             "equity" (equity balances the sheet) | "cash" | "revolver"
amortization_tax_deductible   share of amortization that shields tax, default 1
provisions       list per year, deducted in FCF, default 0
"""
from __future__ import annotations

from copy import deepcopy

BASE_ITEMS = (
    "revenue", "cogs", "sga", "rnd", "other_opex", "depreciation", "amortization",
    "interest_expense", "interest_income", "income_taxes", "net_income",
    "cash", "receivables", "inventory", "other_current_assets", "fixed_assets",
    "payables", "accrued", "short_term_debt", "long_term_debt", "other_lt_liabilities", "equity",
)
COST_LINES = ("cogs", "sga", "rnd", "other_opex")
WCR_ASSETS = ("receivables", "inventory", "other_current_assets")
WCR_LIABS = ("payables", "accrued")
MAX_ITER, TOL = 200, 1e-9


class ProjectionError(ValueError):
    pass


def _ratio(num, den):
    return (num or 0) / den if den else 0.0


def revenue_path(driver: dict, base_revenue: float, years: int) -> list[float]:
    m = driver.get("method")
    if m == "values":
        vals = list(driver["values"])
        if len(vals) < years:
            raise ProjectionError("revenue values shorter than the horizon")
        return vals[:years]
    if m == "growth":
        rates = list(driver["rates"])
    elif m == "fade":
        g0 = driver["g0"]
        if driver.get("adjust") is not None:          # explicit per-year adjustments replace the fade
            rates = [g0 + _per_year(driver["adjust"], t) for t in range(years)]
        else:
            gt, n = driver["g_terminal"], driver["fade_years"]
            rates = [g0 - min(t, n) * (g0 - gt) / n for t in range(years)]
    else:
        raise ProjectionError(f"unknown revenue method {m!r}")
    if len(rates) < years:
        rates += [rates[-1]] * (years - len(rates))
    out, s = [], base_revenue
    for g in rates[:years]:
        s = s * (1 + g)
        out.append(s)
    return out


def _per_year(x, t: int, default=0.0):
    if x is None:
        return default
    if isinstance(x, (list, tuple)):
        return x[t] if t < len(x) else (x[-1] if x else default)
    return x


class _Ctx:
    def __init__(self, base: dict, drivers: dict):
        self.b, self.d = base, drivers

    def drv(self, name, default=None):
        return self.d.get(name) or default or {"method": "same_as_base"}

    def pct_of_sales(self, name, dr, sales, t):
        value = dr.get("value")
        if value is None:
            value = _ratio(self.b.get(name), self.b["revenue"])
        return _per_year(value, t) * sales * (1 + _per_year(dr.get("adjust"), t))


def _flow_line(ctx: _Ctx, name: str, row: dict, prev: dict, t: int) -> float:
    dr = ctx.drv(name)
    m = dr["method"]
    if m == "pct_of_sales":
        return ctx.pct_of_sales(name, dr, row["revenue"], t)
    if m == "same_as_base":
        return ctx.b.get(name) or 0.0
    if m == "pct_of_fixed_assets":
        v = dr.get("value")
        if v is None:
            v = _ratio(ctx.b.get(name), ctx.b.get("fixed_assets"))
        return _per_year(v, t) * prev["fixed_assets"]
    if m == "values":
        return _per_year(dr["values"], t)
    raise ProjectionError(f"{name}: unknown method {m!r}")


def _balance_line(ctx: _Ctx, name: str, row: dict, prev: dict, t: int) -> float:
    dr = ctx.drv(name)
    m = dr["method"]
    days = ctx.d.get("days_in_year", 365)
    if m == "same_as_base":
        return prev[name]
    if m == "pct_of_sales":
        return ctx.pct_of_sales(name, dr, row["revenue"], t)
    if m == "days":
        flow = row["cogs"] if name == "inventory" else row["revenue"]
        return _per_year(dr["value"], t) * flow / days
    if m == "turnover":
        return row["cogs"] / _per_year(dr["value"], t)
    if m == "days_purchases":
        purchases = row["cogs"] + row["inventory"] - prev["inventory"]
        return _per_year(dr["value"], t) * purchases / days
    if m == "schedule":
        return _per_year(dr["values"], t)
    raise ProjectionError(f"{name}: unknown method {m!r}")


def _opening(base: dict) -> dict:
    row = {k: base.get(k) or 0.0 for k in BASE_ITEMS}
    row["revolver"] = 0.0
    row["wcr"] = sum(row[k] for k in WCR_ASSETS) - sum(row[k] for k in WCR_LIABS)
    return row


def _income_statement(ctx: _Ctx, row: dict, prev: dict, t: int, interest: tuple[float, float]):
    d = ctx.d
    for name in COST_LINES:
        row[name] = _flow_line(ctx, name, row, prev, t) if name in d or ctx.b.get(name) else 0.0
    row["depreciation"] = _flow_line(ctx, "depreciation", row, prev, t)
    row["amortization"] = _flow_line(ctx, "amortization", row, prev, t) if (
        "amortization" in d or ctx.b.get("amortization")) else 0.0
    costs = sum(row[k] for k in COST_LINES)
    da = row["depreciation"] + row["amortization"]
    if d.get("costs_include_da", True):
        row["ebitda"] = row["revenue"] - costs + da
    else:
        row["ebitda"] = row["revenue"] - costs
    row["ebit"] = row["ebitda"] - da
    row["interest_expense"], row["interest_income"] = interest
    row["nonrecurring"] = _per_year(d.get("nonrecurring"), t)
    row["ebt"] = row["ebit"] - row["interest_expense"] + row["interest_income"] - row["nonrecurring"]
    row["tax_rate"] = _per_year(d.get("tax_rate"), t, default=_ratio(ctx.b.get("income_taxes"),
                                                                       _base_ebt(ctx.b)))
    row["income_taxes"] = row["ebt"] * row["tax_rate"]
    row["net_income"] = row["ebt"] - row["income_taxes"]


def _base_ebt(b: dict) -> float:
    if b.get("net_income") is not None and b.get("income_taxes") is not None:
        return b["net_income"] + b["income_taxes"]
    return 0.0


def _interest(ctx: _Ctx, row: dict, prev: dict, t: int) -> tuple[float, float]:
    dr = ctx.d.get("interest") or {"method": "same_as_base"}
    m = dr["method"]
    if m == "same_as_base":
        return ctx.b.get("interest_expense") or 0.0, ctx.b.get("interest_income") or 0.0
    if m == "pct_of_sales":
        v = dr.get("value")
        if v is None:
            v = _ratio((ctx.b.get("interest_expense") or 0) - (ctx.b.get("interest_income") or 0),
                       ctx.b["revenue"])
        return _per_year(v, t) * row["revenue"], 0.0
    if m == "rate_on_debt":
        debt_prev = prev["short_term_debt"] + prev["long_term_debt"] + prev["revolver"]
        cash_prev = prev["cash"]
        if dr.get("basis", "beginning") == "average" and "short_term_debt" in row:
            debt = (debt_prev + row["short_term_debt"] + row["long_term_debt"] + row["revolver"]) / 2
            cash = (cash_prev + row["cash"]) / 2
        else:
            debt, cash = debt_prev, cash_prev
        return _per_year(dr["rate"], t) * debt, _per_year(dr.get("cash_rate", 0.0), t) * cash
    raise ProjectionError(f"interest: unknown method {m!r}")


def _balance_sheet(ctx: _Ctx, row: dict, prev: dict, t: int) -> None:
    d = ctx.d
    # capex and fixed assets
    capex_dr = d.get("capex") or {"method": "replacement"}
    if capex_dr["method"] == "replacement":
        capex = row["depreciation"] + row["amortization"]
    else:
        capex = _flow_line(ctx, "capex", row, prev, t) if capex_dr["method"] != "same_as_base" \
            else ctx.b.get("capex") or 0.0
    fa_dr = d.get("fixed_assets") or {"method": "roll_forward"}
    if fa_dr["method"] == "roll_forward":
        row["fixed_assets"] = prev["fixed_assets"] + capex - row["depreciation"] - row["amortization"]
        row["capex"] = capex
    else:
        row["fixed_assets"] = _balance_line(ctx, "fixed_assets", row, prev, t)
        row["capex"] = row["fixed_assets"] - prev["fixed_assets"] + row["depreciation"] + row["amortization"]

    # working capital requirement
    nwc = d.get("nwc") or {"method": "items"}
    if nwc["method"] == "incremental":
        for k in WCR_ASSETS + WCR_LIABS:
            row[k] = prev[k]
        row["wcr"] = prev["wcr"] + _per_year(nwc["ratio"], t) * (row["revenue"] - prev["revenue"])
        row["other_current_assets"] += row["wcr"] - prev["wcr"]   # carry the change in one line
    else:
        for k in ("inventory",) + tuple(x for x in WCR_ASSETS + WCR_LIABS if x != "inventory"):
            row[k] = _balance_line(ctx, k, row, prev, t)
        row["wcr"] = sum(row[k] for k in WCR_ASSETS) - sum(row[k] for k in WCR_LIABS)

    for k in ("short_term_debt", "long_term_debt", "other_lt_liabilities"):
        row[k] = _balance_line(ctx, k, row, prev, t)

    payout = _per_year((d.get("dividends") or {}).get("payout"), t)
    row["dividends"] = max(row["net_income"], 0) * payout
    plug = d.get("plug", "equity")
    cash_dr = d.get("cash") or {"method": "same_as_base"}

    if plug == "equity":
        row["cash"] = _balance_line(ctx, "cash", row, prev, t)
        row["revolver"] = prev["revolver"]
        assets = row["cash"] + sum(row[k] for k in WCR_ASSETS) + row["fixed_assets"]
        liabs = (sum(row[k] for k in WCR_LIABS) + row["short_term_debt"] + row["revolver"]
                 + row["long_term_debt"] + row["other_lt_liabilities"])
        row["equity"] = assets - liabs
    elif plug in ("cash", "revolver"):
        row["equity"] = prev["equity"] + row["net_income"] - row["dividends"]
        non_cash = sum(row[k] for k in WCR_ASSETS) + row["fixed_assets"]
        funding = (sum(row[k] for k in WCR_LIABS) + row["short_term_debt"] + row["long_term_debt"]
                   + row["other_lt_liabilities"] + row["equity"])
        floor = 0.0
        if plug == "revolver" or cash_dr["method"] == "min":
            floor = (_balance_line(ctx, "cash", row, prev, t) if cash_dr["method"] != "min"
                     else _per_year(cash_dr["value"], t))
        cash = funding - non_cash
        if cash < floor:
            row["revolver"], row["cash"] = floor - cash, floor
        else:
            row["revolver"], row["cash"] = 0.0, cash
    else:
        raise ProjectionError(f"unknown plug {plug!r}")


def _cash_flow(row: dict, prev: dict) -> dict:
    d_wcr = row["wcr"] - prev["wcr"]
    d_oltl = row["other_lt_liabilities"] - prev["other_lt_liabilities"]
    cfo = row["net_income"] + row["depreciation"] + row["amortization"] - d_wcr + d_oltl
    cfi = -row["capex"]
    d_debt = (row["short_term_debt"] + row["long_term_debt"] + row["revolver"]
              - prev["short_term_debt"] - prev["long_term_debt"] - prev["revolver"])
    equity_other = row["equity"] - prev["equity"] - row["net_income"] + row["dividends"]
    cff = d_debt - row["dividends"] + equity_other
    return {"cfo": cfo, "cfi": cfi, "cff": cff, "change_in_debt": d_debt,
            "equity_issued_or_plug": equity_other, "change_in_cash": row["cash"] - prev["cash"],
            "ties": abs(cfo + cfi + cff - (row["cash"] - prev["cash"])) < 1e-6 * max(1.0, abs(row["revenue"]))}


def _managerial(row: dict) -> dict:
    fixed = row["fixed_assets"]
    ic = row["cash"] + row["wcr"] + fixed
    ce = row["short_term_debt"] + row["revolver"] + row["long_term_debt"] + row["other_lt_liabilities"] + row["equity"]
    return {"cash": row["cash"], "wcr": row["wcr"], "fixed_assets": fixed, "invested_capital": ic,
            "short_term_debt": row["short_term_debt"] + row["revolver"],
            "long_term_financing": row["long_term_debt"] + row["other_lt_liabilities"],
            "equity": row["equity"], "capital_employed": ce}


def _fcf(row: dict, prev: dict, d: dict, t: int) -> dict:
    tax = row["tax_rate"]
    deductible = d.get("amortization_tax_deductible", 1.0)
    d_nwc = row["wcr"] - prev["wcr"]
    provisions = _per_year(d.get("provisions"), t)
    fcf = (row["ebitda"] * (1 - tax) + row["depreciation"] * tax
           + row["amortization"] * tax * deductible - row["capex"] - d_nwc - provisions)
    return {"nopat": row["ebit"] * (1 - tax), "ebitda": row["ebitda"], "depreciation": row["depreciation"],
            "amortization": row["amortization"], "capex": row["capex"], "change_in_nwc": d_nwc,
            "provisions": provisions, "fcf": fcf}


def project(base: dict, drivers: dict, years: int) -> dict:
    """Return {"years": [..per-year statements..], "base": opening row, "drivers": drivers}."""
    if not base.get("revenue"):
        raise ProjectionError("base revenue is required")
    if "revenue" not in drivers:
        raise ProjectionError("a revenue driver is required")
    ctx = _Ctx(base, drivers)
    sales = revenue_path(drivers["revenue"], base["revenue"], years)
    prev = _opening(base)
    out = []
    iterative = (drivers.get("interest") or {}).get("basis") == "average"
    for t in range(years):
        row = {"year": t + 1, "revenue": sales[t]}
        _income_statement(ctx, row, prev, t, _interest(ctx, row, prev, t))
        _balance_sheet(ctx, row, prev, t)
        if iterative:
            for _ in range(MAX_ITER):
                ie = _interest(ctx, row, prev, t)
                before = row["net_income"]
                _income_statement(ctx, row, prev, t, ie)
                _balance_sheet(ctx, row, prev, t)
                if abs(row["net_income"] - before) <= TOL * max(1.0, abs(before)):
                    break
            else:
                raise ProjectionError(f"interest did not converge in year {t + 1}")
        row["cash_flow"] = _cash_flow(row, prev)
        row["managerial"] = _managerial(row)
        row["free_cash_flow"] = _fcf(row, prev, drivers, t)
        row["balance_check"] = (row["managerial"]["invested_capital"] - row["managerial"]["capital_employed"])
        out.append(row)
        prev = row
    return {"base": _opening(base), "drivers": deepcopy(drivers), "years": out}


# ------------------------------------------------- base year from L1 output

def base_from_detail(values: dict) -> dict:
    """Map a company_detail period's values (concept ids) to projection items.

    Working-capital lines come from totals so nothing untagged goes missing:
    other current assets = current assets - cash - receivables - inventory,
    accrued (and other current liabilities) = current liabilities - payables - short-term debt.
    Fixed assets = total assets - current assets. Equity includes the NCI.
    """
    v = values
    g = lambda k: v.get(k) or 0.0  # noqa: E731
    da = v.get("depreciation_amortization_cf")
    dep = v.get("depreciation_expense")
    amort = v.get("amortization_of_intangibles")
    if da is not None and dep is None:
        dep, amort = da - (amort or 0), amort
    liabilities = v.get("liabilities")
    if liabilities is None and v.get("liabilities_and_equity") is not None:
        eq = v.get("all_equity_balance_including_minority_interest")
        if eq is None:
            eq = g("all_equity_balance") + g("minority_interest_balance")
        liabilities = v["liabilities_and_equity"] - eq - g("temporary_and_mezzanine_financing")
    ca, cl = g("current_assets_total"), g("current_liabilities_total")
    lt_liab = (liabilities or 0) - cl
    return {
        "revenue": v.get("revenue"),
        "cogs": v.get("cost_of_goods_and_services_sold"),
        "sga": v.get("selling_general_and_admin_expenses"),
        "rnd": v.get("research_and_development_expenses"),
        "other_opex": v.get("other_operating_expense"),
        "depreciation": dep,
        "amortization": amort,
        "capex": v.get("capital_expenses"),
        "interest_expense": v.get("interest_expense"),
        "interest_income": v.get("interest_income"),
        "income_taxes": v.get("income_taxes"),
        "net_income": v.get("profit_loss", v.get("net_income")),
        "cash": g("cash_and_marketable_securities"),
        "receivables": g("trade_receivables"),
        "inventory": g("inventories"),
        "other_current_assets": ca - g("cash_and_marketable_securities") - g("trade_receivables") - g("inventories"),
        "fixed_assets": g("assets") - ca,
        "payables": g("trade_payables"),
        "accrued": cl - g("trade_payables") - g("short_term_debt"),
        "short_term_debt": g("short_term_debt"),
        "long_term_debt": g("long_term_debt"),
        "other_lt_liabilities": lt_liab - g("long_term_debt"),
        "equity": g("assets") - (liabilities or 0),
    }


def statement_row(y: dict) -> dict:
    """The income-statement and cash-flow lines the site shows for a projected year."""
    return {
        "year": y["year"], "revenue": y["revenue"], "cogs": y["cogs"], "gross_profit": y["revenue"] - y["cogs"],
        "rnd": y["rnd"], "sga": y["sga"], "other_opex": y["other_opex"], "ebitda": y["ebitda"],
        "depreciation": y["depreciation"] + y["amortization"], "ebit": y["ebit"],
        "interest_net": y["interest_expense"] - y["interest_income"], "ebt": y["ebt"],
        "income_taxes": y["income_taxes"], "net_income": y["net_income"], "capex": y["capex"],
        "change_in_nwc": y["free_cash_flow"]["change_in_nwc"], "fcf": y["free_cash_flow"]["fcf"],
    }
