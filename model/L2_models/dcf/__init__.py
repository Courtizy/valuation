"""Standalone DCF.

Inputs: company_detail.json (L1) and inputs/assumptions/{TICKER}/dcf.json. Market
inputs (price, rates, beta) come from the assumptions file until a market-data
adapter exists.

Steps
-----
1. Base period: the latest TTM (or latest fiscal year) from company detail.
   Cost lines are kept as percentages of sales; "other operating" is the
   residual, so base-year EBIT equals reported operating income.
2. Projection (core.projection): revenue grows at g0 and fades linearly to
   terminal growth over the years to terminal (or follows explicit per-year
   adjustments); costs, D&A and capex stay at their ratios to sales;
   working capital grows by (dNWC/dSales) x dSales. Year 1 is the closing
   year, and the projection runs years_to_terminal + 1 years.
3. Discount rates (core.cost_of_capital): beta unlevered at today's market
   D/E and relevered at the target; a pre-terminal WACC and a terminal-year
   WACC on the normalized long-run rate.
4. Value (core.dcf): discounted FCF plus a Gordon terminal value, less net
   debt (debt - cash not needed for operations), over diluted shares (TSM).
5. Range: conservative / expected / aggressive from the two sensitivity
   moves, blended by the terminal value's share.

Modes
-----
forecast  your growth assumption gives a value per share.
implied   solves near-term growth so the value equals the market price; the
          answer is what the price implies, and the range is built around it.
"""
from __future__ import annotations

from copy import deepcopy

from core.cost_of_capital import discount_rates
from core.dcf import scenario_range, sensitivity_grid, solve, value_firm
from core.projection import base_from_detail, project
from core.shares import treasury_stock_method
from core.projection import statement_row
from L2_models.base import ModelResult

DEFAULT_NWC_RATIO = 0.20          # used when history can't give dNWC/dSales
NWC_HISTORY_YEARS = 4


class AssumptionError(ValueError):
    pass


def _need(d: dict, key: str, where: str):
    v = d.get(key)
    if v is None:
        raise AssumptionError(f"dcf assumptions: {where}.{key} is required")
    return v


def _base_period(detail: dict, which: str) -> dict:
    views = detail["views"]
    if which == "ttm" and views.get("ttm"):
        return views["ttm"][-1]
    if views.get("annual"):
        return views["annual"][-1]
    if views.get("ttm"):
        return views["ttm"][-1]
    raise AssumptionError("company detail has no 12-month period to start from")


def _nwc_ratio(detail: dict, warnings: list[str]) -> float:
    """dNWC/dSales over recent fiscal years, from the managerial WCR (excludes cash)."""
    an = [a for a in detail["analysis"]["annual"] if a["managerial_balance_sheet"]["wcr"] is not None]
    periods = {p["end"]: p["values"].get("revenue") for p in detail["views"]["annual"]}
    an = [a for a in an if periods.get(a["end"]) is not None][-NWC_HISTORY_YEARS:]
    if len(an) >= 2:
        d_wcr = an[-1]["managerial_balance_sheet"]["wcr"] - an[0]["managerial_balance_sheet"]["wcr"]
        d_s = periods[an[-1]["end"]] - periods[an[0]["end"]]
        if d_s > 0:
            k = d_wcr / d_s
            if -1 <= k <= 1:
                return k
    warnings.append(f"dNWC/dSales not measurable from history; using {DEFAULT_NWC_RATIO}")
    return DEFAULT_NWC_RATIO


DEFAULT_CREDIT_SPREAD = 0.015
DEFAULT_TERMINAL_GROWTH = 0.025
DEFAULT_ERP = 0.05
GROWTH_CAP = (-0.05, 0.20)


