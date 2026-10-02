"""L1 stage 2, part 1: frequency views from canonical records.

Stage 1 keeps every duration it finds (3, 6, 9 and 12 months). This module
turns them into three views:

  annual     12-month periods; balance-sheet items at the fiscal year end
  quarterly  3-month periods. A quarter that wasn't reported on its own is
             derived from year-to-date figures:
               Q2 = 6M YTD - Q1          method ytd_derived
               Q3 = 9M YTD - 6M YTD      method ytd_derived
               Q4 = FY - 9M YTD          method q4_derived
             (cash-flow statements in 10-Qs are YTD only, so Q2/Q3 matter)
  ttm        trailing four contiguous quarters, summed; instants at the end

Rules:
  - Only additive items are differenced or summed: monetary durations that
    are reported or memo. Shares, per-share amounts and ratios are taken only
    where reported for that exact period.
  - Instants (balance sheet) never sum; each period takes its end-date value.
  - Derived concepts are recomputed per period from the view's own values,
    so EBITDA in a derived Q4 is Q4 operating income + Q4 D&A, and the
    effective tax rate is a true ratio rather than a difference of ratios.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta

from .formula import evaluate
from .registry import Registry

CONTIGUITY_DAYS = 3  # tolerance when checking that quarters follow each other


def _d(s: str) -> date:
    return date.fromisoformat(s)


def _next_day(s: str) -> str:
    return (_d(s) + timedelta(days=1)).isoformat()


def calendar_label(end: str) -> tuple[int, int]:
    """Calendar year and quarter for a period end. Ends in the first week of a
    month (52/53-week years) belong to the prior month."""
    d = _d(end) - timedelta(days=7)
    return d.year, (d.month - 1) // 3 + 1


def additive(c) -> bool:
    return c.period_type == "duration" and c.unit_type == "monetary" and c.kind != "derived"


class _Index:
    def __init__(self, records: list[dict]):
        self.dur: dict[str, dict[tuple, dict]] = defaultdict(dict)
        self.inst: dict[str, dict[str, dict]] = defaultdict(dict)
        for r in records:
            if r["start"] is None:
                self.inst[r["concept"]][r["end"]] = r
            else:
                self.dur[r["concept"]][(r["start"], r["end"])] = r


def _fiscal_calendar(idx: _Index, reg: Registry) -> list[dict]:
    """Fiscal years as chains of YTD ends: {start, ends: {3: e, 6: e, 9: e, 12: e}, fy}.

    Built from every additive duration so one sparse concept can't hide a quarter.
    """
    by_start: dict[str, dict[int, Counter]] = defaultdict(lambda: defaultdict(Counter))
    fy_votes: dict[str, Counter] = defaultdict(Counter)
    for cid, periods in idx.dur.items():
        if cid not in reg.concepts or not additive(reg[cid]):
            continue
        for (s, e), r in periods.items():
            m = r["months"]
            if m in (3, 6, 9, 12):
                by_start[s][m][e] += 1
                if r.get("fiscal_year") is not None:
                    fy_votes[s][r["fiscal_year"]] += 1
    chains = []
    for s, months in by_start.items():
        ends = {m: c.most_common(1)[0][0] for m, c in months.items()}
        # A start date is a fiscal-year start only if it anchors a YTD chain
        # (a 6/9/12-month period), or it is the latest Q1 of a year in progress.
        chains.append({"start": s, "ends": ends,
                       "fy": fy_votes[s].most_common(1)[0][0] if fy_votes[s] else None})
    starts_of_quarters = {_next_day(e) for ch in chains for m, e in ch["ends"].items() if m < 12}
    year_chains = [ch for ch in chains
                   if (set(ch["ends"]) & {6, 9, 12}) or ch["start"] not in starts_of_quarters]
    return sorted(year_chains, key=lambda ch: ch["start"])


def _quarters_of(chain: dict) -> list[tuple[int, str, str]]:
    """(quarter number, start, end) for the quarters a chain can define."""
    ends = chain["ends"]
    out, prev_end = [], None
    for q, m in enumerate((3, 6, 9, 12), start=1):
        if m not in ends:
            # can't place this quarter without its end date; later ones need it too
            if q == 1:
                return []
            break
        start = chain["start"] if q == 1 else _next_day(prev_end)
        out.append((q, start, ends[m]))
        prev_end = ends[m]
    return out


def _value(idx: _Index, cid: str, start: str, end: str) -> dict | None:
    return idx.dur.get(cid, {}).get((start, end))


def _quarter_value(idx: _Index, cid: str, chain: dict, q: int, qs: str, qe: str):
    """(value, method, record_or_None) for one additive concept in one quarter."""
    rec = _value(idx, cid, qs, qe)
    if rec is not None:
        return rec["value"], "reported", rec
    if q == 1:
        return None, None, None
    ytd = _value(idx, cid, chain["start"], qe)
    prev_ytd = _value(idx, cid, chain["start"], chain["ends"][3 * (q - 1)])
    if ytd is None or prev_ytd is None:
        return None, None, None
    return ytd["value"] - prev_ytd["value"], ("q4_derived" if q == 4 else "ytd_derived"), ytd


def _empty_period(label, fy, fp, start, end, months) -> dict:
    cy, cq = calendar_label(end)
    return {"label": label, "fiscal_year": fy, "fiscal_period": fp, "start": start, "end": end,
            "months": months, "calendar_year": cy, "calendar_quarter": cq,
            "values": {}, "methods": {}, "restated": []}


def _put(p: dict, cid: str, value, method: str, rec: dict | None) -> None:
    p["values"][cid] = value
    p["methods"][cid] = method
    if rec is not None and rec.get("restated"):
        p["restated"].append(cid)


def _fill_instants(p: dict, idx: _Index, reg: Registry) -> None:
    for cid, by_end in idx.inst.items():
        c = reg.concepts.get(cid)
        if c is None or c.kind == "derived":
            continue
        rec = by_end.get(p["end"])
        if rec is not None:
            _put(p, cid, rec["value"], rec["method"], rec)


def _derive(p: dict, reg: Registry) -> None:
    for c in reg.derived_order():
        v = evaluate(c.formula, p["values"])
        if v is not None:
            p["values"][c.id] = v
            p["methods"][c.id] = "derived"


def annual_view(idx: _Index, reg: Registry, chains: list[dict]) -> list[dict]:
    out = []
    for ch in chains:
        if 12 not in ch["ends"]:
            continue
        s, e = ch["start"], ch["ends"][12]
        p = _empty_period(f"FY{ch['fy']}", ch["fy"], "FY", s, e, 12)
        for cid, periods in idx.dur.items():
            c = reg.concepts.get(cid)
            if c is None or c.kind == "derived":
                continue
            rec = periods.get((s, e))
            if rec is not None:
                _put(p, cid, rec["value"], rec["method"], rec)
        _fill_instants(p, idx, reg)
        _derive(p, reg)
        out.append(p)
    return out


def quarterly_view(idx: _Index, reg: Registry, chains: list[dict]) -> list[dict]:
    out = []
    for ch in chains:
        for q, qs, qe in _quarters_of(ch):
            p = _empty_period(f"FY{ch['fy']} Q{q}", ch["fy"], f"Q{q}", qs, qe, 3)
            for cid in idx.dur:
                c = reg.concepts.get(cid)
                if c is None or c.kind == "derived":
                    continue
                if additive(c):
                    v, method, rec = _quarter_value(idx, cid, ch, q, qs, qe)
                else:
                    rec = _value(idx, cid, qs, qe)
                    v, method = (rec["value"], "reported") if rec else (None, None)
                if v is not None:
                    _put(p, cid, v, method, rec)
            _fill_instants(p, idx, reg)
            _derive(p, reg)
            if p["values"]:
                out.append(p)
    out.sort(key=lambda p: p["end"])
    return out


def ttm_view(quarters: list[dict], reg: Registry) -> list[dict]:
    """One TTM period per quarter end that closes four contiguous quarters."""
    out = []
    for i in range(3, len(quarters)):
        window = quarters[i - 3:i + 1]
        if any(abs((_d(b["start"]) - _d(_next_day(a["end"]))).days) > CONTIGUITY_DAYS
               for a, b in zip(window, window[1:])):
            continue
        last = window[-1]
        p = _empty_period(f"TTM {last['end']}", last["fiscal_year"], f"TTM-{last['fiscal_period']}",
                          window[0]["start"], last["end"], 12)
        for cid, c in reg.concepts.items():
            if additive(c) and all(cid in q["values"] for q in window):
                methods = {q["methods"][cid] for q in window}
                _put(p, cid, sum(q["values"][cid] for q in window),
                     "summed_4q" if methods == {"reported"} else "summed_4q_with_derived", None)
                if any(cid in q["restated"] for q in window):
                    p["restated"].append(cid)
            elif c.period_type == "instant" and c.kind != "derived" and cid in last["values"]:
                _put(p, cid, last["values"][cid], last["methods"][cid], None)
        _derive(p, reg)
        out.append(p)
    return out


def build_views(records: list[dict], reg: Registry) -> dict:
    idx = _Index(records)
    chains = _fiscal_calendar(idx, reg)
    quarterly = quarterly_view(idx, reg, chains)
    return {
        "annual": annual_view(idx, reg, chains),
        "quarterly": quarterly,
        "ttm": ttm_view(quarterly, reg),
    }
