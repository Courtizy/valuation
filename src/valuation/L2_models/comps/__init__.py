"""Public comparables.

Inputs: company_detail.json for the target, configs/public/assumptions/{TICKER}/comps.json,
and (from the pipeline) company_detail.json for each peer that has SEC data.

Each peer
---------
    market value     = price x shares
    net debt         = long-term debt (incl. current portion and short-term debt) - cash & ST investments
    enterprise value = market value + net debt
    EV/Sales, EV/EBITDA, P/E   (a multiple is used only when positive)

Peer figures come from the peer's company detail (latest TTM, else latest
fiscal year). Any figure can be typed into comps.json instead, which is how a
peer without SEC data (foreign filer, private benchmark) is added.

Implied target value per share (per peer, per multiple)
-------------------------------------------------------
    EV/Sales:  (multiple x target sales  - target net debt) / target shares
    EV/EBITDA: (multiple x target EBITDA - target net debt) / target shares
    P/E:        multiple x target net income / target shares

Two peer sets
-------------
"peers" is the sector set: companies from the target's own industry (the traditional pick).
"closest" (optional) is the set closest on fundamentals, from anywhere in the sector screen.
Both are valued the same way; the sector set is this model's value, the closest set is
reported under details.closest and shown as its own football-field row.

How close each peer is: the underlying value method (course Pub_Comps rows)
--------------------------------------------------------------------------
EV/EBITDA is a DCF over current EBITDA, so a good comparable has a similar DCF profile, not
just the same industry or size. Each peer is rated against the target on the drivers:

    analysts' 5-year earnings growth   pre-terminal growth          green within 2 points
    past 5-year earnings growth        a check on that forecast     green within 5 points
    discount rate (WACC from beta)     the rate                     green within 0.5 points
    EBITDA margin                      the long run: high margins   green within 3 points
                                       drift back to the mean
    net debt / EV                      capital structure, so EV     green within 5 points
                                       and market-value multiples
                                       compare alike

A figure within the tolerance is green, within twice it yellow, beyond that red (the course's
stoplight). Closeness = (greens + half the yellows) / figures compared, 0 to 1. "match" in
comps.json changes a tolerance; a peer's or the target's figures can be typed there too
(growth_5y, growth_past_5y, discount_rate), which is how analysts' growth gets in when no
source has it. Size (sales against the target's) is shown, not rated: the course calls size
a poor proxy for performance.

Peers are weighted by closeness (the course: "weight public comparables based on how close
you can get"); "peer_weights": "equal" in comps.json weights them equally. Both values are
reported: details.blend (weighted, the model's value) and details.blend_equal. A peer with
fewer than 3 figures to compare is "unchecked" and gets a neutral 0.5; closeness below 0.5
flags a peer "weak".

A third set: the synthesized firm (course Case 3)
-------------------------------------------------
When no single peer looks like the target, build one: weights on the peers from both sets
(non-negative, summing to 1) chosen so the weighted peer matches the target's rated figures as
closely as possible, each gap measured in tolerances:
    minimize  sum_k ((sum_i w_i x_ik - x_target,k) / tolerance_k)^2
(projected gradient on the simplex). The weighted peer is then valued like the other sets and
reported under details.synthesized, with how close the blend gets on each figure.

EV/Sales against EV/EBITDA
--------------------------
EV/Sales = EV/EBITDA x EBITDA/Sales, so the two implied values differ only by the target's
margin against the peers': implied by sales / implied by EBITDA ~ peer margin / target margin.
EV/Sales is the better read when the target can reach the peers' margin on its own, or its
current margin isn't representative of its future (details.sales_vs_ebitda).

Range
-----
"auto" (default): Q1 / median / Q3 with four or more peers, else lowest /
median / highest, so one outlier peer can't set the range. "min_max" (the
course method): lowest / median / highest always. "quartiles": Q1 / median / Q3. Multiples are
blended with weights (equal by default). A multiple whose target metric is
not positive (EBITDA or earnings below zero) is dropped with a note.
"""
from __future__ import annotations

