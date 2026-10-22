"""Prior deals: reading a deal list and the per-deal figures transaction comps use.

A deal list is a CSV or tab-separated paste (copied straight from Excel), one deal per row,
with a header row. Headers are matched loosely (case, spacing and line breaks ignored), so
an SDC Platinum export works as is. Figures in one row must share a unit (SDC uses $ millions);
only ratios cross between deals and the target.

Per deal
--------
    premium (1 week)   = offer price / price 1 week before announcement - 1
    premium (4 weeks)  = offer price / price 4 weeks before - 1
    premium            = the larger of the two, a negative one set to 10% and anything
                         above 100% capped at 100% (the course's "best premium paid")
    transaction EV     = the EV the source reports at the offer price, else
                         offer price x shares + net debt
    pre-announcement EV = price 1 week before x shares + net debt
    multiples          = EV / sales, EV / EBITDA, each kept only when positive
    synergies / sales  = announced annual synergies over the target's sales (when the list has them)
"""
from __future__ import annotations

import csv
import io
import math
import re

# field: header prefixes, normalized (lower case, single spaces); the first match wins
ALIASES = {
    "year": ["year announced", "year"],
    "date": ["date announced", "announced", "date"],
    "target": ["target name", "target company", "target"],
    "acquirer": ["acquiror name", "acquirer name", "acquiror", "acquirer", "buyer"],
    "ev": ["enterprise value evaluated at offer", "transaction enterprise value", "transaction ev", "enterprise value", "ev"],
    "sales": ["target net sales", "net sales", "sales", "revenue"],
    "ebitda": ["target ebitda", "ebitda"],
    "net_income": ["net income"],
    "offer_price": ["price per share", "offer price per share", "offer price", "offer"],
    "price_1w": ["target share price 1 week prior", "price 1 week", "price 1 wk", "pre-announcement price", "pre price"],
    "price_4w": ["target share price 4 weeks prior", "price 4 weeks", "price 4 wk"],
    "sic": ["target primary sic", "target sic", "sic"],
    "nation": ["target nation", "nation", "country"],
    "net_debt": ["net debt"],
    "shares": ["shares out", "shares outstanding", "shares"],
    "premium": ["premium"],
    "synergies": ["announced synergies", "expected synergies", "total synergies", "synergies"],
    "best": ["best", "use", "selected"],
}
NUMERIC = {"year", "ev", "sales", "ebitda", "net_income", "offer_price", "price_1w", "price_4w", "net_debt", "shares", "premium",
           "synergies"}


class DealListError(ValueError):
    pass


def _norm(h: str) -> str:
    return re.sub(r"\s+", " ", str(h or "").replace("\n", " ")).strip().lower()


def _num(x):
    if x is None:
        return None
    s = str(x).strip().replace(",", "").replace("$", "")
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").rstrip("%")
    if s in ("", "-", "–", "na", "n/a", "nm"):
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def map_headers(headers: list[str]) -> dict[str, int]:
    """field -> column index, longest alias first so "net income" can't take "net debt"."""
    norm = [_norm(h) for h in headers]
    out: dict[str, int] = {}
    taken: set[int] = set()
    pairs = sorted(((a, f) for f, al in ALIASES.items() for a in al), key=lambda p: -len(p[0]))
    for alias, field in pairs:
        if field in out:
            continue
        for i, h in enumerate(norm):
            if i not in taken and h.startswith(alias):
                out[field] = i
                taken.add(i)
                break
    return out


