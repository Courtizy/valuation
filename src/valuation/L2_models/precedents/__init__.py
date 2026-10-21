"""Precedent transactions (transaction comps), as in the course's Best TC and Central Tendency sheets.

Inputs: company_detail.json for the target, configs/public/assumptions/{TICKER}/precedents.json
(on the site, the deal list uploaded on the device) and the deal (deal.json: pre-announcement price):

    {"csv": "<the deal list as CSV or a tab-separated paste>",   # or "deals": [{...}, ...]
     "best": ["Target A", ...],          # the most comparable deals; default: those marked in a
                                         # "best" column, else the first five
     "choice": 0,                        # 0: standalone rows from best deals, offer rows from all
                                         #    deals (the course default); 1: best only; 2: all only
     "central": {"spread": [0.1, 0.1], "percentile": {"ev_sales": null, "ev_ebitda": null}},
     "target": {...}}                    # figures that override company detail (sales, ebitda, ...)

Per deal figures are in core.deals. The target's implied value per share from a multiple is
(multiple x target metric - target net debt) / target shares; from a premium it is the
pre-announcement price x (1 + premium).

Best deals: conservative / expected / aggressive = lowest / average / highest implied value,
with the deal EV rebuilt from offer price x shares + net debt.

All deals (central tendency): premium at the 1st quartile / median / 3rd quartile; multiples at
a percentile and +/- the spread around it. The percentile defaults to where the target's own
pre-announcement multiple ranks among the deals' (Excel PERCENTRANK.EXC), so a target that
trades rich gets a rich multiple. Transaction multiples use the EV the data source reports.

Rows for the deal summary (details.summary_rows):
    precedents_pre_sales / precedents_pre_ebitda    standalone: pre-announcement multiples
    precedents_sales / precedents_ebitda / precedents_premium    offer: transaction multiples, premium
value_per_share is the premium row.
"""
from __future__ import annotations

from valuation._core.deals import DealListError, deal_figures, parse_deal_list, percentile, percentrank_exc, stats
from valuation._core.figures import company_figures
from valuation.L2_models.base import ModelResult

BEST_MAX = 5
SPREAD = (0.1, 0.1)
ROWS = {"tx_sales": ("tx_ev_sales", "sales"), "tx_ebitda": ("tx_ev_ebitda", "ebitda"),
        "pre_sales": ("pre_ev_sales", "sales"), "pre_ebitda": ("pre_ev_ebitda", "ebitda")}


def target_figures(detail: dict, assumptions: dict) -> dict:
    f = company_figures(detail, assumptions.get("target"))
    deal = assumptions.get("deal") or {}
    if deal.get("pre_announcement_price"):
        f["price"], f["price_source"] = deal["pre_announcement_price"], "deal inputs (pre-announcement)"
    f["net_debt"] = (f.get("debt") or 0) - (f.get("cash") or 0)
    ev = f["price"] * f["shares"] + f["net_debt"] if f.get("price") and f.get("shares") else None
    f["ev_sales"] = ev / f["sales"] if ev and f.get("sales") else None
    f["ev_ebitda"] = ev / f["ebitda"] if ev and f.get("ebitda") and f["ebitda"] > 0 else None
    return f


def implied(mult: float | None, metric: float | None, t: dict) -> float | None:
    if mult is None or not metric or metric <= 0 or not t.get("shares"):
        return None
    return (mult * metric - t["net_debt"]) / t["shares"]


def best_rows(deals: list[dict], t: dict) -> dict:
    """Each best deal's implied values (EV rebuilt from offer x shares + net debt), and the range."""
    per = []
    for d in deals:
        per.append({"target": d["target"],
                    "tx_sales": implied(d["built_ev_sales"], t.get("sales"), t),
                    "tx_ebitda": implied(d["built_ev_ebitda"], t.get("ebitda"), t),
                    "premium": t["price"] * (1 + d["premium"]) if t.get("price") and d.get("premium") is not None else None,
                    "pre_sales": implied(d["pre_ev_sales"], t.get("sales"), t),
                    "pre_ebitda": implied(d["pre_ev_ebitda"], t.get("ebitda"), t)})
    ranges = {}
    for k in ("tx_sales", "tx_ebitda", "premium", "pre_sales", "pre_ebitda"):
        xs = [p[k] for p in per if p[k] is not None]
        ranges[k] = [min(xs), sum(xs) / len(xs), max(xs)] if xs else None
    return {"deals": per, "ranges": ranges}


