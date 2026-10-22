"""Action titles for the Company Detail charts: one sentence each that says what the chart shows.

Built from the same annual figures the charts plot (views.annual, analysis.annual). A chart whose
figures are missing gets None and the site keeps its plain label.

    revenue   growth over the years shown and the latest year's revenue
    returns   RNOA in the latest year and what financing adds or takes off (ROCE − RNOA)
    margins   operating margin, first year shown to latest
    cash      free cash flow against net income over the years shown
"""
from __future__ import annotations

YEARS = 5      # the charts show the last five fiscal years


def _ok(*xs) -> bool:
    return all(isinstance(x, (int, float)) and x == x for x in xs)


def _pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def _money(v: float) -> str:
    a = abs(v)
    s = f"${a / 1e12:.1f}T" if a >= 1e12 else f"${a / 1e9:.1f}B" if a >= 1e9 else f"${a / 1e6:.0f}M" if a >= 1e6 else f"${a:,.0f}"
    return ("−" if v < 0 else "") + s


def company_headlines(doc: dict) -> dict:
    out = dict.fromkeys(("revenue", "returns", "margins", "cash"))
    ann = ((doc.get("views") or {}).get("annual") or [])[-YEARS:]
    name = (doc.get("entity") or {}).get("ticker") or "The company"
    if len(ann) >= 2:
        first, last = ann[0], ann[-1]
        r0, r1 = first["values"].get("revenue"), last["values"].get("revenue")
        n = len(ann) - 1
        if _ok(r0, r1) and r0 > 0 and r1 > 0:
            g = (r1 / r0) ** (1 / n) - 1
            verb = "grew" if g >= 0.005 else "shrank" if g <= -0.005 else "held flat"
            rate = f" {_pct(abs(g))} a year" if verb != "held flat" else ""
            out["revenue"] = f"Revenue {verb}{rate} from {first['label']} to {last['label']}, to {_money(r1)}."
        m = [(p["label"], p["values"].get("operating_income_loss"), p["values"].get("revenue")) for p in ann]
        m = [(lbl, oi / rev) for lbl, oi, rev in m if _ok(oi, rev) and rev]
        if len(m) >= 2:
            (l0, a), (l1, b) = m[0], m[-1]
            d = b - a
            if abs(d) < 0.005:
                out["margins"] = f"Operating margin held steady near {_pct(b)} from {l0} to {l1}."
            else:
                move = "widened" if d > 0 else "narrowed"
                out["margins"] = f"Operating margin {move} {abs(d) * 100:.1f} points, from {_pct(a)} in {l0} to {_pct(b)} in {l1}."
        ni = [p["values"].get("net_income") for p in ann]
        fcf = [p["values"].get("free_cash_flow") for p in ann]
        pairs = [(a, b) for a, b in zip(ni, fcf) if _ok(a, b)]
        tot_ni, tot_fcf = sum(a for a, _ in pairs), sum(b for _, b in pairs)
        if len(pairs) >= 2 and tot_ni > 0:
            conv = tot_fcf / tot_ni
            read = ("profits turn into cash" if conv >= 0.9 else "some profit is tied up in working capital or capex"
                    if conv >= 0.5 else "much of the profit doesn't reach cash")
            out["cash"] = f"Free cash flow was {conv * 100:.0f}% of net income over {len(pairs)} years: {read}."
    an = [a for a in ((doc.get("analysis") or {}).get("annual") or []) if (a.get("ratios") or {}).get("reformulated", {}).get("avg")]
    if an:
        avg = an[-1]["ratios"]["reformulated"]["avg"]
        rnoa, roce = avg.get("rnoa"), avg.get("roce")
        if _ok(rnoa, roce):
            d = roce - rnoa
            lev = (f"financing adds {d * 100:.1f} points for shareholders (ROCE {_pct(roce)})" if d >= 0.005
                   else f"financing takes {abs(d) * 100:.1f} points off shareholder returns (ROCE {_pct(roce)})" if d <= -0.005
                   else f"ROCE is about the same at {_pct(roce)}")
            out["returns"] = f"{name} earned {_pct(rnoa)} on its operating assets in {an[-1].get('label', 'the latest year')}; {lev}."
    return out