import math
import statistics

from valuation._core.figures import _latest_values, company_figures  # noqa: F401  (re-exported)
from valuation.L2_models.base import ModelResult

MULTIPLES = {
    "ev_sales": ("EV / Sales", "sales"),
    "ev_ebitda": ("EV / EBITDA", "ebitda"),
    "pe": ("P / E", "net_income"),
}
DEFAULT_MULTIPLES = ["ev_ebitda", "ev_sales"]
# (label, row key, kind, tolerance): "diff" = absolute difference, "ratio" = peer / target within [1/x, x]
MATCH = {
    "growth_5y": ("5-Yr Growth (Forecast)", "diff", 0.02),
    "growth_past_5y": ("5-Yr Growth (Past)", "diff", 0.05),
    "discount_rate": ("Discount Rate", "diff", 0.005),
    "ebitda_margin": ("EBITDA Margin", "diff", 0.03),
    "net_debt_to_ev": ("Net Debt / EV", "diff", 0.05),
}
WEAK_BELOW = 0.5    # closeness below this flags a peer
UNCHECKED_WEIGHT = 0.5


class CompsError(ValueError):
    pass


class NoPeerPrices(CompsError):
    """No peer has a price: expected in showcase mode (no market data) until prices are typed in comps.json.
    The runner reports it as a warning, not a failure."""
    is_warning = True


def peer_row(f: dict) -> dict:
    price, shares = f.get("price"), f.get("shares")
    mv = price * shares if price and shares else None
    net_debt = (f.get("debt") or 0) - (f.get("cash") or 0)
    ev = mv + net_debt if mv is not None else None

    def m(num, den):
        return num / den if num is not None and den and den > 0 and num / den > 0 else None

    return {
        **f, "market_value": mv, "net_debt": net_debt, "enterprise_value": ev,
        "net_debt_to_ev": max(net_debt, 0) / ev if ev else None,
        "ebitda_margin": m(f.get("ebitda"), f.get("sales")),
        "multiples": {"ev_sales": m(ev, f.get("sales")), "ev_ebitda": m(ev, f.get("ebitda")),
                      "pe": m(mv, f.get("net_income"))},
    }


def match(target: dict, peer: dict, rules: dict | None = None) -> dict:
    """Stoplight rating of a peer row against the target row on the MATCH figures, plus size."""
    rules = {**MATCH, **{k: (MATCH[k][0], MATCH[k][1], v) for k, v in (rules or {}).items() if k in MATCH}}
    out, n, score = {}, 0, 0.0
    for k, (_, _, tol) in rules.items():
        a, b = peer.get(k), target.get(k)
        if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
            out[k] = {"peer": a, "target": b, "light": None}
            continue
        gap = abs(a - b)
        light = "green" if gap <= tol + 1e-12 else "yellow" if gap <= 2 * tol + 1e-12 else "red"
        out[k] = {"peer": a, "target": b, "gap": a - b, "light": light}
        n += 1
        score += {"green": 1.0, "yellow": 0.5, "red": 0.0}[light]
    ps, ts = peer.get("sales"), target.get("sales")
    size = ps / ts if isinstance(ps, (int, float)) and isinstance(ts, (int, float)) and ts > 0 else None
    closeness = score / n if n else None
    flag = "unchecked" if n < 3 else "weak" if closeness < WEAK_BELOW else "ok"
    return {"figures": out, "size": size, "checked": n, "greens": sum(1 for f in out.values() if f["light"] == "green"),
            "closeness": closeness, "flag": flag,
            "weight": UNCHECKED_WEIGHT if flag == "unchecked" else closeness}