def central_rows(deals: list[dict], t: dict, opts: dict) -> dict:
    spread = opts.get("spread") or SPREAD
    fixed = opts.get("percentile") or {}
    notes, pct = [], {}
    for m, own in (("ev_sales", t.get("ev_sales")), ("ev_ebitda", t.get("ev_ebitda"))):
        xs = [d[f"pre_{m}"] for d in deals if d.get(f"pre_{m}") is not None]
        k = fixed.get(m)
        if k is None:
            k = percentrank_exc(xs, own) if own is not None and xs else None
            if k is None:
                k = 0.5
                notes.append(f"the target's {m.replace('_', '/').upper()} is outside the deals' range (or unknown): median used")
        pct[m] = [k - spread[0], k, k + spread[1]]
    ranges = {}
    for row, (field, metric) in ROWS.items():
        xs = [d[field] for d in deals if d.get(field) is not None]
        ks = pct["ev_sales" if metric == "sales" else "ev_ebitda"]
        vals = [implied(percentile(xs, k), t.get(metric), t) for k in ks] if xs else []
        ranges[row] = vals if vals and all(v is not None for v in vals) else None
    prem = stats([d["premium"] for d in deals])
    ranges["premium"] = ([t["price"] * (1 + prem[q]) for q in ("q1", "median", "q3")]
                         if prem and t.get("price") else None)
    table = {k: stats([d.get(k) for d in deals]) for k in
             ("premium", "tx_ev_sales", "tx_ev_ebitda", "pre_ev_sales", "pre_ev_ebitda", "ebitda_margin")}
    return {"percentiles": pct, "ranges": ranges, "stats": table, "notes": notes}


def transaction_comps(deals_in: list[dict], t: dict, best: list[str] | None = None, choice: int = 0,
                      central: dict | None = None) -> dict:
    deals = [deal_figures(d) for d in deals_in]
    names = set(best or [])
    chosen = ([d for d in deals if d["target"] in names] if names
              else [d for d in deals if d.get("best")] or deals[:BEST_MAX])
    b = best_rows(chosen, t)
    c = central_rows(deals, t, central or {})
    src_st, src_of = {0: (b, c), 1: (b, b), 2: (c, c)}.get(int(choice), (b, c))
    rows = {"precedents_pre_sales": src_st["ranges"]["pre_sales"], "precedents_pre_ebitda": src_st["ranges"]["pre_ebitda"],
            "precedents_sales": src_of["ranges"]["tx_sales"], "precedents_ebitda": src_of["ranges"]["tx_ebitda"],
            "precedents_premium": src_of["ranges"]["premium"]}
    return {"deals": deals, "best": [d["target"] for d in chosen], "best_rows": b, "central": c,
            "choice": int(choice), "summary_rows": rows}


class Precedents:
    name = "precedents"
    needs_peers = False

    def run(self, detail: dict, assumptions: dict, peers: list[dict] | None = None) -> ModelResult:
        a = assumptions or {}
        deals_in = a.get("deals") or (parse_deal_list(a["csv"]) if a.get("csv") else None)
        if not deals_in:
            raise DealListError("no deal list: upload one under Deal → Prior Deals")
        t = target_figures(detail, a)
        if not t.get("price"):
            raise DealListError("transaction comps need the target's pre-announcement price: set it under Deal")
        out = transaction_comps(deals_in, t, a.get("best"), a.get("choice", 0), a.get("central"))
        prem = out["summary_rows"]["precedents_premium"]
        notes = list(out["central"]["notes"])
        if not prem:
            raise DealListError("no deal has both an offer price and a pre-announcement price, so no premium")
        notes.append(f"{len(out['deals'])} deals, {len(out['best'])} chosen as most comparable")
        target = {k: t.get(k) for k in ("price", "price_source", "shares", "net_debt", "sales", "ebitda", "ev_sales", "ev_ebitda")}
        return ModelResult(
            model=self.name, ticker=(detail.get("entity") or {}).get("ticker") or "", as_of=detail.get("as_of", ""),
            value_per_share={"p10": prem[0], "p50": prem[1], "p90": prem[2], "mean": prem[1]},
            assumptions_used={"deals": len(out["deals"]), "choice": out["choice"], "sources": a.get("sources") or {}},
            lineage={}, notes=notes,
            details={**out, "target": target,
                     "range": {"conservative": prem[0], "expected": prem[1], "aggressive": prem[2]}})


MODEL = Precedents()