def parse_deal_list(text: str) -> list[dict]:
    text = (text or "").strip()
    if not text:
        raise DealListError("the deal list is empty")
    delim = "\t" if "\t" in text[:5000] else ","          # a paste from Excel is tab-separated
    rows = list(csv.reader(io.StringIO(text), delimiter=delim))
    cols = map_headers(rows[0])
    missing = [f for f in ("target", "offer_price") if f not in cols]
    if missing:
        raise DealListError(f"the deal list needs columns for {', '.join(missing)} (found: {', '.join(rows[0][:12])})")
    deals = []
    for r in rows[1:]:
        if not any(c.strip() for c in r):
            continue
        get = lambda f: r[cols[f]] if f in cols and cols[f] < len(r) else None  # noqa: E731
        d = {f: (_num(get(f)) if f in NUMERIC else (get(f) or "").strip() or None) for f in cols}
        if d.get("premium") is not None and abs(d["premium"]) > 3:      # typed as a percent
            d["premium"] /= 100
        if d.get("year") is None and d.get("date"):
            m = re.search(r"(19|20)\d\d", d["date"])
            d["year"] = float(m.group(0)) if m else None
        d["best"] = str(d.get("best") or "").strip().lower() in ("1", "y", "yes", "true", "x", "best")
        if d.get("target"):
            deals.append(d)
    if not deals:
        raise DealListError("no deals with a target name in the list")
    return deals


def _pos(num, den):
    return num / den if num is not None and den and den > 0 and num / den > 0 else None


def deal_figures(d: dict) -> dict:
    offer, p1, p4 = d.get("offer_price"), d.get("price_1w"), d.get("price_4w")
    shares, nd = d.get("shares"), d.get("net_debt")
    prem_1w = offer / p1 - 1 if offer and p1 else None
    prem_4w = offer / p4 - 1 if offer and p4 else None
    best = d.get("premium")
    if best is None:
        cands = [p for p in (prem_1w, prem_4w) if p is not None]
        best = max(cands) if cands else None
    if best is not None:
        best = 0.1 if best < 0 else min(best, 1.0)
    built_ev = offer * shares + (nd or 0) if offer and shares else None
    tx_ev = d.get("ev") if d.get("ev") is not None else built_ev
    pre_ev = p1 * shares + (nd or 0) if p1 and shares else None
    s, e = d.get("sales"), d.get("ebitda")
    return {**d, "premium_1w": prem_1w, "premium_4w": prem_4w, "premium": best,
            "transaction_ev": tx_ev, "transaction_ev_built": built_ev, "pre_ev": pre_ev,
            "tx_ev_sales": _pos(tx_ev, s), "tx_ev_ebitda": _pos(tx_ev, e),
            "built_ev_sales": _pos(built_ev, s), "built_ev_ebitda": _pos(built_ev, e),
            "pre_ev_sales": _pos(pre_ev, s), "pre_ev_ebitda": _pos(pre_ev, e),
            "ebitda_margin": e / s if e is not None and s else None,
            "synergies_to_sales": d["synergies"] / s if d.get("synergies") is not None and s else None}


# ------------------------------------------------------------ Excel's statistics

def percentile(xs: list[float], k: float) -> float:
    """Excel PERCENTILE / PERCENTILE.INC: linear between order statistics, k in [0, 1]."""
    xs = sorted(xs)
    k = min(max(k, 0.0), 1.0)
    h = k * (len(xs) - 1)
    lo = math.floor(h)
    return xs[lo] + (h - lo) * (xs[min(lo + 1, len(xs) - 1)] - xs[lo])


def percentrank_exc(xs: list[float], x: float, significance: int = 3) -> float | None:
    """Excel PERCENTRANK.EXC: x's rank as (position) / (n + 1), interpolated, truncated to
    `significance` digits. None when x is outside the data (Excel's #N/A)."""
    xs = sorted(xs)
    n = len(xs)
    if not n or x < xs[0] or x > xs[-1]:
        return None
    for i in range(n):
        if xs[i] == x:
            pos = i + 1
            break
        if i + 1 < n and xs[i] < x < xs[i + 1]:
            pos = i + 1 + (x - xs[i]) / (xs[i + 1] - xs[i])
            break
    r = pos / (n + 1)
    f = 10 ** significance
    return math.floor(r * f + 1e-9) / f


def stats(xs: list[float]) -> dict | None:
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    return {"n": len(xs), "mean": sum(xs) / len(xs), "min": xs[0], "q1": percentile(xs, 0.25),
            "median": percentile(xs, 0.5), "q3": percentile(xs, 0.75), "max": xs[-1]}
