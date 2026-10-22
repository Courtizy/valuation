"""Acquisition values: the whole-firm DCF with synergies and the just-synergies DCF.

Both start from the standalone DCF's inputs (dcf.json or the default case) and
read the deal from assumptions["deal"] (configs/public/assumptions/{TICKER}/deal.json,
or the deal saved on this device):

    {"pre_announcement_price": null,      # default: the market price
     "synergies": {
        "annual_cost": 300,               # $ per year once fully realized (same units as the filings)
        "revenue_pct_of_cost": 0.33,      # revenue synergies as a share of cost synergies
        "one_time_cost": null,            # default 2 x (cost + revenue synergies), the course's rule of thumb
        "years_to_full": 2,
        "cost_forever": 0.0,              # share of cost synergies that lasts past the terminal year
        "revenue_growth_add": 0.01,       # whole firm: added to revenue growth from year 1
        "cost_realized": 1.0,             # whole firm: share of the cost cut achieved
        "cost_pct": null}}                # whole firm: cut to COGS and SG&A; default annual_cost / (COGS + SG&A)

Checks (Week 9 synergy review):
  - synergies needed for a price: with deal.target_price (else deal.offer_price), the cost cut
    (whole firm, at the given revenue growth add) or the annual synergies (just synergies)
    that make the value equal that price
  - lasting cost synergies: terminal ROIC against the terminal WACC suggests how much of the
    cost synergies can last forever (core.checks.lasting_cost_share)
  - this deal's synergies as a share of the target's sales, to set against prior deals'

The math is in core.synergy. Ranges follow the course's sensitivity tables:
whole firm moves % realized by 25 points and revenue synergy growth by half a
point; just synergies moves the annual synergies by 25%.
"""
from __future__ import annotations

from copy import deepcopy

from valuation._core.checks import lasting_cost_share
from valuation._core.dcf import solve
from valuation._core.synergy import cost_lines, just_synergies, synergy_drivers
from valuation.L2_models.base import ModelResult

REALIZED_STEP, REVENUE_STEP, AMOUNT_STEP, FOREVER_STEP = 0.25, 0.005, 0.25, 0.05
DEFAULTS = {"annual_cost": None, "revenue_pct_of_cost": 0.0, "one_time_cost": None, "years_to_full": 2,
            "cost_forever": 0.0, "revenue_growth_add": 0.0, "cost_realized": 1.0, "cost_pct": None}


class DealError(ValueError):
    pass


def deal_inputs(assumptions: dict) -> dict:
    deal = (assumptions or {}).get("deal")
    if not deal:
        raise DealError("no deal inputs: enter the expected synergies under Deal")
    syn = {**DEFAULTS, **{k: v for k, v in (deal.get("synergies") or {}).items() if v is not None}}
    if syn["annual_cost"] is None:
        raise DealError("deal: synergies.annual_cost is required")
    if syn["one_time_cost"] is None:
        syn["one_time_cost"] = 2 * syn["annual_cost"] * (1 + syn["revenue_pct_of_cost"])
    syn["years_to_full"] = int(syn["years_to_full"])
    if syn["years_to_full"] < 1:
        raise DealError("deal: synergies.years_to_full must be at least 1")
    return {"synergies": syn, "pre_announcement_price": deal.get("pre_announcement_price"),
            "target_price": deal.get("target_price") or deal.get("offer_price")}


def _try_solve(f, target, lo, hi):
    try:
        return solve(f, target, lo, hi)
    except (ValueError, ZeroDivisionError):
        return None


def synergy_checks(p: dict, standalone_val: dict, syn: dict) -> dict:
    t = standalone_val["terminal"]
    total = syn["annual_cost"] * (1 + syn["revenue_pct_of_cost"])
    return {"lasting_cost": lasting_cost_share(roic_terminal=t.get("roic"), wacc_terminal=p["rates"]["wacc_terminal"],
                                               invested_capital=t.get("invested_capital"),
                                               annual_cost=syn["annual_cost"], tax_rate=p["tax"]),
            "synergies_to_sales": total / p["base"]["revenue"] if p["base"]["revenue"] else None}


def _result(name, detail, p, low, mid, high, notes, details, assumptions_used) -> ModelResult:
    return ModelResult(model=name, ticker=(detail.get("entity") or {}).get("ticker") or "", as_of=detail.get("as_of", ""),
                       value_per_share={"p10": low, "p50": mid, "p90": high, "mean": mid},
                       assumptions_used=assumptions_used, lineage={}, notes=notes, details=details)


