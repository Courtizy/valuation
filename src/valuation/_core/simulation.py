"""Monte Carlo utilities: seeded generators, input distributions, summaries.

Same interface as the Decision Models kit's numpy version (rng, sample, summarize), in pure
Python so the package stays dependency-free and Pyodide-friendly. Every draw goes through
rng(seed), so the same inputs and seed give the same numbers in the private app, the CI
export and the browser.

Distribution specs: a plain number (fixed), {"dist": "triangular", "low", "mode", "high"},
{"dist": "normal", "mean", "sd"}, {"dist": "uniform", "low", "high"}.
"""
from __future__ import annotations

import math
import random
from typing import Any, Mapping


def rng(seed: int) -> random.Random:
    return random.Random(seed)


def sample(spec: Mapping[str, Any] | float, n: int, gen: random.Random) -> list[float]:
    if isinstance(spec, (int, float)):
        return [float(spec)] * n
    kind = spec.get("dist")
    if kind == "triangular":
        lo, mode, hi = spec["low"], spec["mode"], spec["high"]
        return [gen.triangular(lo, hi, mode) for _ in range(n)]
    if kind == "normal":
        return [gen.gauss(spec["mean"], spec["sd"]) for _ in range(n)]
    if kind == "uniform":
        return [gen.uniform(spec["low"], spec["high"]) for _ in range(n)]
    raise ValueError(f"unknown distribution: {kind!r}")


def percentile(sorted_values: list[float], p: float) -> float:
    """Linear interpolation between closest ranks (numpy's default)."""
    if not sorted_values:
        return math.nan
    k = (len(sorted_values) - 1) * p / 100
    lo, hi = math.floor(k), math.ceil(k)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo)


def summarize(values: list[float], percentiles=(5, 10, 25, 50, 75, 90, 95)) -> dict[str, float]:
    xs = sorted(values)
    out = {"mean": sum(xs) / len(xs) if xs else math.nan}
    out.update({f"p{p}": percentile(xs, p) for p in percentiles})
    return out


def histogram(values: list[float], bins: int = 30, trim: float = 0.5) -> dict[str, list]:
    """Counts and edges over the p{trim}–p{100-trim} span (a few extreme runs would
    otherwise flatten the chart); counts outside it are reported separately."""
    xs = sorted(values)
    lo, hi = percentile(xs, trim), percentile(xs, 100 - trim)
    if not xs or hi <= lo:
        return {"counts": [len(xs)], "edges": [lo, hi], "below": 0, "above": 0}
    width = (hi - lo) / bins
    counts = [0] * bins
    below = above = 0
    for x in xs:
        if x < lo:
            below += 1
        elif x > hi:
            above += 1
        else:
            counts[min(int((x - lo) / width), bins - 1)] += 1
    return {"counts": counts, "edges": [lo + i * width for i in range(bins + 1)], "below": below, "above": above}
