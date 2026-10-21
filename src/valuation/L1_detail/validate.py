"""Validation: the SEC figures checked against themselves and against a second source.

- Tie-outs (from L1 normalize): assets = liabilities + equity, gross profit = revenue - cost
  of revenue, net income split. Each counts periods checked and those off by more than 0.5%.
- Cross-source: each filed annual figure that Yahoo fundamentals also report for the same
  fiscal year end, compared within 2%. Values Yahoo filled in (backfill) aren't compared,
  since they have nothing to be checked against.

company_detail["validation"] carries both; a figure that differs is listed with both values,
so a reader can see which source to trust. The SEC value is always the one used.
"""
from __future__ import annotations

from datetime import date

from .backfill import ITEMS, METHOD

TOLERANCE = 0.02
YEARS = 4                      # the latest fiscal years compared


def _near(a: str, b: str) -> bool:
    return abs((date.fromisoformat(a) - date.fromisoformat(b)).days) <= 7


def cross_source(records: list[dict], fundamentals: dict | None) -> dict | None:
    """Filed annual values vs Yahoo's for the same concept and year end."""
    series = (fundamentals or {}).get("series") or {}
    if not series:
        return None
    filed: dict[str, list[dict]] = {}
    for r in records:
        if r.get("method") != METHOD and (r.get("months") == 12 or r.get("period_type") == "instant"):
            filed.setdefault(r["concept"], []).append(r)
    ends = sorted({r["end"] for r in records if r.get("months") == 12 and r.get("method") != METHOD})[-YEARS:]
    rows = []
    for name, points in series.items():
        if not name.startswith("annual") or name.removeprefix("annual") not in ITEMS:
            continue
        cid, sign = ITEMS[name.removeprefix("annual")]
        for p in points:
            if p.get("value") is None or p.get("currency") not in (None, "USD") or not any(_near(p["end"], e) for e in ends):
                continue
            sec = next((r for r in filed.get(cid, []) if _near(r["end"], p["end"])), None)
            if sec is None or sec["value"] is None:
                continue
            other = sign * p["value"]
            diff = (other - sec["value"]) / abs(sec["value"]) if sec["value"] else (0.0 if not other else None)
            rows.append({"concept": cid, "end": sec["end"], "sec": sec["value"], "other": other,
                         "diff_pct": diff, "ok": diff is not None and abs(diff) <= TOLERANCE})
    rows.sort(key=lambda r: (r["concept"], r["end"]))
    return {"source": fundamentals.get("source", "yahoo"), "tolerance": TOLERANCE, "compared": len(rows),
            "agree": sum(r["ok"] for r in rows), "differ": [r for r in rows if not r["ok"]]}


def tie_outs(checks: list[dict] | None) -> list[dict]:
    return [{"name": c["name"], "evaluated": c["evaluated"], "failed": len(c["failed"]),
             "periods_failed": [f["end"] for f in c["failed"]][-YEARS:]} for c in checks or []]


def validation(canonical: dict, records: list[dict], fundamentals: dict | None) -> dict:
    return {"tie_outs": tie_outs(canonical.get("checks")), "cross_source": cross_source(records, fundamentals)}


def warnings_for(v: dict) -> list[str]:
    out = []
    bad = [t for t in v["tie_outs"] if t["failed"]]
    if bad:
        out.append("filings don't tie out: " + "; ".join(f"{t['name'].replace('_', ' ')} in {t['failed']} of {t['evaluated']} periods" for t in bad))
    x = v.get("cross_source")
    if x and x["differ"]:
        names = sorted({d["concept"].replace("_", " ") for d in x["differ"]})
        out.append(f"{len(x['differ'])} of {x['compared']} filed figures differ from {x['source'].title()} by more than "
                   f"{x['tolerance']:.0%} ({', '.join(names[:5])}{'…' if len(names) > 5 else ''}); the SEC figures are used")
    return out