class DCFSynergy:
    name = "dcf_synergy"
    needs_peers = False

    def __init__(self, dcf):
        self.dcf = dcf

    def run(self, detail: dict, assumptions: dict, peers: list[dict] | None = None) -> ModelResult:
        deal = deal_inputs(assumptions)
        syn = deal["synergies"]
        p = self.dcf.prepare(detail, assumptions)
        notes = list(p["warnings"])
        if p["solve_de"]:
            self.dcf.solve_debt_to_equity(p)
        base, years = p["base"], p["years"]
        lines = cost_lines(base)
        cost_base = sum(base.get(k) or 0 for k in lines)
        cost_pct = syn["cost_pct"]
        if cost_pct is None:
            if cost_base <= 0:
                raise DealError("the filings give no COGS, SG&A or other operating costs to cut, so cost synergies can't be applied here (set synergies.cost_pct to force a cut); Just Synergies still values them")
            cost_pct = syn["annual_cost"] / cost_base
            names = {"cogs": "COGS", "sga": "SG&A", "rnd": "R&D", "other_opex": "other operating costs"}
            notes.append(f"cost cut {cost_pct:.2%} = annual cost synergies over the base year's "
                         f"{' + '.join(names[k] for k in lines)}")

        def at(realized, growth_add, forever=syn["cost_forever"], cp=cost_pct):
            q = deepcopy(p)
            q["drivers"] = synergy_drivers(p["drivers"], base, years, revenue_growth_add=growth_add, cost_pct=cp,
                                           realized=realized, cost_forever=forever, years_to_full=syn["years_to_full"])
            q["drivers"]["revenue"]["g_terminal"] = p["drivers"]["revenue"]["g_terminal"]
            return self.dcf.value(q)

        base_val = at(syn["cost_realized"], syn["revenue_growth_add"])
        standalone_val = self.dcf.value(p)
        standalone = standalone_val["value_per_share"]
        checks = synergy_checks(p, standalone_val, syn)
        if deal["target_price"]:
            need = _try_solve(lambda c: at(syn["cost_realized"], syn["revenue_growth_add"], cp=c)["value_per_share"],
                              deal["target_price"], -0.5, 0.9)
            checks["needed_for_price"] = {"price": deal["target_price"], "revenue_growth_add": syn["revenue_growth_add"],
                                          "cost_pct": need,
                                          "annual_cost": need * cost_base if need is not None else None}
        low = at(syn["cost_realized"] - REALIZED_STEP, syn["revenue_growth_add"] - REVENUE_STEP)["value_per_share"]
        high = at(syn["cost_realized"] + REALIZED_STEP, syn["revenue_growth_add"] + REVENUE_STEP)["value_per_share"]
        realized_axis = [syn["cost_realized"] + REALIZED_STEP * k for k in range(-3, 4)]
        growth_axis = [syn["revenue_growth_add"] + REVENUE_STEP * k for k in range(-2, 3)]
        forever_axis = [max(syn["cost_forever"] + FOREVER_STEP * k, 0.0) for k in range(-2, 3)]
        grid = {"realized": realized_axis, "revenue_growth_add": growth_axis,
                "values": [[at(r, g)["value_per_share"] for g in growth_axis] for r in realized_axis]}
        grid_forever = {"realized": realized_axis, "cost_forever": forever_axis,
                        "values": [[at(r, syn["revenue_growth_add"], f)["value_per_share"] for f in forever_axis]
                                   for r in realized_axis]}
        proj = base_val["projection"]["years"]
        details = {
            "standalone_per_share": standalone, "synergy_per_share": base_val["value_per_share"] - standalone,
            "cost_pct": cost_pct, "cost_lines": list(lines), "synergies": syn,
            "rates": p["rates"], "terminal": base_val["terminal"], "terminal_value_share": base_val["terminal_value_share"],
            "bridge": {"enterprise_value": base_val["enterprise_value"], "net_debt": p["net_debt"],
                       "equity_value": base_val["equity_value"], "shares": p["shares"],
                       "value_per_share": base_val["value_per_share"]},
            "projection": [{"year": y["year"], "revenue": y["revenue"], "ebitda": y["ebitda"], "ebit": y["ebit"],
                            "fcf": y["free_cash_flow"]["fcf"], "pv": cf["pv"]}
                           for y, cf in zip(proj, base_val["cash_flows"])],
            "range": {"conservative": low, "expected": base_val["value_per_share"], "aggressive": high,
                      "steps": {"realized": REALIZED_STEP, "revenue_growth_add": REVENUE_STEP}},
            "sensitivity": grid, "sensitivity_forever": grid_forever, "checks": checks,
        }
        used = {"synergies": syn, "cost_of_capital": {"wacc": p["rates"]["wacc"], "wacc_terminal": p["rates"]["wacc_terminal"]},
                "forecast": {"tax_rate": p["tax"]}, "sources": p["sources"]}
        return _result(self.name, detail, p, low, base_val["value_per_share"], high, notes, details, used)


