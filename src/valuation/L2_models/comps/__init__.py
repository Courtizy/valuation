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

Range
-----
"auto" (default): Q1 / median / Q3 with four or more peers, else lowest /
median / highest, so one outlier peer can't set the range. "min_max" (the
course method): lowest / median / highest always. "quartiles": Q1 / median / Q3. Multiples are
blended with weights (equal by default). A multiple whose target metric is
not positive (EBITDA or earnings below zero) is dropped with a note.
"""
from __future__ import annotations

import statistics

from valuation.L2_models.base import ModelResult

MULTIPLES = {
    "ev_sales": ("EV / Sales", "sales"),
    "ev_ebitda": ("EV / EBITDA", "ebitda"),
    "pe": ("P / E", "net_income"),
}
DEFAULT_MULTIPLES = ["ev_ebitda", "ev_sales"]


class CompsError(ValueError):
    pass


class NoPeerPrices(CompsError):
    """No peer has a price: expected in showcase mode (no market data) until prices are typed in comps.json.
    The runner reports it as a warning, not a failure."""
    is_warning = True


def _latest_values(detail: dict | None) -> dict:
    if not detail:
        return {}
    views = detail.get("views") or {}
    period = (views.get("ttm") or views.get("annual") or [None])[-1]
    return dict(period["values"]) if period else {}


def company_figures(detail: dict | None, manual: dict | None = None) -> dict:
    """Sales, EBITDA, net income, debt, cash, shares from detail; manual entries override."""
    v = _latest_values(detail)
    f = {
        "sales": v.get("revenue"),
        "ebitda": v.get("ebitda"),
        "net_income": v.get("net_income", v.get("profit_loss")),
        "debt": ((v.get("short_term_debt") or 0) + (v.get("long_term_debt") or 0))
        if v.get("long_term_debt") is not None or v.get("short_term_debt") is not None else None,
        "cash": v.get("cash_and_marketable_securities"),
        # newest filed count (10-K/10-Q cover page, carried in company detail), else the statements'
        "shares": ((detail or {}).get("shares_outstanding") or v.get("shares_year_end")
                   or v.get("shares_fully_diluted_average")),
        "revenue_growth": ((detail or {}).get("profile") or {}).get("vector", {}).get("revenue_cagr"),
    }
    mkt = (detail or {}).get("market") or {}
    if mkt.get("price") is not None:            # market data from L1; a price typed in comps.json still wins
        f["price"], f["price_source"] = mkt["price"], f"market data ({mkt.get('source')}, {mkt.get('price_date')})"
        if mkt.get("shares_outstanding"):
            f["shares"] = mkt["shares_outstanding"]
    for k, val in (manual or {}).items():
        if k in f or k in ("price", "beta", "name"):
            f[k] = val
            if k == "price":
                f["price_source"] = "comps.json"
    return f


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

        rows = []
        for e in entries:
            e = {"ticker": e} if isinstance(e, str) else dict(e)
            t = e.get("ticker", "").upper()
            f = company_figures(by_ticker.get(t), e)
            f["ticker"] = t
            f.setdefault("name", ((by_ticker.get(t) or {}).get("entity") or {}).get("name") or t)
            f["source"] = "sec" if t in by_ticker else "manual"
            row = peer_row(f)
            if row["enterprise_value"] is None:
                notes.append(f"{t}: no price or share count, left out (set price in comps.json)")
                row["excluded"] = True
            rows.append(row)
        live = [r for r in rows if not r.get("excluded")]
        if not live:
            raise NoPeerPrices("no peer has a price: type peer prices in comps.json (the public site's showcase mode "
                               "fetches no market prices), or run with market data")

        wanted = a.get("multiples") or DEFAULT_MULTIPLES
        weights = a.get("weights") or {m: 1.0 for m in wanted}
        method = a.get("range", "auto")
        if method == "auto":
            method = "quartiles" if len(live) >= 4 else "min_max"
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
            per_multiple[mid] = {
                "label": MULTIPLES[mid][0], "weight": weights.get(mid, 0.0),
                "peer_average": avg_mult, "peer_median": statistics.median([r["multiples"][mid] for r in live if r["multiples"][mid]]),
                "implied_at_average": implied_price(mid, avg_mult, target),
                "implied": implied, **_range(vals, method),
            }
        used = {k: v for k, v in per_multiple.items() if v["weight"] > 0}
        if not used:
            raise CompsError("no usable multiple: check the target's sales, EBITDA and earnings")
        total = sum(v["weight"] for v in used.values())
        blend = {k: sum(v["weight"] * v[k] for v in used.values()) / total
                 for k in ("conservative", "expected", "aggressive")}
        target_row = peer_row({**target, "ticker": (detail.get("entity") or {}).get("ticker", ""), "name": "target"})

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
            },
            lineage={},
            notes=notes + [f"range = {'lowest / median / highest' if method == 'min_max' else 'Q1 / median / Q3'} implied price across peers"],
            details={"target": target_row, "peers": rows, "multiples": per_multiple, "blend": blend,
                     "market_price": target.get("price"), "range_method": method},
        )


MODEL = Comps()