def _peer_average(target: dict, rows: list[dict], w: dict[str, float]) -> dict:
    """Simple and closeness-weighted peer averages of the rated figures, against the target
    (the course compares the comp average with the target)."""
    out = {}
    for k in list(MATCH) + ["ev_sales", "ev_ebitda"]:
        get = (lambda r: r["multiples"].get(k)) if k in ("ev_sales", "ev_ebitda") else (lambda r: r.get(k))  # noqa: E731
        xs = [(get(r), w.get(r["ticker"], 0.0)) for r in rows if isinstance(get(r), (int, float))]
        ws = sum(x for _, x in xs)
        out[k] = {"average": sum(v for v, _ in xs) / len(xs) if xs else None,
                  "weighted": sum(v * x for v, x in xs) / ws if ws else None,
                  "target": target["multiples"].get(k) if k in ("ev_sales", "ev_ebitda") else target.get(k)}
    return out


def implied_price(multiple_id: str, multiple: float, target: dict) -> float | None:
    if multiple is None or not target.get("shares"):
        return None
    metric = target.get(MULTIPLES[multiple_id][1])
    if metric is None or metric <= 0:
        return None
    net_debt = (target.get("debt") or 0) - (target.get("cash") or 0)
    if multiple_id == "pe":
        return multiple * metric / target["shares"]
    return (multiple * metric - net_debt) / target["shares"]


def _wquantile(pairs: list[tuple[float, float]], q: float) -> float:
    """Weighted quantile, interpolated between the weighted midpoints of the sorted values (equal
    weights give the same answer as the inclusive method of statistics.quantiles)."""
    pairs = sorted((v, w) for v, w in pairs if w > 0)
    if len(pairs) == 1:
        return pairs[0][0]
    total = sum(w for _, w in pairs)
    cum, pos = 0.0, []
    for v, w in pairs:
        pos.append((cum + w / 2 - pairs[0][1] / 2) / (total - pairs[0][1] / 2 - pairs[-1][1] / 2))
        cum += w
    t = q
    for i in range(1, len(pairs)):
        if t <= pos[i]:
            lo, hi = pos[i - 1], pos[i]
            f = (t - lo) / (hi - lo) if hi > lo else 0.0
            return pairs[i - 1][0] + f * (pairs[i][0] - pairs[i - 1][0])
    return pairs[-1][0]


def _wrange(pairs: list[tuple[float, float]], method: str) -> dict:
    """Range from (implied value, peer weight) pairs: lowest / weighted median / highest, or
    weighted Q1 / median / Q3. Peers with no weight are left out."""
    live = [(v, w) for v, w in pairs if w > 0] or [(v, 1.0) for v, _ in pairs]
    xs = [v for v, _ in live]
    if method == "quartiles" and len(xs) >= 4:
        return {"conservative": _wquantile(live, 0.25), "expected": _wquantile(live, 0.5), "aggressive": _wquantile(live, 0.75)}
    return {"conservative": min(xs), "expected": _wquantile(live, 0.5), "aggressive": max(xs)}


def _range(values: list[float], method: str) -> dict:
    xs = sorted(values)
    if method == "auto":
        method = "quartiles" if len(xs) >= 4 else "min_max"
    if method == "quartiles" and len(xs) >= 4:
        q1, med, q3 = statistics.quantiles(xs, n=4, method="inclusive")
        return {"conservative": q1, "expected": med, "aggressive": q3}
    return {"conservative": xs[0], "expected": statistics.median(xs), "aggressive": xs[-1]}


def _avg_positive(xs):
    xs = [x for x in xs if x is not None and x > 0]
    return sum(xs) / len(xs) if xs else None