class JustSynergy:
    name = "just_synergy"
    needs_peers = False

    def __init__(self, dcf):
        self.dcf = dcf

    def run(self, detail: dict, assumptions: dict, peers: list[dict] | None = None) -> ModelResult:
        deal = deal_inputs(assumptions)
        syn = deal["synergies"]
        p = self.dcf.prepare(detail, assumptions)
        notes = list(p["warnings"])
        if p["solve_de"]:
            self.dcf.solve_debt_to_equity(p)
        price = deal["pre_announcement_price"] or p["price"]
        if not price:
            raise DealError("just synergies adds to the pre-announcement price: set deal.pre_announcement_price "
                            "(no market price on this run)")
        if not deal["pre_announcement_price"]:
            notes.append(f"pre-announcement price = the market price {price:,.2f}; set it under Deal once a bid is public")
        rev = p["drivers"]["revenue"]
        scaled_once = (assumptions.get("deal") or {}).get("synergies", {}).get("one_time_cost") is None

        def at(amount_k=1.0, forever=syn["cost_forever"], terminal_year=p["years"] - 1):
            return just_synergies(
                annual_cost=syn["annual_cost"] * amount_k, revenue_pct_of_cost=syn["revenue_pct_of_cost"],
                one_time_cost=syn["one_time_cost"] * (amount_k if scaled_once else 1.0), tax_rate=p["tax"],
                terminal_growth=rev["g_terminal"], wacc=p["rates"]["wacc"], wacc_terminal=p["rates"]["wacc_terminal"],
                growth=rev["g0"], years_to_full=syn["years_to_full"], terminal_year=terminal_year,
                cost_forever=forever, shares=p["shares"], pre_price=price)

        v = at()
        low, high = at(1 - AMOUNT_STEP)["value_per_share"], at(1 + AMOUNT_STEP)["value_per_share"]
        checks = synergy_checks(p, self.dcf.value(p), syn)
        if deal["target_price"]:
            k = _try_solve(lambda k: at(k)["value_per_share"], deal["target_price"], -5.0, 20.0)
            checks["needed_for_price"] = {"price": deal["target_price"],
                                          "annual_cost": syn["annual_cost"] * k if k is not None else None}
        amounts = [1 + AMOUNT_STEP * k for k in range(-3, 4)]
        forever_axis = [round(FOREVER_STEP * k, 4) for k in range(6)]
        t = p["years"] - 1
        term_axis = [y for y in range(t - 4, t + 7, 2) if y >= syn["years_to_full"]]
        details = {
            "pre_announcement_price": price, "synergy_per_share": v["per_share"], "max_premium": v["max_premium"],
            "total_value": v["total_value"], "terminal_value_share": v["terminal_value_share"], "years": v["years"],
            "synergies": syn, "rates": {"wacc": p["rates"]["wacc"], "wacc_terminal": p["rates"]["wacc_terminal"]},
            "growth": rev["g0"], "terminal_growth": rev["g_terminal"], "tax_rate": p["tax"], "shares": p["shares"],
            "range": {"conservative": low, "expected": v["value_per_share"], "aggressive": high,
                      "steps": {"annual_cost": AMOUNT_STEP}},
            "sensitivity": {"annual_cost": [syn["annual_cost"] * k for k in amounts], "cost_forever": forever_axis,
                            "values": [[at(k, f)["value_per_share"] for k in amounts] for f in forever_axis]},
            "sensitivity_terminal": {"annual_cost": [syn["annual_cost"] * k for k in amounts], "terminal_year": term_axis,
                                     "values": [[at(k, terminal_year=y)["value_per_share"] for k in amounts] for y in term_axis]},
            "checks": checks,
        }
        used = {"synergies": syn, "cost_of_capital": {"wacc": p["rates"]["wacc"], "wacc_terminal": p["rates"]["wacc_terminal"]},
                "forecast": {"tax_rate": p["tax"]}, "sources": p["sources"]}
        return _result(self.name, detail, p, low, v["value_per_share"], high, notes, details, used)
