"""LBO: what a financial sponsor could pay (course Week 7 LBO model).

Starts from the standalone DCF's inputs (dcf.json or the default case), as the course model's
LBO sheet starts from the Inputs page, and reads the sponsor's assumptions from
assumptions["lbo"] (configs/public/assumptions/{TICKER}/lbo.json, or the deal page):

    {"sponsor_irr": 0.20,           # target return, 15-25% typical
     "hold_years": 5,
     "offer_premium": 0.30,         # over today's (or the pre-announcement) price
     "exit_multiple_change": 0.0,   # exit EV/EBITDA = today's multiple + this; set it to the
                                    # offer multiple's premium to sell at the price paid
     "coverage": 2.0,               # EBIT / interest the lenders allow
     "securable_assets": null,      # default: PP&E + receivables + inventories from the filings
     "pct_secured": 1.0, "sub_to_senior": 0.6,
     "senior_rate": null,           # default: the DCF's pre-tax cost of debt
     "rate_step": 0.03, "fees": 0.02,
     "steps": {"growth_add": 0.0,   # added to revenue growth every year
               "margin_add": 0.0,   # added to the EBITDA margin from year 1 (COGS share cut)
               "capex_add": 0.0,    # added to capex / sales
               "nwc_change": 0.0}}  # year-1 change in working capital, e.g. -0.25 releases a quarter

The math is in core.lbo. Range: max price at the sponsor IRR + 5 points (conservative), at the
IRR (expected) and at - 5 points (aggressive), the course's 15-25% band around 20%.
"""
from __future__ import annotations

from copy import deepcopy

from valuation._core.lbo import buyout
from valuation._core.projection import project
from valuation._core.synergy import growth_rates
from valuation.L2_models.base import ModelResult

DEFAULTS = {"sponsor_irr": 0.20, "hold_years": 5, "offer_premium": 0.30, "exit_multiple_change": 0.0, "coverage": 2.0,
            "securable_assets": None, "pct_secured": 1.0, "sub_to_senior": 0.6, "senior_rate": None,
            "rate_step": 0.03, "fees": 0.02}
STEPS = {"growth_add": 0.0, "margin_add": 0.0, "capex_add": 0.0, "nwc_change": 0.0}
IRR_STEP = 0.05


class LBOError(ValueError):
    is_warning = True     # no price (showcase mode) or no collateral: reported, not a failed run


def securable(v: dict) -> tuple[float | None, str]:
    parts = [v.get(k) for k in ("plant_property_equipment_net", "trade_receivables", "inventories")]
    if any(x is not None for x in parts):
        return sum(x or 0 for x in parts), "PP&E + receivables + inventories (the filings)"
    if v.get("assets") is not None:
        x = v["assets"] - sum(v.get(k) or 0 for k in ("goodwill", "intangible_assets", "cash_and_marketable_securities"))
        return x, "total assets less goodwill, intangibles and cash (the filings)"
    return None, ""


def _base_wcr(detail: dict) -> float:
    an = [a for a in (detail.get("analysis") or {}).get("annual") or [] if a["managerial_balance_sheet"]["wcr"] is not None]
    return an[-1]["managerial_balance_sheet"]["wcr"] if an else 0.0


