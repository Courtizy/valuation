"""Trend case: a projection calculated from the company's own history, no inputs.

Shown next to the reported statements so current and projected growth sit
side by side. It isn't a valuation; the DCF model's projection (from its
assumptions) replaces it on the site when a DCF has run.

Base period: the last reported fiscal year, so Year 1 is the fiscal year in
progress (FY+1E) and estimate columns line up with filings. Ten years.

Drivers, all measured from the filings:
  revenue        g0 = revenue CAGR over up to five fiscal years (bounded to
                 -20%..+40%), fading linearly to 3% by Year 10
                 (fade_years = horizon - 1, since the engine's fade lands in year n+1)
  cost lines     base-period ratios to sales; "other operating" is the
                 residual so base EBIT equals reported operating income
  D&A, capex     base-period ratios to sales
  working cap.   dNWC/dSales from the managerial WCR history (0.20 if not measurable)
  tax            base-period effective rate (0.21 if not measurable)
  interest       base-period amount held flat
The math is core.projection, the same engine the DCF uses.
"""
from __future__ import annotations

from core.projection import base_from_detail, project, statement_row

HORIZON = 10
TERMINAL_GROWTH = 0.03
GROWTH_BOUNDS = (-0.20, 0.40)
DEFAULT_NWC = 0.20


def _nwc_ratio(detail: dict) -> tuple[float, str]:
    annual = {p["end"]: p["values"].get("revenue") for p in detail["views"].get("annual", [])}
    an = [a for a in detail["analysis"].get("annual", [])
          if a["managerial_balance_sheet"]["wcr"] is not None and annual.get(a["end"])][-4:]
    if len(an) >= 2:
        d_s = annual[an[-1]["end"]] - annual[an[0]["end"]]
        if d_s > 0:
            k = (an[-1]["managerial_balance_sheet"]["wcr"] - an[0]["managerial_balance_sheet"]["wcr"]) / d_s
            if -1 <= k <= 1:
                return k, "history"
    return DEFAULT_NWC, "default"


def trend_case(detail: dict, horizon: int = HORIZON) -> dict | None:
    views = detail["views"]
    base_p = (views.get("annual") or views.get("ttm") or [None])[-1]
    if not base_p or not base_p["values"].get("revenue"):
        return None
    v = base_p["values"]
    b = base_from_detail(v)
    rev = b["revenue"]
    b["depreciation"] = (b["depreciation"] or 0) + (b["amortization"] or 0)
    b["amortization"] = 0.0
    if v.get("operating_income_loss") is not None:
        b["other_opex"] = rev - sum(b.get(k) or 0 for k in ("cogs", "sga", "rnd")) - v["operating_income_loss"]

    cagr = ((detail.get("profile") or {}).get("traits", {}).get("stage", {}).get("measures", {}) or {}).get("revenue_cagr")
    g0 = min(max(cagr if cagr is not None else 0.05, GROWTH_BOUNDS[0]), GROWTH_BOUNDS[1])
    etr = v.get("effective_tax_rate")
    tax = etr if etr is not None and 0 <= etr <= 0.5 else 0.21
    nwc, nwc_src = _nwc_ratio(detail)
    ratio = lambda k: (b.get(k) or 0) / rev  # noqa: E731
    drivers = {
        "revenue": {"method": "fade", "g0": g0, "g_terminal": TERMINAL_GROWTH, "fade_years": max(horizon - 1, 1)},
        **{k: {"method": "pct_of_sales", "value": ratio(k)} for k in ("cogs", "sga", "rnd", "other_opex")},
        "depreciation": {"method": "pct_of_sales", "value": ratio("depreciation")},
        "amortization": {"method": "values", "values": [0]},
        "capex": {"method": "pct_of_sales", "value": (b.get("capex") or b["depreciation"]) / rev},
        "nwc": {"method": "incremental", "ratio": nwc},
        "interest": {"method": "same_as_base"},
        "tax_rate": tax,
        "costs_include_da": True,
        "plug": "cash",
    }
    years = project(b, drivers, horizon)["years"]
    return {
        "case": "trend",
        "base_period": {"label": base_p["label"], "end": base_p["end"], "fiscal_year": base_p.get("fiscal_year"),
                        "kind": "fiscal" if base_p.get("fiscal_period") == "FY" else "ltm"},
        "assumptions": {"revenue_growth_start": g0, "terminal_growth": TERMINAL_GROWTH, "fade_years": max(horizon - 1, 1),
                        "tax_rate": tax, "nwc_to_sales_change": nwc, "nwc_source": nwc_src,
                        "capex_pct_revenue": drivers["capex"]["value"]},
        "years": [statement_row(y) for y in years],
    }