def _value_set(live: list[dict], target: dict, wanted: list[str], weights: dict, method: str,
               notes: list[str], peer_w: dict[str, float] | None = None) -> tuple[dict, dict, dict, str]:
    """Implied values per multiple and the blended range for one peer set, with each peer
    weighted by peer_w (closeness), and the same with equal weights under "equal"."""
    if method == "auto":
        method = "quartiles" if len(live) >= 4 else "min_max"
    peer_w = peer_w or {r["ticker"]: 1.0 for r in live}
    per_multiple = {}
    for mid in wanted:
        if mid not in MULTIPLES:
            raise CompsError(f"unknown multiple {mid!r}; choose from {sorted(MULTIPLES)}")
        metric = target.get(MULTIPLES[mid][1])
        if metric is None or metric <= 0:
            notes.append(f"{MULTIPLES[mid][0]} dropped: target {MULTIPLES[mid][1].replace('_', ' ')} is not positive")
            continue
        implied = {r["ticker"]: implied_price(mid, r["multiples"][mid], target) for r in live}
        vals = [x for x in implied.values() if x is not None]
        if not vals:
            notes.append(f"{MULTIPLES[mid][0]} dropped: no peer has a positive multiple")
            continue
        avg_mult = _avg_positive([r["multiples"][mid] for r in live])
        mults = [(r["multiples"][mid], peer_w.get(r["ticker"], 0.0)) for r in live if r["multiples"][mid]]
        wsum = sum(w for _, w in mults)
        per_multiple[mid] = {
            "label": MULTIPLES[mid][0], "weight": weights.get(mid, 0.0),
            "peer_average": avg_mult, "peer_median": statistics.median([m for m, _ in mults]),
            "peer_weighted_average": sum(m * w for m, w in mults) / wsum if wsum else avg_mult,
            "implied_at_average": implied_price(mid, avg_mult, target),
            "implied": implied,
            **_wrange([(implied[t], peer_w.get(t, 0.0)) for t, x in implied.items() if x is not None], method),
            "equal": _range(vals, method),
        }
    used = {k: v for k, v in per_multiple.items() if v["weight"] > 0}
    if not used:
        raise CompsError("no usable multiple: check the target's sales, EBITDA and earnings")
    total = sum(v["weight"] for v in used.values())
    keys = ("conservative", "expected", "aggressive")
    blend = {k: sum(v["weight"] * v[k] for v in used.values()) / total for k in keys}
    blend_equal = {k: sum(v["weight"] * v["equal"][k] for v in used.values()) / total for k in keys}
    return per_multiple, blend, blend_equal, method


def _simplex(v: list[float]) -> list[float]:
    """Euclidean projection onto {w >= 0, sum w = 1}."""
    u = sorted(v, reverse=True)
    css, rho, theta = 0.0, 0, 0.0
    for i, x in enumerate(u, 1):
        css += x
        t = (css - 1) / i
        if x - t > 0:
            rho, theta = i, t
    return [max(x - theta, 0.0) for x in v]


def synthesize(target: dict, rows: list[dict], rules: dict | None = None, iterations: int = 4000) -> dict | None:
    """Peer weights whose weighted figures come closest to the target's (in tolerances)."""
    tol = {k: (rules or {}).get(k, t) for k, (_, _, t) in MATCH.items()}
    keys = [k for k in MATCH if isinstance(target.get(k), (int, float))
            and sum(isinstance(r.get(k), (int, float)) for r in rows) >= 3]
    pool = [r for r in rows if all(isinstance(r.get(k), (int, float)) for k in keys)]
    if len(keys) < 2 or len(pool) < 2:
        return None
    X = [[r[k] / tol[k] for k in keys] for r in pool]
    t = [target[k] / tol[k] for k in keys]
    n = len(pool)
    lip = 2 * sum(x * x for row in X for x in row) or 1.0        # a safe step: 1 / Lipschitz bound
    w = [1 / n] * n
    for _ in range(iterations):
        fit = [sum(w[i] * X[i][j] for i in range(n)) for j in range(len(keys))]
        res = [f - y for f, y in zip(fit, t)]
        grad = [2 * sum(X[i][j] * res[j] for j in range(len(keys))) for i in range(n)]
        w = _simplex([wi - g / lip for wi, g in zip(w, grad)])
    w = [x if x > 1e-4 else 0.0 for x in w]
    s = sum(w)
    w = [x / s for x in w]
    figs = {}
    for j, k in enumerate(keys):
        blend = sum(w[i] * pool[i][k] for i in range(n))
        gap = blend - target[k]
        figs[k] = {"blend": blend, "target": target[k], "gap": gap,
                   "light": "green" if abs(gap) <= tol[k] + 1e-12 else "yellow" if abs(gap) <= 2 * tol[k] + 1e-12 else "red"}
    return {"weights": {pool[i]["ticker"]: w[i] for i in range(n)}, "figures": figs,
            "fit": math.sqrt(sum(((f["gap"]) / tol[k]) ** 2 for k, f in figs.items()) / len(figs))}


