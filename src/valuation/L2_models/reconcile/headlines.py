"""Action titles: one sentence per section that says what the numbers show.

The site shows these in place of plain labels ("Football Field"), the way a banking book or a
consulting deck titles each page with its finding. Every sentence is built from the same
figures the section displays, so the words can't drift from the numbers. A section whose
figures are missing gets None, and the site falls back to its plain label.

    valuation_headlines(comparison, by_model)   -> {"answer", "field", "spread", "sensitivity", "comps", "dcf"}
    deal_headlines(deal, by_model)              -> {"summary", "field", "bridge", "premiums", "prior_deals",
                                                    "whole_firm", "just_synergy"}
"""
from __future__ import annotations

FAIR = 0.05          # within 5% of the price reads as "in line with"


def _ok(*xs) -> bool:
    return all(isinstance(x, (int, float)) and x == x for x in xs)


def usd(v: float) -> str:
    return f"${v:,.2f}"


def pct(v: float, digits: int = 1) -> str:
    return f"{v * 100:.{digits}f}%"


def _vs_price(value: float, px: float) -> str:
    gap = value / px - 1
    if abs(gap) < FAIR:
        return f"in line with the {usd(px)} share price"
    return f"{pct(abs(gap), 0)} {'above' if gap > 0 else 'below'} the {usd(px)} share price"


def _details(by_model: dict, m: str) -> dict:
    return (by_model.get(m) or {}).get("details") or {}


# ------------------------------------------------------------------ standalone valuation

def valuation_headlines(c: dict, by_model: dict, ticker: str = "") -> dict:
    name = ticker or c.get("ticker") or "The company"
    out = dict.fromkeys(("answer", "field", "spread", "sensitivity", "comps", "dcf"))
    blend, px = c.get("blend") or {}, c.get("price")
    if _ok(blend.get("p50"), blend.get("p10"), blend.get("p90")):
        rng = f"range {usd(blend['p10'])}–{usd(blend['p90'])}"
        out["answer"] = (f"{name} is worth about {usd(blend['p50'])} a share ({rng}), {_vs_price(blend['p50'], px)}."
                         if _ok(px) else f"{name} is worth about {usd(blend['p50'])} a share ({rng}).")

    methods = [m for m in (c.get("plan") or {}).get("methods", [])
               if m.get("weight", 0) > 0 and (m.get("value_per_share") or {}).get("p50") is not None]
    if len(methods) >= 2:
        lo = min(methods, key=lambda m: m["value_per_share"]["p50"])
        hi = max(methods, key=lambda m: m["value_per_share"]["p50"])
        a, b = lo["value_per_share"]["p50"], hi["value_per_share"]["p50"]
        short = {"dcf": "the DCF", "comps": "sector comps", "comps_closest": "closest-match comps"}
        nm = lambda m: short.get(m["model"]) or str(m.get("name") or m["model"]).lower()  # noqa: E731
        if b / a - 1 < 0.10:
            out["field"] = f"The weighted methods agree within {usd(b - a)} a share: {nm(lo)} at {usd(a)}, {nm(hi)} at {usd(b)}."
        else:
            out["field"] = (f"The methods are {pct(b / a - 1, 0)} apart: {nm(lo)} gives {usd(a)}, {nm(hi)} {usd(b)}, "
                            f"so the weights decide the answer.")
    elif len(methods) == 1:
        v = methods[0]["value_per_share"]
        out["field"] = f"One weighted method so far: {usd(v['p10'])}–{usd(v['p90'])} a share."

    d = _details(by_model, "dcf")
    ps = (d.get("simulation") or {}).get("per_share") or {}
    runs = (d.get("simulation") or {}).get("runs_used")
    if _ok(ps.get("p10"), ps.get("p90"), runs):
        tail = ""
        if _ok(px):
            # share of simulated runs at or above the price, from the percentiles
            qs = [(0.05, ps.get("p5")), (0.10, ps["p10"]), (0.25, ps.get("p25")), (0.50, ps.get("p50")),
                  (0.75, ps.get("p75")), (0.90, ps["p90"]), (0.95, ps.get("p95"))]
            qs = [(q, v) for q, v in qs if _ok(v)]
            below = next((q for q, v in qs if v >= px), None)
            if below is None:
                tail = f"; fewer than {pct(1 - qs[-1][0], 0)} of runs reach the {usd(px)} price"
            elif below == qs[0][0] and qs[0][1] >= px:
                tail = f"; more than {pct(1 - qs[0][0], 0)} of runs are above the {usd(px)} price"
            else:
                tail = f"; about {pct(1 - below, 0)} of runs are above the {usd(px)} price"
        out["spread"] = f"80% of {runs:,} simulated runs land between {usd(ps['p10'])} and {usd(ps['p90'])}{tail}."

    s = d.get("sensitivity") or {}
    vals, w = s.get("values"), s.get("wacc")
    if vals and w and len(vals) >= 2:
        mid = len(vals[0]) // 2
        steps = [abs(vals[i][mid] - vals[i + 1][mid]) for i in range(len(vals) - 1) if _ok(vals[i][mid], vals[i + 1][mid])]
        flat = [v for row in vals for v in row if _ok(v)]
        if steps and flat:
            dw = abs(w[1] - w[0])
            out["sensitivity"] = (f"Each {dw * 100:.1f}-point change in the discount rate moves value about "
                                  f"{usd(sum(steps) / len(steps))} a share; the grid spans {usd(min(flat))}–{usd(max(flat))}.")

    tv, base = d.get("terminal_value_share"), (d.get("bridge") or {}).get("value_per_share")
    if _ok(tv, base):
        out["dcf"] = f"The DCF's {usd(base)} a share rests {pct(tv, 0)} on the terminal value."

    cd = _details(by_model, "comps")
    mult = cd.get("multiples") or {}
    if mult:
        exp = {k: v.get("expected") for k, v in mult.items() if _ok(v.get("expected"))}
        if exp:
            v = (by_model.get("comps") or {}).get("value_per_share") or {}
            hi_k = max(exp, key=exp.get)
            label = (mult[hi_k].get("label") or hi_k).replace(" ", "")
            core = f"Peers' multiples imply {usd(v['p50'])} a share" if _ok(v.get("p50")) else "Peers' multiples"
            rng = f" (range {usd(v['p10'])}–{usd(v['p90'])})" if _ok(v.get("p10"), v.get("p90")) else ""
            out["comps"] = f"{core}{rng}; {label} gives the highest median at {usd(exp[hi_k])}."
            cb = (cd.get("closest") or {}).get("blend") or {}
            if _ok(v.get("p50"), cb.get("expected")):
                n = sum(1 for r in cd["closest"].get("peers") or [] if not r.get("excluded"))
                gap = cb["expected"] / v["p50"] - 1
                where = "about the same" if abs(gap) < 0.02 else f"{pct(abs(gap), 0)} {'more' if gap > 0 else 'less'}"
                out["comps"] = (f"Sector peers imply {usd(v['p50'])} a share{rng}; the {n} peers closest on fundamentals "
                                f"give {usd(cb['expected'])}, {where}.")
    return out