def default_assumptions(detail: dict) -> dict:
    """The default case, used when inputs/assumptions/{TICKER}/dcf.json doesn't exist.

    Everything comes from the data: revenue growth = the company's own historical CAGR
    (from the L1 trend case, capped to -5%..20%) fading to 2.5% terminal growth over ten
    years; 5% equity risk premium; risk-free from FRED and price / beta from market data
    when present (else the sector's illustrative beta and book D/E); cost lines, capex,
    tax and working capital from the filings. A dcf.json always replaces it."""
    trend = ((detail or {}).get("projection") or {}).get("assumptions") or {}
    g0 = trend.get("revenue_growth_start")
    g0 = 0.05 if g0 is None else min(max(g0, GROWTH_CAP[0]), GROWTH_CAP[1])
    return {
        "default_case": True, "mode": "forecast", "base_period": "annual",
        "market": {"price": None, "basic_shares": None, "options": []},
        "forecast": {"years_to_terminal": 10, "revenue_growth": g0, "terminal_growth": DEFAULT_TERMINAL_GROWTH},
        "cost_of_capital": {"risk_free": None, "risk_free_terminal": None, "equity_risk_premium": DEFAULT_ERP, "beta": None,
                            "pre_tax_cost_of_debt": None, "pre_tax_cost_of_debt_fallback": None},
        "bridge": {"operating_cash_pct": 0.5, "include_longterm_investments": False},
        "terminal": {"method": "gordon", "weight": 1.0},
        "sources": {
            "revenue_growth": f"default case: historical revenue CAGR {g0:.1%} (capped {GROWTH_CAP[0]:.0%} to {GROWTH_CAP[1]:.0%}), fading over 10 years",
            "terminal_growth": f"default case: {DEFAULT_TERMINAL_GROWTH:.1%}",
            "equity_risk_premium": f"default case: {DEFAULT_ERP:.0%}",
            "pre_tax_cost_of_debt": "interest expense / total debt from the filings, else risk-free + 1.5%",
        },
    }


