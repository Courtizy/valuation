"""One similarity ranking for the site: Similar Companies and the comps peer picker.

Closeness = root-mean-square z-score distance over six figures every company has
on the same basis, whether it comes from full company detail or a sector screen:

    revenue CAGR, operating margin, FCF-margin stdev, capex / sales,
    debt / EBITDA, log10 revenue

z-scores use the mean and spread of the pool being ranked, so "close" is
relative to the alternatives on offer. score = 1 / (1 + distance), scaled by
0.8 + 0.05 x traits shared (0 to 4): shared traits break near-ties without
overriding the numbers.
"""
from __future__ import annotations

import math

KEYS = ("revenue_cagr", "operating_margin", "fcf_margin_stdev", "capex_to_sales", "debt_to_ebitda", "log_revenue")
TRAITS = ("stage", "predictability", "asset_intensity", "capital_structure")


def _value(c: dict, key: str):
    if key == "log_revenue":
        r = c.get("revenue")
        return math.log10(r) if r and r > 0 else None
    v = c.get(key)
    return v if isinstance(v, (int, float)) and math.isfinite(v) else None


def rank(target: dict, pool: list[dict], limit: int | None = None) -> list[dict]:
    """[{ticker, score, traits_shared}] for every other company in pool, closest first.

    Each company is {ticker, traits: {...}, revenue, revenue_cagr, ...}.
    """
    stats = {}
    for k in KEYS:
        xs = [x for x in (_value(c, k) for c in pool + [target]) if x is not None]
        m = sum(xs) / len(xs) if xs else 0.0
        sd = math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs)) if xs else 0.0
        stats[k] = (m, sd or 1.0)
    out = []
    for c in pool:
        if c.get("ticker") == target.get("ticker"):
            continue
        d2 = n = 0
        for k in KEYS:
            a, b = _value(c, k), _value(target, k)
            if a is not None and b is not None:
                d2 += ((a - b) / stats[k][1]) ** 2
                n += 1
        shared = sum(1 for t in TRAITS if (c.get("traits") or {}).get(t) and
                     (c.get("traits") or {}).get(t) == (target.get("traits") or {}).get(t))
        score = (1 / (1 + math.sqrt(d2 / n))) * (0.8 + 0.05 * shared) if n else None
        out.append({"ticker": c.get("ticker"), "score": score, "traits_shared": shared})
    out.sort(key=lambda r: -(r["score"] if r["score"] is not None else -1))
    return out[:limit] if limit else out


def from_card(card: dict) -> dict:
    """A published company card in the ranking's shape."""
    v = card.get("vector") or {}
    return {"ticker": card["ticker"], "traits": card.get("traits") or {}, "revenue": v.get("revenue"),
            **{k: v.get(k) for k in KEYS if k != "log_revenue"}}
