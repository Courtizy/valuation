"""Synthetic market inputs for the demo, in the same shapes the real market step writes, so the
real L1 code computes beta, market cap and WACC from them. Seeded, so every rebuild is identical.

Each featured company shows a different market-data state:
  DEMO   Yahoo price, checked against Alpha Vantage (ok)
  DEMOG  Yahoo price, Alpha Vantage differs by 2.6% (mismatch flag)
  DEMOU  Yahoo unavailable, Alpha Vantage used as the backup; two fiscal years of D&A missing from
         the "filings" are filled from Yahoo-style fundamentals (shown as y)
"""
from __future__ import annotations

import random
from datetime import date

from L3_app.demo.companies import AS_OF, MARKET

RISK_FREE = {"series": "DGS10 (synthetic)", "value": 0.045, "date": AS_OF, "source": "synthetic"}
MONTHS = 61


def _months_back(n: int) -> list[str]:
    y, m = date.fromisoformat(AS_OF).year, date.fromisoformat(AS_OF).month
    out = []
    for _ in range(n):
        out.append(f"{y}-{m:02d}")
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return out[::-1]


def _index_returns() -> list[float]:
    rng = random.Random(500)
    return [rng.gauss(0.008, 0.045) for _ in range(MONTHS - 1)]


def _series(end_value: float, returns: list[float]) -> list[dict]:
    """Adjusted closes ending at end_value whose month-on-month changes are `returns`."""
    vals = [end_value]
    for r in reversed(returns):
        vals.append(vals[-1] / (1 + r))
    vals = vals[::-1]
    return [{"month": m, "adj_close": round(v, 4)} for m, v in zip(_months_back(MONTHS), vals)]


def raw_market(ticker: str) -> dict:
    price, shares, beta = MARKET[ticker]
    idx = _index_returns()
    rng = random.Random(sum(map(ord, ticker)))
    stock = [beta * r + rng.gauss(0, 0.035) for r in idx]
    doc = {"schema_version": "0.1.0", "ticker": ticker, "as_of": AS_OF, "source": "yahoo", "fallback": False,
           "currency": "USD", "price": price, "price_date": AS_OF, "shares_outstanding": shares,
           "monthly": _series(price, stock),
           "index": {"symbol": "^GSPC", "monthly": _series(4800.0, idx)}, "errors": [], "fundamentals": None,
           "check": {"source": "alphavantage", "tolerance": 0.02, "status": "ok", "price": round(price * 1.002, 2),
                     "price_date": AS_OF, "diff_pct": 0.002}}
    if ticker == "DEMOG":
        doc["check"] = {**doc["check"], "status": "mismatch", "price": round(price * 1.026, 2), "diff_pct": 0.026}
    if ticker == "DEMOU":
        doc.update(source="alphavantage", fallback=True, check=None,
                   errors=["yahoo: 503 Service Unavailable (synthetic example of the backup source)"])
        doc["index"]["symbol"] = "SPY"
    return doc


def fundamentals_for_gaps(removed: list[dict]) -> dict:
    """Yahoo-style fundamentals carrying exactly the values removed from the synthetic filings."""
    return {"source": "yahoo", "series": {"annualReconciledDepreciation": [
        {"end": r["end"], "value": r["value"], "period": "12M", "currency": "USD"} for r in removed]}}