def sales_vs_ebitda(target: dict, rows: list[dict], w: dict[str, float]) -> dict | None:
    pts = [(r["ebitda_margin"], w.get(r["ticker"], 0.0)) for r in rows if r.get("ebitda_margin")]
    ws = sum(x for _, x in pts)
    tm = target.get("ebitda_margin")
    if not ws or not tm:
        return None
    pm = sum(m * x for m, x in pts) / ws
    ratio = pm / tm
    if abs(ratio - 1) <= 0.1:
        note = "margins are similar, so EV/Sales and EV/EBITDA should agree"
    elif ratio > 1:
        note = ("peers earn a higher margin, so EV/Sales gives the higher value; it fits only if the target can "
                "reach the peers' margin on its own")
    else:
        note = ("peers earn a lower margin, so EV/Sales gives the lower value; EV/EBITDA fits better unless the "
                "target's margin is temporarily high")
    return {"target_margin": tm, "peer_margin": pm, "ratio": ratio, "note": note}


class Comps:
    name = "comps"
    needs_peers = True

    def run(self, detail: dict, assumptions: dict, peers: list[dict] | None = None) -> ModelResult:
        if not detail or "views" not in detail:
            raise CompsError("comps needs company_detail.json")
        a = assumptions or {}
        entries = a.get("peers") or []
        if not entries:
            raise CompsError("comps.json lists no peers: add tickers (with prices) under \"peers\"")
        by_ticker = {((d or {}).get("entity") or {}).get("ticker", "").upper(): d for d in (peers or []) if d}
        notes: list[str] = []

        target_manual = dict(a.get("target") or {})
        target = company_figures(detail, target_manual)
        if target.get("price") is None:
            target["price"] = (a.get("market") or {}).get("price")
        if not target.get("shares"):
            raise CompsError("no target share count: set target.shares in comps.json")

        target_row = peer_row({**target, "ticker": (detail.get("entity") or {}).get("ticker", ""), "name": "target"})
        rules = a.get("match")

        # figures typed for a ticker in either list apply wherever it appears
        typed = {}
        for e in (a.get("peers") or []) + (a.get("closest") or []):
            if isinstance(e, dict) and e.get("ticker"):
                typed.setdefault(e["ticker"].upper(), {}).update({k: v for k, v in e.items() if k != "ticker"})

        def rows_for(entries):
            rows = []
            for e in entries:
                e = {"ticker": e} if isinstance(e, str) else dict(e)
                t = e.get("ticker", "").upper()
                e = {**typed.get(t, {}), **e}
                f = company_figures(by_ticker.get(t), e)
                f["ticker"] = t
                f.setdefault("name", ((by_ticker.get(t) or {}).get("entity") or {}).get("name") or t)
                f["source"] = "sec" if t in by_ticker else "manual"
                row = peer_row(f)
                row["match"] = match(target_row, row, rules)
                if row["enterprise_value"] is None:
                    notes.append(f"{t}: no price or share count, left out (set price in comps.json)")
                    row["excluded"] = True
                rows.append(row)
            return rows

        rows = rows_for(entries)
        live = [r for r in rows if not r.get("excluded")]
        if not live:
            raise NoPeerPrices("no peer has a price: type peer prices in comps.json (the public site's showcase mode "
                               "fetches no market prices), or run with market data")
        weak = [r["ticker"] for r in live if r["match"]["flag"] == "weak"]
        if weak:
            notes.append(f"weak match (closeness below {WEAK_BELOW:.0%} on growth, discount rate, margin and leverage): {', '.join(weak)}")
        equal = a.get("peer_weights") == "equal"
        weigh = lambda rows: {r["ticker"]: 1.0 if equal else r["match"]["weight"] for r in rows}  # noqa: E731

        wanted = a.get("multiples") or DEFAULT_MULTIPLES
        weights = a.get("weights") or {m: 1.0 for m in wanted}
        method = a.get("range", "auto")
        per_multiple, blend, blend_equal, method = _value_set(live, target, wanted, weights, method, notes, weigh(live))
        used = {k: v for k, v in per_multiple.items() if v["weight"] > 0}
        total = sum(v["weight"] for v in used.values())

        closest = None
        if a.get("closest"):
            c_rows = rows_for(a["closest"])
            c_live = [r for r in c_rows if not r.get("excluded")]
            if c_live:
                c_notes: list[str] = []
                try:
                    c_mult, c_blend, c_equal, c_method = _value_set(c_live, target, wanted, weights, a.get("range", "auto"),
                                                                    c_notes, weigh(c_live))
                    closest = {"peers": c_rows, "multiples": c_mult, "blend": c_blend, "blend_equal": c_equal,
                               "range_method": c_method, "peer_average": _peer_average(target_row, c_live, weigh(c_live)),
                               "sales_vs_ebitda": sales_vs_ebitda(target_row, c_live, weigh(c_live)),
                               "notes": c_notes, "source": (a.get("sources") or {}).get("closest")}
                except CompsError as e:
                    notes.append(f"closest-match set not valued: {e}")

        synthesized = None
        if a.get("synthesized", True):
            pool = {r["ticker"]: r for r in live + ([r for r in closest["peers"] if not r.get("excluded")] if closest else [])}
            syn = synthesize(target_row, list(pool.values()), rules)
            if syn:
                s_live = [pool[t] for t, x in syn["weights"].items() if x > 0]
                s_notes: list[str] = []
                try:
                    s_mult, s_blend, s_equal, s_method = _value_set(s_live, target, wanted, weights, "min_max", s_notes,
                                                                    {t: syn["weights"][t] for t in (r["ticker"] for r in s_live)})
                    # the synthesized firm is one firm: its value is the weighted multiple applied to the target
                    s_point = {mid: implied_price(mid, sum(syn["weights"][r["ticker"]] * r["multiples"][mid]
                                                           for r in s_live if r["multiples"][mid])
                                                  / (sum(syn["weights"][r["ticker"]] for r in s_live if r["multiples"][mid]) or 1),
                                                  target) for mid in s_mult}
                    synthesized = {**syn, "peers": [pool[t] for t in syn["weights"]], "multiples": s_mult,
                                   "blend": s_blend, "blend_equal": s_equal, "range_method": s_method,
                                   "implied_at_blend": s_point, "notes": s_notes}
                except CompsError as e:
                    notes.append(f"synthesized firm not valued: {e}")

        return ModelResult(
            model=self.name,
            ticker=(detail.get("entity") or {}).get("ticker") or "",
            as_of=detail.get("as_of", ""),
            value_per_share={"p10": blend["conservative"], "p50": blend["expected"],
                             "p90": blend["aggressive"], "mean": blend["expected"]},
            assumptions_used={
                "multiples": {"used": sorted(used), "weights": {k: v["weight"] / total for k, v in used.items()},
                              "range": method},
                "peers": [r["ticker"] for r in live],
                "sources": a.get("sources", {}),
                **({"closest": [r["ticker"] for r in closest["peers"] if not r.get("excluded")]} if closest else {}),
            },
            lineage={},
            notes=notes + [f"range = {'lowest / median / highest' if method == 'min_max' else 'Q1 / median / Q3'} implied price across peers"],
            details={"target": target_row, "peers": rows, "multiples": per_multiple, "blend": blend, "blend_equal": blend_equal,
                     "peer_weights": "equal" if equal else "closeness", "peer_average": _peer_average(target_row, live, weigh(live)),
                     "market_price": target.get("price"), "range_method": method, "closest": closest,
                     "synthesized": synthesized,
                     "sales_vs_ebitda": sales_vs_ebitda(target_row, live, weigh(live)),
                     "match_rules": {k: {"label": lbl, "tolerance": (a.get("match") or {}).get(k, tol)}
                                     for k, (lbl, kind, tol) in MATCH.items()}},
        )


MODEL = Comps()
