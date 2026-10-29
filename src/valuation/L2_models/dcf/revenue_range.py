"""Calibrated revenue uncertainty for the DCF simulation.

Revenue paths are drawn from the model's own past misses instead of a +/-3% wobble in growth.
configs/public/calibration/revenue_errors.json holds, for each year out (1-5), quantiles of
ln(actual / forecast) divided by a company scale (revenue volatility + floor), measured on SEC
filings by the forecast-accuracy study in Courtizy/research. Tested out of sample, a range built
for 90% held 88-93% of outcomes; the triangular wobble's 80% range held about 14%.

One draw u ~ U(0, 1) per run moves every year by the same percentile of its own horizon's errors,
so a run that misses low in year 1 keeps missing low. Years after the last calibrated horizon
keep that horizon's level, growing at the base path's rates.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from statistics import pstdev

DEFAULT_PATH = Path(__file__).resolve().parents[4] / "configs" / "public" / "calibration" / "revenue_errors.json"
HISTORY_YEARS = 6


@lru_cache(maxsize=4)
def load_table(path: str | None = None) -> dict | None:
    p = Path(path) if path else DEFAULT_PATH
    if not p.exists():
        return None
    t = json.loads(p.read_text())
    t["_horizons"] = sorted(int(h) for h in t["quantiles"])
    return t


def company_scale(detail: dict, table: dict) -> tuple[float, float]:
    """(scale, volatility): pstdev of yearly log revenue growth over the last annual periods, plus the floor."""
    annual = ((detail or {}).get("views") or {}).get("annual") or []
    rev = [p["values"].get("revenue") for p in annual][-HISTORY_YEARS:]
    g = [math.log(b / a) for a, b in zip(rev, rev[1:]) if a and b and a > 0 and b > 0]
    vol = pstdev(g) if len(g) >= 2 else table["scale"]["default_vol"]
    return vol + table["scale"]["floor"], vol


def _interp(ps: list[float], qs: list[float], u: float) -> float:
    if u <= ps[0]:
        return qs[0]
    if u >= ps[-1]:
        return qs[-1]
    lo, hi = 0, len(ps) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if ps[mid] <= u:
            lo = mid
        else:
            hi = mid
    w = (u - ps[lo]) / (ps[hi] - ps[lo])
    return qs[lo] + w * (qs[hi] - qs[lo])


def multipliers(table: dict, u: float, scale: float, years: int) -> list[float]:
    """Revenue level multipliers for years 1..years at percentile u."""
    hs = table["_horizons"]
    m = {h: math.exp(_interp(table["p"], table["quantiles"][str(h)], u) * scale) for h in hs}
    return [m[min(t, hs[-1])] for t in range(1, years + 1)]


def band(table: dict, scale: float, levels=(0.8, 0.9)) -> dict:
    """The calibrated revenue range by year out, as multipliers of the base-case revenue."""
    out = {}
    for lvl in levels:
        lo, hi = (1 - lvl) / 2, 1 - (1 - lvl) / 2
        out[f"{round(lvl * 100)}"] = [{"year": h, "low": multipliers(table, lo, scale, h)[-1],
                                       "high": multipliers(table, hi, scale, h)[-1]} for h in table["_horizons"]]
    return out
