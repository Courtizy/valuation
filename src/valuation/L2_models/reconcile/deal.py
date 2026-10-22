"""Deal summary: the course's standalone range and offer price range.

Each method gives conservative / best guess / aggressive values per share:
DCF from its course scenarios, the synergy models from their sensitivity
ranges, comps and others from p10 / p50 / p90, and the 52-week trading range
as low / current / high. Weights for methods that have no value are spread
over the rest (the course's "blank value" column).

    standalone range  = weighted conservative, best guess and aggressive values
    offer range       conservative = weighted conservative values
                      aggressive   = weighted aggressive values, except the synergy
                                     methods enter at their best guess: paying for
                                     synergies beyond what you expect gives the
                                     whole gain away
                      best guess   = conservative + (aggressive - conservative)
                                     x relative power of the target (0 = the buyer
                                     holds all the bargaining power, 1 = the target)

Premiums are against the pre-announcement price; "share of synergies" is how
much of the gap between that price and the top of the offer range a price
hands to the target's shareholders.
"""
from __future__ import annotations

# the course template's default weights; the closest-match comps set is shown unweighted (set a weight to use it)
STANDALONE = {"comps": 0.2, "comps_closest": 0.0, "precedents_pre_sales": 0.1, "precedents_pre_ebitda": 0.1, "dcf": 0.4, "trading_range": 0.2}
OFFER = {"precedents_sales": 0.02, "precedents_ebitda": 0.02, "precedents_premium": 0.30, "dcf_synergy": 0.33,
         "just_synergy": 0.33, "lbo": 0.0}
NAMES = {"comps": "Public Comps: Sector Peers", "comps_closest": "Public Comps: Closest Match", "precedents_pre_sales": "Prior Deals: Pre-announcement EV/Sales",
         "precedents_pre_ebitda": "Prior Deals: Pre-announcement EV/EBITDA", "dcf": "DCF (Standalone)",
         "trading_range": "52-Week Low, Current, High", "precedents_sales": "Prior Deals: Transaction EV/Sales",
         "precedents_ebitda": "Prior Deals: Transaction EV/EBITDA", "precedents_premium": "Prior Deals: Premium Paid",
         "dcf_synergy": "Whole Firm DCF with Synergies", "just_synergy": "Pre-announcement Price + Just Synergies",
         "lbo": "LBO"}
SYNERGY_METHODS = ("dcf_synergy", "just_synergy")


def _triple(result: dict | None) -> tuple[float, float, float] | None:
    if not result:
        return None
    d = result.get("details") or {}
    s = d.get("scenarios") or d.get("range")
    if s and s.get("conservative") is not None:
        return s["conservative"], s["expected"], s["aggressive"]
    v = result.get("value_per_share") or {}
    return (v["p10"], v["p50"], v["p90"]) if v.get("p50") is not None else None


def _rows(weights: dict, values: dict) -> list[dict]:
    live = {m: w for m, w in weights.items() if values.get(m) and w > 0}
    total = sum(live.values())
    return [{"method": m, "name": NAMES.get(m, m), "weight": w, "values": values.get(m),
             "adjusted_weight": live.get(m, 0.0) / total if total else 0.0} for m, w in weights.items()]


def _premium(v, base):
    return v / base - 1 if v is not None and base else None


def deal_summary(by_model: dict, detail: dict | None, deal: dict) -> dict:
    market = (detail or {}).get("market") or {}
    pre = deal.get("pre_announcement_price") or market.get("price")
    q = market.get("quote") or {}
    values = {m: _triple(by_model.get(m)) for m in set(STANDALONE) | set(OFFER) | set(by_model)}
    rows = (((by_model.get("precedents") or {}).get("details") or {}).get("summary_rows") or {})
    values.update({m: tuple(v) for m, v in rows.items() if v and all(x is not None for x in v)})     # transaction comps fill five rows
    if pre and q.get("wk52_low") and q.get("wk52_high"):
        values["trading_range"] = (q["wk52_low"], pre, q["wk52_high"])
    w = deal.get("weights") or {}
    st_rows = _rows({**STANDALONE, **(w.get("standalone") or {})}, values)
    of_rows = _rows({**OFFER, **(w.get("offer") or {})}, values)
    notes = [f"{r['name']}: no value yet, so its weight went to the others"
             for r in st_rows + of_rows if r["weight"] > 0 and not r["values"]]

    st = None
    if any(r["adjusted_weight"] for r in st_rows):
        st = {k: sum(r["adjusted_weight"] * r["values"][i] for r in st_rows if r["adjusted_weight"])
              for i, k in enumerate(("conservative", "best_guess", "aggressive"))}
    power = deal.get("relative_power", 0.5)
    offer = None
    live = [r for r in of_rows if r["adjusted_weight"]]
    if live:
        low = sum(r["adjusted_weight"] * r["values"][0] for r in live)
        high = sum(r["adjusted_weight"] * r["values"][1 if r["method"] in SYNERGY_METHODS else 2] for r in live)
        offer = {"conservative": low, "best_guess": low + (high - low) * power, "aggressive": high}
    gap = (offer["aggressive"] - pre) if offer and pre else None
    share = lambda v: (v - pre) / gap if gap and v is not None else None  # noqa: E731
    actual = deal.get("offer_price")
    return {
        "pre_announcement_price": pre,
        "pre_announcement_source": "deal inputs" if deal.get("pre_announcement_price") else "market price",
        "relative_power": power,
        "standalone": {"methods": st_rows, "range": st},
        "offer": {"methods": of_rows, "range": offer,
                  "premium": {k: _premium(v, pre) for k, v in offer.items()} if offer else None,
                  "synergy_share": {k: share(v) for k, v in offer.items()} if offer else None},
        "offer_price": actual,
        "offer_price_premium": _premium(actual, pre),
        "offer_price_synergy_share": share(actual),
        "notes": notes,
    }