# ------------------------------------------------------------------ deal

def _past_clause(prem: float, st: dict) -> tuple[str, int]:
    """Where the bid's premium sits among past deals: (clause, -1 cheap / 0 in line / +1 rich)."""
    if prem < st["q1"]:
        return "below what past acquirers paid", -1
    if prem > st["q3"]:
        return "above what past acquirers paid", 1
    return "in line with what past acquirers paid", 0


def deal_headlines(deal: dict | None, by_model: dict) -> dict:
    out = dict.fromkeys(("summary", "field", "bridge", "premiums", "prior_deals", "whole_firm", "just_synergy"))
    if not deal:
        return out
    pre, offer_px = deal.get("pre_announcement_price"), deal.get("offer_price")
    offer, st = (deal.get("offer") or {}).get("range"), (deal.get("standalone") or {}).get("range")
    js = _details(by_model, "just_synergy")
    syn = js.get("synergy_per_share")
    pd = _details(by_model, "precedents")
    prem_stats = ((pd.get("central") or {}).get("stats") or {}).get("premium")

    # summary: the bid against past deals and against the synergies
    if _ok(offer_px, pre):
        bid_prem = offer_px / pre - 1
        past = _past_clause(bid_prem, prem_stats) if prem_stats and _ok(prem_stats.get("q1"), prem_stats.get("q3")) else None
        syn_clause, syn_sign = None, 0
        if _ok(syn):
            gap = offer_px - (pre + syn)
            if abs(gap) < 0.005 * offer_px:
                syn_clause = "about what the synergies are worth"
            elif gap > 0:
                syn_clause, syn_sign = f"{usd(gap)} a share above what the synergies are worth", 1
            else:
                syn_clause, syn_sign = f"leaves {usd(-gap)} a share of the synergies with the buyer", -1
        if past and syn_clause:
            # "but" when one test flatters the bid and the other doesn't
            joint = "but" if (syn_sign > 0 and past[1] <= 0) or (syn_sign < 0 and past[1] > 0) else "and"
            out["summary"] = f"At {usd(offer_px)}, the bid is {past[0]} {joint} {syn_clause}."
        elif past:
            out["summary"] = f"At {usd(offer_px)} ({pct(bid_prem)} premium), the bid is {past[0]}."
        elif syn_clause:
            out["summary"] = f"At {usd(offer_px)} ({pct(bid_prem)} premium), the bid is {syn_clause}."
        elif offer and _ok(offer.get("conservative"), offer.get("aggressive")):
            where = ("inside" if offer["conservative"] <= offer_px <= offer["aggressive"]
                     else "above" if offer_px > offer["aggressive"] else "below")
            out["summary"] = f"At {usd(offer_px)}, the bid sits {where} the {usd(offer['conservative'])}–{usd(offer['aggressive'])} offer range."
    elif offer and _ok(pre, offer.get("conservative"), offer.get("aggressive")):
        out["summary"] = (f"A fair offer runs {usd(offer['conservative'])}–{usd(offer['aggressive'])} a share, "
                          f"a {pct(offer['conservative'] / pre - 1, 0)}–{pct(offer['aggressive'] / pre - 1, 0)} premium "
                          f"to the {usd(pre)} pre-announcement price.")

    if offer and st and _ok(offer.get("conservative"), st.get("aggressive"), st.get("best_guess"), offer.get("best_guess")):
        gap = offer["conservative"] - st["aggressive"]
        if gap > 0:
            out["field"] = (f"The offer range starts {usd(gap)} a share above the top of the standalone range "
                            f"({usd(st['aggressive'])}): that gap is what control and synergies add.")
        else:
            out["field"] = (f"The offer range overlaps the standalone range; the best guesses are "
                            f"{usd(st['best_guess'])} standalone and {usd(offer['best_guess'])} with control.")

    if _ok(pre, syn):
        cap = pre + syn
        tail = ""
        if _ok(offer_px):
            d = offer_px - cap
            tail = (f"; the {usd(offer_px)} bid pays {usd(d)} a share more than that" if d > 0.005
                    else f"; the {usd(offer_px)} bid keeps {usd(-d)} a share for the buyer" if d < -0.005 else "; the bid pays all of it")
        out["bridge"] = f"Synergies are worth {usd(syn)} a share, so the most a buyer can pay without losing value is {usd(cap)}{tail}."

    if prem_stats and _ok(prem_stats.get("median")):
        n = prem_stats.get("n")
        lead = f"Past deals paid a median {pct(prem_stats['median'])} premium"
        lead += f" across {n} deals" if n else ""
        if _ok(offer_px, pre):
            bp = offer_px / pre - 1
            pos = ("below the first quartile" if bp < prem_stats["q1"] else "above the third quartile"
                   if bp > prem_stats["q3"] else "inside the middle half")
            out["premiums"] = f"{lead}; the bid's {pct(bp)} sits {pos}."
        else:
            out["premiums"] = f"{lead}; the middle half paid {pct(prem_stats['q1'])}–{pct(prem_stats['q3'])}."

    if pd:
        sts = (pd.get("central") or {}).get("stats") or {}
        n = len(pd.get("deals") or [])
        tx = (sts.get("tx_ev_ebitda") or {}).get("median")
        ps = (sts.get("premium") or {}).get("median")
        bits = [f"median premium {pct(ps)}" if _ok(ps) else None, f"median transaction EV/EBITDA {tx:.1f}x" if _ok(tx) else None]
        bits = [b for b in bits if b]
        if n:
            out["prior_deals"] = f"{n} prior deals, {len(pd.get('best') or [])} marked most comparable" + (f": {', '.join(bits)}." if bits else ".")

    wf = _details(by_model, "dcf_synergy")
    rg = wf.get("range") or {}
    if _ok(rg.get("expected"), wf.get("standalone_per_share")):
        add = rg["expected"] - wf["standalone_per_share"]
        out["whole_firm"] = (f"With synergies the whole firm is worth {usd(rg['expected'])} a share, "
                             f"{usd(abs(add))} {'more' if add >= 0 else 'less'} than the standalone DCF.")

    if _ok(syn, js.get("terminal_value_share")):
        out["just_synergy"] = (f"Synergies add {usd(syn)} a share; {pct(js['terminal_value_share'], 0)} of that value "
                               f"comes from the terminal year onward.")
    return out