class LBO:
    name = "lbo"
    needs_peers = False

    def __init__(self, dcf):
        self.dcf = dcf

    def plan(self, p: dict, steps: dict, hold: int, wcr0: float) -> list[dict]:
        d = deepcopy(p["drivers"])
        rates = growth_rates(p["drivers"]["revenue"], p["base"]["revenue"], hold)
        d["revenue"] = {"method": "growth", "rates": [g + steps["growth_add"] for g in rates]}
        d["cogs"]["value"] -= steps["margin_add"]
        d["capex"]["value"] += steps["capex_add"]
        proj = project(p["base"], d, hold)["years"]
        out = []
        for i, y in enumerate(proj):
            dn = y["free_cash_flow"]["change_in_nwc"] + (steps["nwc_change"] * wcr0 if i == 0 else 0.0)
            out.append({"year": i + 1, "revenue": y["revenue"], "ebitda": y["ebitda"], "ebit": y["ebit"],
                        "depreciation": y["ebitda"] - y["ebit"], "capex": y["capex"], "change_in_nwc": dn})
        return out

    def run(self, detail: dict, assumptions: dict, peers: list[dict] | None = None) -> ModelResult:
        p = self.dcf.prepare(detail, assumptions)
        if p["solve_de"]:
            self.dcf.solve_debt_to_equity(p)
        notes = list(p["warnings"])
        lbo = {**DEFAULTS, **{k: v for k, v in (assumptions.get("lbo") or {}).items() if v is not None and k != "steps"}}
        steps = {**STEPS, **{k: v for k, v in ((assumptions.get("lbo") or {}).get("steps") or {}).items() if v is not None}}
        deal = assumptions.get("deal") or {}
        price = deal.get("pre_announcement_price") or p["price"]
        if not price:
            raise LBOError("the LBO prices a buyout against today's price: no market price on this run")
        v = p["period"]["values"]
        sec, sec_basis = (lbo["securable_assets"], "assumptions") if lbo["securable_assets"] is not None else securable(v)
        if sec is None:
            raise LBOError("no securable assets in the filings (PP&E, receivables, inventories): set lbo.securable_assets")
        senior_rate = lbo["senior_rate"] if lbo["senior_rate"] is not None else p["rates"]["pre_tax_cost_of_debt"]
        hold = int(lbo["hold_years"])
        if hold < 1:
            raise LBOError("lbo.hold_years must be at least 1")
        plan = self.plan(p, steps, hold, _base_wcr(detail))
        ebit0 = p["base"]["revenue"] - sum(p["base"].get(k) or 0 for k in ("cogs", "sga", "rnd", "other_opex"))
        ebitda0 = ebit0 + (p["base"].get("depreciation") or 0)
        if ebitda0 <= 0:
            raise LBOError("base-year EBITDA is not positive: an LBO needs cash flow to carry debt")
        net_debt = p["debt"] - p["cash"]
        kw = dict(plan=plan, ebit0=ebit0, ebitda0=ebitda0, price=price, shares=p["shares"], net_debt=net_debt,
                  tax_rate=p["tax"], offer_premium=lbo["offer_premium"], securable_assets=sec,
                  pct_secured=lbo["pct_secured"], sub_to_senior=lbo["sub_to_senior"], senior_rate=senior_rate,
                  rate_step=lbo["rate_step"], fee_pct=lbo["fees"])
        at = lambda irr=lbo["sponsor_irr"], change=lbo["exit_multiple_change"], cov=lbo["coverage"]: buyout(  # noqa: E731
            **kw, sponsor_irr=irr, exit_multiple_change=change, coverage=cov)
        base = at()
        low = at(irr=lbo["sponsor_irr"] + IRR_STEP)["max_price"]
        high = at(irr=lbo["sponsor_irr"] - IRR_STEP)["max_price"]
        changes = [lbo["exit_multiple_change"] + k for k in (-2, -1, 0, 1, 2)]
        coverages = [1.5, 2.0, 2.5, 3.0]
        irrs = [0.15, 0.20, 0.25, 0.30]
        grids = {
            "irr_by_exit_and_coverage": {"exit_multiple_change": changes, "coverage": coverages,
                                         "values": [[at(change=c, cov=cv)["irr_at_offer"] for c in changes] for cv in coverages]},
            "max_price_by_irr_and_exit": {"sponsor_irr": irrs, "exit_multiple_change": changes,
                                          "values": [[at(irr=r, change=c)["max_price"] for c in changes] for r in irrs]},
        }
        short = [r["year"] for r in base["schedule"] if r["shortfall"] < 0]
        if short:
            notes.append(f"cash doesn't cover interest in year(s) {', '.join(map(str, short))}: the debt is too heavy for this plan")
        if base["debt"]["coverage"] and base["debt"]["coverage"] > lbo["coverage"] + 1e-9:
            notes.append(f"collateral caps the debt: coverage {base['debt']['coverage']:.2f}x stays above the "
                         f"{lbo['coverage']:.1f}x target (few securable assets)")
        notes.append(f"max price at a {lbo['sponsor_irr']:.0%} sponsor IRR; range at "
                     f"{lbo['sponsor_irr'] + IRR_STEP:.0%} / {lbo['sponsor_irr'] - IRR_STEP:.0%}")
        details = {**base, "plan": plan, "steps": steps, "inputs": {**lbo, "senior_rate": senior_rate,
                                                                    "securable_assets": sec, "securable_basis": sec_basis},
                   "standalone_per_share": self.dcf.value(p)["value_per_share"], "grids": grids,
                   "range": {"conservative": low, "expected": base["max_price"], "aggressive": high}}
        used = {"lbo": {**lbo, "steps": steps}, "forecast": {"tax_rate": p["tax"]}, "sources": p["sources"]}
        return ModelResult(model=self.name, ticker=(detail.get("entity") or {}).get("ticker") or "",
                           as_of=detail.get("as_of", ""),
                           value_per_share={"p10": low, "p50": base["max_price"], "p90": high, "mean": base["max_price"]},
                           assumptions_used=used, lineage={}, notes=notes, details=details)
