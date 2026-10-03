"""Which methods to trust, from the company profile (triangulation).

Every valuation uses a primary method and at least one cross-check; anything
else is shown for reference with zero weight. The choice follows the
company's characteristics (L1 profile), not its sector label:

  financial balance sheet      comps primary (P/B, P/E). A WACC DCF treats debt
                               as financing, but for a lender debt is the
                               operating raw material, so DCF is reference only.
  high growth or low           comps primary 60%, DCF cross-check 40%: earnings
  cash-flow predictability     and FCF aren't stable enough to anchor on alone.
  declining                    DCF 50% (short horizon), comps 50%; asset or
                               liquidation value is the floor to check.
  mature, high predictability  DCF primary 60%, comps cross-check 40%.
  otherwise (medium)           DCF 50%, comps 50%.

Context changes the question being asked:
  standalone  value of the company as it is (default). Precedent transactions
              and LBO are reference only: precedents include a control premium,
              and an LBO prices what a financial buyer could pay.
  acquisition offer price, as in the course summary: just synergies 33%,
              DCF with synergies 33%, precedent transactions (premium paid)
              34%; LBO reference.

Weights for methods that didn't run are dropped and the rest renormalized
(the course summary does the same with blank rows). An overrides file can
replace the weights; roles then follow the new weights.
"""
from __future__ import annotations

METHOD_NAMES = {"dcf": "DCF (Standalone)", "dcf_synergy": "DCF with Synergies", "just_synergy": "Just Synergies",
                "comps": "Public Comps", "precedents": "Precedent Transactions", "lbo": "LBO", "ipo": "IPO"}


def _plan(profile: dict | None, context: str) -> tuple[list[tuple[str, str, float, str]], str]:
    """[(model, role, weight, reason)], summary sentence."""
    if context == "acquisition":
        return ([
            ("just_synergy", "primary", 0.33, "value of the synergies on top of the pre-announcement price"),
            ("dcf_synergy", "primary", 0.33, "whole-firm DCF including synergies"),
            ("precedents", "cross-check", 0.34, "premiums and multiples paid in comparable deals"),
            ("lbo", "reference", 0.0, "what a financial buyer could pay: a floor for a strategic bid"),
            ("dcf", "reference", 0.0, "standalone value, the starting point of the offer"),
        ], "Acquisition context: synergy-based values and prior deals set the offer range.")

    t = (profile or {}).get("traits", {})
    stage = t.get("stage", {}).get("label", "unknown")
    pred = t.get("predictability", {}).get("label", "unknown")
    cap = t.get("capital_structure", {}).get("label", "unknown")
    intensity = t.get("asset_intensity", {}).get("label", "unknown")
    ref = [("precedents", "reference", 0.0, "includes a control premium; not a standalone value"),
           ("lbo", "reference", 0.0, "what a financial buyer could pay given the cash flows and debt capacity")]

    if cap == "financial":
        return ([("comps", "primary", 1.0, "for a financial firm debt is operating, so book-value and earnings multiples fit"),
                 ("dcf", "reference", 0.0, "a WACC/FCF DCF misreads a lender's balance sheet")] + ref,
                "Financial-style balance sheet: value on equity multiples; the firm DCF is reference only.")
    if stage == "high growth" or pred == "low":
        why = "high growth" if stage == "high growth" else "low cash-flow predictability"
        return ([("comps", "primary", 0.6, f"{why}: current multiples (EV/Sales, EV/EBITDA) anchor better than distant cash flows"),
                 ("dcf", "cross-check", 0.4, "tests whether the multiple is supported by plausible long-run cash flows")] + ref,
                f"{why.capitalize()} → comps primary, DCF cross-check.")
    if stage == "declining":
        return ([("dcf", "primary", 0.5, "short-horizon cash flows capture the run-off"),
                 ("comps", "cross-check", 0.5, "where similar companies trade")] + ref,
                "Declining revenue → DCF and comps equally; check asset or liquidation value as a floor.")
    if pred == "high" and stage in ("mature", "mature grower"):
        lev = " with low leverage" if cap == "low leverage" else ""
        return ([("dcf", "primary", 0.6, "predictable, positive free cash flow makes cash flows the most direct measure"),
                 ("comps", "cross-check", 0.4, f"{stage}{lev}: enterprise multiples compare cleanly")] + ref,
                f"{stage.capitalize()}, predictable cash flows ({intensity} assets, {cap}) → DCF primary, comps cross-check.")
    return ([("dcf", "primary", 0.5, "cash flows are reasonably steady"),
             ("comps", "cross-check", 0.5, "medium predictability: give the market check equal say")] + ref,
            "Medium predictability → DCF and comps weighted equally.")


def method_plan(profile: dict | None, available: list[str], overrides: dict | None = None) -> dict:
    overrides = overrides or {}
    context = overrides.get("context", "standalone")
    plan, summary = _plan(profile, context)
    rows = {m: {"model": m, "name": METHOD_NAMES.get(m, m), "role": role, "default_weight": w, "reason": why}
            for m, role, w, why in plan}
    for m in available:                       # anything that ran but isn't in the plan
        rows.setdefault(m, {"model": m, "name": METHOD_NAMES.get(m, m), "role": "reference",
                            "default_weight": 0.0, "reason": "not part of the plan for this profile"})
    raw = dict(overrides.get("weights") or {m: r["default_weight"] for m, r in rows.items()})
    for m in raw:
        rows.setdefault(m, {"model": m, "name": METHOD_NAMES.get(m, m), "role": "reference",
                            "default_weight": 0.0, "reason": "added by override"})
    live = {m: w for m, w in raw.items() if m in available and w > 0}
    total = sum(live.values())
    notes = []
    for m, r in rows.items():
        r["ran"] = m in available
        r["weight"] = live.get(m, 0.0) / total if total else 0.0
        if raw.get(m, 0) > 0 and m not in available:
            notes.append(f"{r['name']} has weight but didn't run; its weight was spread over the others")
    if overrides.get("weights"):
        ranked = sorted((r for r in rows.values() if r["weight"] > 0), key=lambda r: -r["weight"])
        for i, r in enumerate(rows.values()):
            r["role"] = "reference"
        for i, r in enumerate(ranked):
            r["role"] = "primary" if i == 0 else "cross-check"
        summary += " Weights set by override."
    order = {"primary": 0, "cross-check": 1, "reference": 2}
    methods = sorted(rows.values(), key=lambda r: (order[r["role"]], -r["weight"], r["model"]))
    if not total:
        notes.append("no weighted method has run yet")
    return {"context": context, "summary": summary, "methods": methods, "notes": notes}