class DCF:
    name = "dcf"
    needs_peers = False

    # ------------------------------------------------------------- inputs
    def prepare(self, detail: dict, assumptions: dict) -> dict:
        if not detail or "views" not in detail:
            raise AssumptionError("dcf needs company_detail.json")
        a = deepcopy(assumptions or {})
        fc, cc = a.get("forecast", {}), a.get("cost_of_capital", {})
        mkt, br = a.get("market", {}), a.get("bridge", {})
        warnings: list[str] = []
        period = _base_period(detail, a.get("base_period", "annual"))
        v = period["values"]
        base = base_from_detail(v)
        rev = base["revenue"]
        if not rev:
            raise AssumptionError(f"no revenue in {period['label']}")

        # D&A as one line; residual "other operating" ties EBIT to operating income
        base["depreciation"] = (base["depreciation"] or 0) + (base["amortization"] or 0)
        base["amortization"] = 0.0
        if v.get("operating_income_loss") is not None:
            named = sum(base.get(k) or 0 for k in ("cogs", "sga", "rnd"))
            base["other_opex"] = rev - named - v["operating_income_loss"]
        else:
            warnings.append("operating income missing; EBIT built from the cost lines present")

        tax = fc.get("tax_rate")
        if tax is None:
            etr = v.get("effective_tax_rate")
            tax = etr if etr is not None and 0 <= etr <= 0.5 else 0.21
            warnings.append(f"tax rate not given; using {tax:.3f} ({'effective' if etr is not None and 0 <= etr <= 0.5 else 'statutory default'})")
        nwc = fc.get("nwc_to_sales_change")
        if nwc is None:
            nwc = _nwc_ratio(detail, warnings)
        capex = fc.get("capex_pct_revenue")
        if capex is None:
            capex = (base.get("capex") or base["depreciation"]) / rev
        cost_pct = fc.get("cost_pct_revenue") or {}
        ratio = lambda k: cost_pct.get(k, (base.get(k) or 0) / rev)  # noqa: E731

        n = int(fc.get("years_to_terminal", 10))
        if n < 1:
            raise AssumptionError("forecast.years_to_terminal must be at least 1")
        revenue_driver = {"method": "fade", "g0": fc.get("revenue_growth", 0.0),
                          "g_terminal": _need(fc, "terminal_growth", "forecast"), "fade_years": n}
        if fc.get("growth_adjust") is not None:
            revenue_driver["adjust"] = fc["growth_adjust"]
        drivers = {
            "revenue": revenue_driver,
            "cogs": {"method": "pct_of_sales", "value": ratio("cogs")},
            "sga": {"method": "pct_of_sales", "value": ratio("sga")},
            "rnd": {"method": "pct_of_sales", "value": ratio("rnd")},
            "other_opex": {"method": "pct_of_sales", "value": ratio("other_opex")},
            "depreciation": {"method": "pct_of_sales", "value": base["depreciation"] / rev},
            "amortization": {"method": "values", "values": [0]},
            "capex": {"method": "pct_of_sales", "value": capex},
            "nwc": {"method": "incremental", "ratio": nwc},
            "interest": {"method": "same_as_base"},
            "tax_rate": tax,
            "costs_include_da": True,
            "plug": "cash",
        }

        # market data (L1 detail["market"]) fills price, beta and the risk-free rate when the
        # assumptions file leaves them blank; a value in the file always wins
        live = detail.get("market") or {}
        sources = dict(a.get("sources") or {})
        if mkt.get("price") is None and live.get("price") is not None:
            mkt["price"] = live["price"]
            sources["price"] = f"close {live.get('price_date')} from market data ({live.get('source')})"
        if cc.get("beta") is None and (live.get("beta") or {}).get("value") is not None:
            b = live["beta"]
            cc["beta"] = b["value"]
            sources["beta"] = (f"{b['value']:.2f}, {b['basis']}" if b.get("basis")
                               else f"{b['value']:.2f}, {b['months']} monthly returns vs {b.get('index')} ({live.get('source')})")
        rf_doc = detail.get("risk_free") or {}
        if cc.get("risk_free") is None and (live.get("wacc") or {}).get("risk_free") is not None:
            cc["risk_free"] = live["wacc"]["risk_free"]
            sources["risk_free"] = f"{live['wacc'].get('risk_free_series', 'DGS10')} on {live['wacc'].get('risk_free_date')} (FRED)"
        elif cc.get("risk_free") is None and rf_doc.get("value") is not None:
            cc["risk_free"] = rf_doc["value"]
            sources["risk_free"] = f"{rf_doc.get('series', 'DGS10')} on {rf_doc.get('date')} (FRED)"
        if cc.get("pre_tax_cost_of_debt_fallback") is None and a.get("default_case") and cc.get("risk_free") is not None:
            cc["pre_tax_cost_of_debt_fallback"] = cc["risk_free"] + DEFAULT_CREDIT_SPREAD
        if cc.get("beta") is None:
            # no beta in the file and none from market data (showcase mode): the sector's typical beta,
            # which L1 puts in company detail (inputs/sectors/taxonomy.json "typical_beta")
            tb = detail.get("sector_beta") or {"value": 1.0, "basis": "market beta of 1.0 (no sector beta in company detail)"}
            cc["beta"] = tb["value"]
            sources["beta"] = f"{tb['value']:.2f}, {tb['basis']}"
            warnings.append(f"beta not given and no market beta: using the {tb['basis']}, {tb['value']:.2f}")
        a["sources"] = sources

        # shares and bridge
        price = mkt.get("price")
        basic = (mkt.get("basic_shares") or live.get("shares_outstanding") or detail.get("shares_outstanding")
                 or v.get("shares_year_end") or v.get("shares_fully_diluted_average"))
        if not basic:
            raise AssumptionError("no share count: set market.basic_shares")
        options = mkt.get("options") or []
        if options and not price:
            raise AssumptionError("market.price is needed to apply the treasury stock method")
        tsm = treasury_stock_method(basic, price, options) if price else None
        shares = tsm["diluted"] if tsm else basic
        debt = (v.get("short_term_debt") or 0) + (v.get("long_term_debt") or 0)
        cash = v.get("cash_and_marketable_securities") or 0
        if br.get("include_longterm_investments"):
            cash += v.get("longterm_investments") or 0    # e.g. non-current marketable securities
        op_cash = br.get("operating_cash_pct", 0.5)
        net_debt = debt - cash * (1 - op_cash)

        # discount rates
        current_de = cc.get("current_debt_to_equity")
        solve_de = False
        if current_de is None:
            if price:
                current_de = debt / (price * shares)
            elif cc.get("target_debt_to_equity") is not None:
                current_de = cc["target_debt_to_equity"]
                warnings.append("no market price: today's D/E taken as the target D/E")
            else:
                # no price: D/E at the model's own equity value, solved in run() (book equity is often
                # tiny or negative after buybacks, so book D/E would misstate leverage)
                solve_de, current_de = True, 0.5
        rf = _need(cc, "risk_free", "cost_of_capital")
        rd, rd_method = self.cost_of_debt(cc, v, debt, rf, warnings)
        rates = discount_rates(
            risk_free=rf,
            pre_tax_cost_of_debt=rd,
            beta=_need(cc, "beta", "cost_of_capital"),
            equity_risk_premium=_need(cc, "equity_risk_premium", "cost_of_capital"),
            tax_rate=tax, current_debt_to_equity=current_de,
            target_debt_to_equity=cc.get("target_debt_to_equity"),
            risk_free_terminal=cc.get("risk_free_terminal"))
        rates.update(pre_tax_cost_of_debt=rd, cost_of_debt_method=rd_method)
        rate_args = dict(risk_free=rf, pre_tax_cost_of_debt=rd, beta=cc["beta"], equity_risk_premium=cc["equity_risk_premium"],
                         tax_rate=tax, target_debt_to_equity=cc.get("target_debt_to_equity"),
                         risk_free_terminal=cc.get("risk_free_terminal"))

        invested = (v.get("assets") or 0) - ((v.get("current_liabilities_total") or 0) - (v.get("short_term_debt") or 0))
        return {
            "period": period, "base": base, "drivers": drivers, "years": n + 1, "tax": tax, "nwc": nwc,
            "capex": capex, "rates": rates, "price": price, "shares": shares, "tsm": tsm,
            "net_debt": net_debt, "debt": debt, "cash": cash, "operating_cash_pct": op_cash,
            "tv_weight": a.get("terminal", {}).get("weight", 1.0),
            "convention": a.get("discounting", {}).get("convention", "closing_year_zero"),
            "ic_to_sales": (invested - cash) / rev if invested else None,
            "mode": a.get("mode", "forecast"), "sensitivity": a.get("sensitivity", {}),
            "risk_free": rf, "default_case": bool(a.get("default_case")),
            "solve_de": solve_de, "rate_args": rate_args,
            "sources": a["sources"], "warnings": warnings,
        }

    @staticmethod
    def cost_of_debt(cc: dict, v: dict, debt: float, risk_free: float, warnings: list[str]) -> tuple[float, str]:
        """Pre-tax cost of debt.

        1. An explicit cost_of_capital.pre_tax_cost_of_debt wins.
        2. Otherwise interest expense / total debt from the base period (the usual method).
        3. If that can't be measured, cost_of_capital.pre_tax_cost_of_debt_fallback
           (e.g. yield to maturity on the company's bonds) is required.
        """
        if cc.get("pre_tax_cost_of_debt") is not None:
            return cc["pre_tax_cost_of_debt"], "given"
        interest = v.get("interest_expense")
        if interest is None:
            interest = v.get("interest_paid")
        if interest and debt > 0:
            rd = interest / debt
            if rd < risk_free:
                warnings.append(f"interest / debt = {rd:.2%} is below the risk-free rate {risk_free:.2%}: "
                                "older low-coupon debt; the terminal debt rate keeps that negative spread")
            return rd, "interest_over_debt"
        fb = cc.get("pre_tax_cost_of_debt_fallback")
        if fb is None:
            raise AssumptionError("can't measure interest / debt from the filings: set "
                                  "cost_of_capital.pre_tax_cost_of_debt_fallback (e.g. bond yield to maturity)")
        warnings.append("interest / debt not measurable; using the fallback cost of debt")
        return fb, "fallback"

    def solve_debt_to_equity(self, p: dict, iterations: int = 40) -> float:
        """Fixed point: D/E = debt / equity value, where the equity value comes from a DCF at the
        WACC that D/E implies. Damped; equity value floored so a near-zero value can't explode D/E."""
        de = p["rates"]["current_debt_to_equity"]
        for _ in range(iterations):
            eq = self.value(p)["equity_value"]
            target = min(p["debt"] / max(eq, p["debt"] / 4, 1.0), 4.0) if p["debt"] > 0 else 0.0
            new = 0.5 * de + 0.5 * target
            rates = discount_rates(current_debt_to_equity=new, **p["rate_args"])
            rates.update(pre_tax_cost_of_debt=p["rates"]["pre_tax_cost_of_debt"], cost_of_debt_method=p["rates"]["cost_of_debt_method"],
                         debt_to_equity_basis="model equity value")
            p["rates"] = rates
            if abs(new - de) < 1e-6:
                break
            de = new
        return p["rates"]["current_debt_to_equity"]

    def value(self, p: dict, g0: float | None = None, g_terminal: float | None = None,
              wacc: float | None = None, wacc_terminal: float | None = None) -> dict:
        d = deepcopy(p["drivers"])
        if g0 is not None:
            d["revenue"]["g0"] = g0
        if g_terminal is not None:
            d["revenue"]["g_terminal"] = g_terminal
        proj = project(p["base"], d, p["years"])
        out = value_firm(
            proj, wacc=p["rates"]["wacc"] if wacc is None else wacc,
            wacc_terminal=p["rates"]["wacc_terminal"] if wacc_terminal is None else wacc_terminal,
            terminal_growth=d["revenue"]["g_terminal"], tax_rate=p["tax"],
            capex_to_sales_terminal=p["capex"], nwc_to_sales_change=p["nwc"], net_debt=p["net_debt"],
            shares=p["shares"], tv_weight=p["tv_weight"], convention=p["convention"],
            invested_capital_to_sales=p["ic_to_sales"])
        out["projection"] = proj
        return out

    # --------------------------------------------------------------- run
    def run(self, detail: dict, assumptions: dict, peers: list[dict] | None = None) -> ModelResult:
        p = self.prepare(detail, assumptions)
        notes = list(p["warnings"])
        if p["default_case"]:
            notes.insert(0, "default assumptions: no inputs/assumptions dcf.json, so growth comes from the company's history and rates from the data")
        if p["solve_de"]:
            de = self.solve_debt_to_equity(p)
            notes.append(f"no market price: D/E {de:.2f} at the model's own equity value (solved with the WACC it implies)")
        implied = None
        if p["mode"] == "implied" and not p["price"]:
            p["mode"] = "forecast"
            notes.append("no market price (showcase mode or no market data): implied mode needs one, so forecast mode is used")
        if p["mode"] == "implied":
            implied = solve(lambda g: self.value(p, g0=g)["value_per_share"], p["price"], -0.5, 1.0)
            p["drivers"]["revenue"]["g0"] = implied
            notes.append(f"implied near-term growth {implied:.4%} makes the DCF equal the price {p['price']}")
        elif p["mode"] != "forecast":
            raise AssumptionError("mode must be 'forecast' or 'implied'")

        base_val = self.value(p)
        r = p["rates"]
        rev = p["drivers"]["revenue"]
        s = p["sensitivity"]
        scen = scenario_range(
            lambda g0, g_terminal, wacc, wacc_terminal: self.value(
                p, g0=g0, g_terminal=g_terminal, wacc=wacc, wacc_terminal=wacc_terminal)["value_per_share"],
            g0=rev["g0"], g_terminal=rev["g_terminal"], wacc=r["wacc"], wacc_terminal=r["wacc_terminal"],
            tv_share=base_val["terminal_value_share"], growth_step=s.get("growth_step", 0.01),
            wacc_step=s.get("wacc_step", 0.01), terminal_growth_step=s.get("terminal_growth_step", 0.005),
            terminal_wacc_step=s.get("terminal_wacc_step", 0.005))
        notes.append("range = course scenario method (conservative / expected / aggressive), not simulated percentiles")
        grid = sensitivity_grid(
            lambda wacc, wacc_terminal, g_terminal: self.value(
                p, wacc=wacc, wacc_terminal=wacc_terminal, g_terminal=g_terminal)["value_per_share"],
            wacc=r["wacc"], wacc_terminal=r["wacc_terminal"], g_terminal=rev["g_terminal"])

        years = base_val["projection"]["years"]
        growth_path = [y["revenue"] / (years[i - 1]["revenue"] if i else p["base"]["revenue"]) - 1
                       for i, y in enumerate(years)]
        assumptions_used = {
            "forecast": {
                "years": len(years), "frequency": "annual",
                "revenue_growth": growth_path,
                "ebitda_margin": [y["ebitda"] / y["revenue"] for y in years],
                "capex_pct_revenue": p["capex"],
                "nwc_to_sales_change": p["nwc"],
                "tax_rate": p["tax"],
            },
            "cost_of_capital": {
                "risk_free": p["risk_free"],
                "risk_free_terminal": r["risk_free_terminal"],
                "equity_risk_premium": (assumptions.get("cost_of_capital") or {}).get("equity_risk_premium"),
                "beta": r["beta_levered_observed"],
                "beta_relevered": r["beta_relevered"],
                "pre_tax_cost_of_debt": p["rates"]["pre_tax_cost_of_debt"],
                "cost_of_debt_method": p["rates"]["cost_of_debt_method"],
                "target_debt_weight": r["debt_weight"],
                "wacc": r["wacc"],
                "wacc_terminal": r["wacc_terminal"],
            },
            "terminal": {"method": "gordon", "growth": rev["g_terminal"], "weight": p["tv_weight"]},
            "sources": p["sources"],
            "default_case": p["default_case"],
        }
        details = {
            "mode": p["mode"],
            "default_case": p["default_case"],
            "implied_growth": implied,
            "base_period": {"label": p["period"]["label"], "end": p["period"]["end"],
                            "fiscal_year": p["period"].get("fiscal_year"),
                            "kind": "fiscal" if p["period"].get("fiscal_period") == "FY" else "ltm"},
            "market_price": p["price"],
            "rates": r,
            "bridge": {"enterprise_value": base_val["enterprise_value"], "pv_fcf": base_val["pv_fcf"],
                       "pv_terminal_value": base_val["pv_terminal_value"], "debt": p["debt"], "cash": p["cash"],
                       "operating_cash_pct": p["operating_cash_pct"], "net_debt": p["net_debt"],
                       "equity_value": base_val["equity_value"], "shares": p["shares"], "tsm": p["tsm"],
                       "value_per_share": base_val["value_per_share"]},
            "terminal": base_val["terminal"],
            "terminal_value_share": base_val["terminal_value_share"],
            "scenarios": scen,
            "projection": [{"year": y["year"], "revenue": y["revenue"], "ebitda": y["ebitda"], "ebit": y["ebit"],
                            "capex": y["capex"], "change_in_nwc": y["free_cash_flow"]["change_in_nwc"],
                            "fcf": y["free_cash_flow"]["fcf"], "pv": cf["pv"]}
                           for y, cf in zip(years, base_val["cash_flows"])],
            "drivers": p["drivers"],
            "statements": [statement_row(y) for y in years],
            "sensitivity": grid,
        }
        return ModelResult(
            model=self.name,
            ticker=(detail.get("entity") or {}).get("ticker") or "",
            as_of=detail.get("as_of", ""),
            value_per_share={"p10": scen["conservative"], "p50": scen["expected"],
                             "p90": scen["aggressive"], "mean": scen["expected"]},
            assumptions_used=assumptions_used,
            lineage={},
            notes=notes,
            details=details,
        )


MODEL = DCF()
