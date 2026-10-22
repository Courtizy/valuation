"""Small statistics: one-variable OLS and the Foster seasonal model (MBA 733).

OLS, y = a + b x, with the usual t statistics and R-squared.

Foster model for quarterly series (sales or earnings):
    Q_t = Q_{t-4} + delta + phi (Q_{t-1} - Q_{t-5})
The seasonal difference D_t = Q_t - Q_{t-4} follows D_t = delta + phi D_{t-1}:
delta is the trend, phi how long a shock to growth lasts. Fitted by OLS on the
seasonal differences, then rolled forward one quarter at a time.
"""
from __future__ import annotations

import math

MIN_QUARTERS = 10      # needs at least five seasonal differences to fit two parameters


def ols(xs: list[float], ys: list[float]) -> dict | None:
    pts = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    n = len(pts)
    if n < 3:
        return None
    mx = sum(x for x, _ in pts) / n
    my = sum(y for _, y in pts) / n
    sxx = sum((x - mx) ** 2 for x, _ in pts)
    if not sxx:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in pts)
    b = sxy / sxx
    a = my - b * mx
    sse = sum((y - a - b * x) ** 2 for x, y in pts)
    sst = sum((y - my) ** 2 for _, y in pts)
    s2 = sse / (n - 2)
    se_b = math.sqrt(s2 / sxx)
    se_a = math.sqrt(s2 * (1 / n + mx * mx / sxx))
    return {"n": n, "intercept": a, "slope": b, "t_intercept": a / se_a if se_a else None,
            "t_slope": b / se_b if se_b else None, "r_squared": 1 - sse / sst if sst else None}


def foster(quarters: list[float], ahead: int = 4) -> dict | None:
    """Fit on a quarterly series (oldest first) and forecast `ahead` quarters."""
    q: list[float] = []
    for v in reversed(quarters):          # the latest unbroken run: a gap would shift the seasons
        if v is None:
            break
        q.insert(0, float(v))
    if len(q) < MIN_QUARTERS:
        return None
    d = [q[t] - q[t - 4] for t in range(4, len(q))]
    fit = ols(d[:-1], d[1:])
    if not fit:
        if len(set(d)) != 1:
            return None
        # growth exactly steady: every seasonal difference is the same, so phi = 0 and delta is that difference
        fit = {"intercept": d[0], "slope": 0.0, "t_intercept": None, "t_slope": None, "r_squared": None}
    delta, phi = fit["intercept"], fit["slope"]
    series, diffs, out = list(q), list(d), []
    for _ in range(ahead):
        nd = delta + phi * diffs[-1]
        nxt = series[-4] + nd
        out.append(nxt)
        series.append(nxt)
        diffs.append(nd)
    return {"delta": delta, "phi": phi, "t_delta": fit["t_intercept"], "t_phi": fit["t_slope"],
            "r_squared": fit["r_squared"], "quarters_used": len(q), "forecast": out,
            "next_four_quarters": sum(out[:4]) if len(out) >= 4 else None}
