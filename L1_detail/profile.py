"""Company profile: four traits that decide how to value a company.

Valuation method follows the company's characteristics, not its sector label:

  stage             revenue CAGR and operating margin
                      declining     CAGR < 0 (checked first, so a shrinking loss-maker is declining)
                      high growth   CAGR > 15%, or growing with operating margin <= 0
                      mature grower CAGR 3-15% and profitable
                      mature        CAGR 0-3% and profitable
  predictability    free cash flow (CFO - capex) over the fiscal years
                      high          FCF > 0 in >= 80% of years and FCF-margin stdev <= 3 pts
                      low           FCF > 0 in <= 50% of years or stdev >= 8 pts
                      medium        otherwise
  asset intensity   capex / sales and net operating asset turnover
                      light         capex/sales < 3% and NOAT > 3x
                      heavy         capex/sales > 10% or NOAT < 1x
                      moderate      otherwise
  capital structure debt / EBITDA and the liabilities share of assets
                      financial     liabilities / assets >= 85% (debt is the business's raw material)
                      low           debt/EBITDA < 2x
                      high          debt/EBITDA > 4x or EBITDA <= 0 with debt
                      moderate      otherwise

Thresholds live in profile_rules.json; a pack can override them. Each trait
reports its measured values and the rule that produced the label, so the
choice of methods downstream can be explained.
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path

RULES_PATH = Path(__file__).with_name("profile_rules.json")


def load_rules(overrides: dict | None = None) -> dict:
    rules = json.loads(RULES_PATH.read_text())
    for k, v in (overrides or {}).items():
        rules[k] = {**rules[k], **v} if isinstance(v, dict) and isinstance(rules.get(k), dict) else v
    return rules


def _div(a, b):
    return None if a is None or b in (None, 0) else a / b


def _latest(detail: dict) -> tuple[dict | None, dict | None]:
    """Latest 12-month period and its analysis (TTM preferred)."""
    for view in ("ttm", "annual"):
        ps, an = detail["views"].get(view) or [], detail["analysis"].get(view) or []
        if ps:
            a = next((x for x in reversed(an) if x["end"] == ps[-1]["end"]), None)
            return ps[-1], a
    return None, None


def classify_stage(cagr, margin, rules: dict) -> tuple[str, str]:
    r = rules["stage"]
    if cagr is None or margin is None:
        return "unknown", "needs two fiscal years of revenue and an operating margin"
    if cagr < 0:
        return "declining", "revenue CAGR < 0"
    if cagr > r["high_growth_cagr"] or margin <= 0:
        return "high growth", f"CAGR > {r['high_growth_cagr']:.0%}, or growing and not yet profitable"
    if cagr >= r["mature_growth_cagr"]:
        return "mature grower", f"CAGR {r['mature_growth_cagr']:.0%}–{r['high_growth_cagr']:.0%} and profitable"
    return "mature", f"CAGR 0–{r['mature_growth_cagr']:.0%} and profitable"


def classify_predictability(fcf_margins: list[float], rules: dict):
    """Returns (label, rule, positive share, margin stdev)."""
    r = rules["predictability"]
    if len(fcf_margins) < 3:
        return "unknown", "needs three fiscal years of free cash flow", None, None
    pos = sum(m > 0 for m in fcf_margins) / len(fcf_margins)
    sd = statistics.pstdev(fcf_margins)
    if pos >= r["high_min_positive_share"] and sd <= r["high_max_fcf_margin_stdev"]:
        return "high", (f"FCF > 0 in ≥ {r['high_min_positive_share']:.0%} of years and margin stdev ≤ "
                        f"{r['high_max_fcf_margin_stdev'] * 100:.0f} pts"), pos, sd
    if pos <= r["low_max_positive_share"] or sd >= r["low_min_fcf_margin_stdev"]:
        return "low", (f"FCF > 0 in ≤ {r['low_max_positive_share']:.0%} of years or margin stdev ≥ "
                       f"{r['low_min_fcf_margin_stdev'] * 100:.0f} pts"), pos, sd
    return "medium", "between the high and low rules", pos, sd


def classify_intensity(capex_s, noat, rules: dict) -> tuple[str, str]:
    r = rules["asset_intensity"]
    if capex_s is None and noat is None:
        return "unknown", "needs capex or NOA turnover"
    if (capex_s is not None and capex_s > r["heavy_min_capex_to_sales"]) or (noat is not None and noat < r["heavy_max_noat"]):
        return "heavy", f"capex/sales > {r['heavy_min_capex_to_sales']:.0%} or NOAT < {r['heavy_max_noat']:.0f}x"
    if (capex_s is None or capex_s < r["light_max_capex_to_sales"]) and (noat is None or noat > r["light_min_noat"]):
        return "light", f"capex/sales < {r['light_max_capex_to_sales']:.0%} and NOAT > {r['light_min_noat']:.0f}x"
    return "moderate", "between the light and heavy rules"


def classify_capital(debt: float, ebitda, l_a, has_balance_sheet: bool, rules: dict) -> tuple[str, str]:
    r = rules["capital_structure"]
    d_ebitda = _div(debt, ebitda) if ebitda and ebitda > 0 else None
    if not has_balance_sheet:
        return "unknown", "needs a balance sheet"
    if l_a is not None and l_a >= r["financial_min_liabilities_to_assets"]:
        return "financial", f"liabilities ≥ {r['financial_min_liabilities_to_assets']:.0%} of assets"
    if ebitda is not None and ebitda <= 0 and debt > 0:
        return "high leverage", "debt with EBITDA ≤ 0"
    if d_ebitda is None and debt == 0:
        return "low leverage", "no debt"
    if d_ebitda is None:
        return "unknown", "needs debt and EBITDA"
    if d_ebitda < r["low_max_debt_to_ebitda"]:
        return "low leverage", f"debt/EBITDA < {r['low_max_debt_to_ebitda']:.0f}x"
    if d_ebitda > r["high_min_debt_to_ebitda"]:
        return "high leverage", f"debt/EBITDA > {r['high_min_debt_to_ebitda']:.0f}x"
    return "moderate leverage", f"debt/EBITDA {r['low_max_debt_to_ebitda']:.0f}–{r['high_min_debt_to_ebitda']:.0f}x"


def build_profile(detail: dict, rules: dict | None = None) -> dict:
    rules = rules or load_rules()
    annual = [p for p in detail["views"].get("annual", []) if p["values"].get("revenue")][-rules["history_years"]:]
    latest, an = _latest(detail)
    v = latest["values"] if latest else {}

    # ---- stage
    cagr = None
    if len(annual) >= 2 and annual[0]["values"]["revenue"] > 0:
        n = len(annual) - 1
        cagr = (annual[-1]["values"]["revenue"] / annual[0]["values"]["revenue"]) ** (1 / n) - 1
    margin = _div(v.get("operating_income_loss"), v.get("revenue"))
    stage, rule = classify_stage(cagr, margin, rules)

    # ---- predictability
    fcf_margins = [_div(p["values"].get("free_cash_flow"), p["values"]["revenue"]) for p in annual]
    fcf_margins = [m for m in fcf_margins if m is not None]
    pred, prule, pos, sd = classify_predictability(fcf_margins, rules)

    # ---- asset intensity
    capex_s = _div(v.get("capital_expenses"), v.get("revenue"))
    noat = None
    if an:
        ref = an["ratios"]["reformulated"]
        noat = (ref.get("avg") or {}).get("noat") or (ref.get("beg") or {}).get("noat")
    intensity, irule = classify_intensity(capex_s, noat, rules)

    # ---- capital structure
    debt = (v.get("short_term_debt") or 0) + (v.get("long_term_debt") or 0)
    ebitda = v.get("ebitda")
    d_ebitda = _div(debt, ebitda) if ebitda and ebitda > 0 else None
    liab = v.get("liabilities")
    if liab is None and v.get("liabilities_and_equity") is not None and v.get("all_equity_balance") is not None:
        liab = v["liabilities_and_equity"] - v["all_equity_balance"] - (v.get("minority_interest_balance") or 0)
    l_a = _div(liab, v.get("assets"))
    equity = None if liab is None or v.get("assets") is None else v["assets"] - liab
    nd_e = _div(debt - (v.get("cash_and_marketable_securities") or 0), equity)
    has_bs = not (v.get("assets") is None and v.get("long_term_debt") is None)
    cap, crule = classify_capital(debt, ebitda, l_a, has_bs, rules)

    years = len(annual)
    return {
        "as_of_period": latest["label"] if latest else None,
        "history_years": years,
        "traits": {
            "stage": {"label": stage, "rule": rule,
                      "measures": {"revenue_cagr": cagr, "operating_margin": margin}},
            "predictability": {"label": pred, "rule": prule,
                               "measures": {"fcf_positive_share": pos, "fcf_margin_stdev": sd,
                                            "years": len(fcf_margins)}},
            "asset_intensity": {"label": intensity, "rule": irule,
                                "measures": {"capex_to_sales": capex_s, "noa_turnover": noat}},
            "capital_structure": {"label": cap, "rule": crule,
                                  "measures": {"debt_to_ebitda": d_ebitda, "net_debt_to_equity": nd_e,
                                               "liabilities_to_assets": l_a}},
        },
        # flat numbers for comparing companies with each other
        "vector": {"revenue_cagr": cagr, "operating_margin": margin, "fcf_margin_stdev": sd,
                   "capex_to_sales": capex_s, "noa_turnover": noat, "debt_to_ebitda": d_ebitda,
                   "revenue": v.get("revenue"),
                   "rnoa": ((an or {}).get("ratios", {}).get("reformulated", {}).get("avg") or {}).get("rnoa")},
    }
