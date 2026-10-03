"""L0 market data: share prices and the risk-free rate, point-in-time at as_of.

Sources
-------
  Yahoo chart API (primary)   query1.finance.yahoo.com/v8/finance/chart/{symbol}
                              no key; unofficial (the endpoint yfinance uses)
  Alpha Vantage (backup +     www.alphavantage.co/query (TIME_SERIES_DAILY compact,
  check)                      TIME_SERIES_MONTHLY_ADJUSTED); free key in $ALPHAVANTAGE_API_KEY.
                              The free plan allows 25 requests a day, so it is used sparingly:
                              one call per cross-check, three for a full fallback.
  FRED DGS10 (risk-free)      fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10, no key

Rules
-----
- Price = the last close on or before as_of (a past as_of never sees later prices).
- Monthly adjusted closes for 5 years plus the market index (^GSPC on Yahoo, SPY on
  Alpha Vantage, which has no index series) feed the beta in L1.
- Yahoo fails or returns nothing -> Alpha Vantage becomes the source (`fallback: true`).
- cross_check=True also asks Alpha Vantage for the same close and records the gap:
  ok within 2%, else mismatch. No key -> the check is skipped and says so.
- Alpha Vantage's free daily series covers the latest 100 trading days, so a fallback or
  check for an older as_of reports "unavailable" rather than guessing.
- The key has to go in the query string; it is redacted from every stored error message.
- L0 stores what the sources said; beta, market cap and WACC are L1's job.

raw_market.json
---------------
  {schema_version, ticker, as_of, source, fallback, currency, price, price_date,
   monthly: [{month, adj_close}], index: {symbol, monthly}, check, errors, fetched_at}
"""
from __future__ import annotations

import csv
import io
import json
import os
from datetime import date, datetime, timedelta, timezone
from typing import Protocol
from urllib.parse import quote

from .cache import FileCache
from .http import HttpClient, HttpError

SCHEMA_VERSION = "0.1.0"
YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?period1={p1}&period2={p2}&interval={interval}&events=div%2Csplit"
AV_URL = "https://www.alphavantage.co/query?function={function}&symbol={symbol}{extra}&apikey={key}"
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}&cosd={start}&coed={end}"
YAHOO_INDEX, AV_INDEX = "^GSPC", "SPY"
CHECK_TOLERANCE = 0.02
BETA_YEARS = 5
BROWSER_UA = "Mozilla/5.0 (compatible; valuation-model/0.1)"


class BytesClient(Protocol):
    def get_bytes(self, url: str) -> bytes: ...


class MarketDataError(RuntimeError):
    pass


def _epoch(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


def _day(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()


def _months(rows: list[tuple[str, float]]) -> list[dict]:
    """[(iso date, adj close)] -> one point per calendar month (the last one), oldest first."""
    by = {}
    for d, v in sorted(rows):
        if v is not None:
            by[d[:7]] = v
    return [{"month": m, "adj_close": v} for m, v in sorted(by.items())]


def yahoo_symbol(t: str) -> str:
    return t.upper().replace(".", "-")          # BRK.B -> BRK-B


def av_symbol(t: str) -> str:
    return t.upper().replace("-", ".")          # Alpha Vantage writes BRK.B


def parse_yahoo(payload: dict) -> dict:
    """Chart API JSON -> {currency, daily: [(date, close, adj_close)]}."""
    chart = payload.get("chart") or {}
    if chart.get("error"):
        raise MarketDataError(f"yahoo: {chart['error']}")
    res = (chart.get("result") or [None])[0]
    if not res or not res.get("timestamp"):
        raise MarketDataError("yahoo: no data")
    q = (res.get("indicators", {}).get("quote") or [{}])[0].get("close") or []
    adj = ((res.get("indicators", {}).get("adjclose") or [{}])[0].get("adjclose")) or q
    rows = [(_day(t), c, a) for t, c, a in zip(res["timestamp"], q, adj) if c is not None]
    return {"currency": (res.get("meta") or {}).get("currency"), "rows": rows}


def parse_alphavantage(payload: dict) -> dict:
    """TIME_SERIES_DAILY / TIME_SERIES_MONTHLY_ADJUSTED JSON -> {currency, rows}. Rate-limit and
    error notices arrive as HTTP 200 with a "Note", "Information" or "Error Message" key."""
    for k in ("Error Message", "Note", "Information"):
        if k in (payload or {}):
            raise MarketDataError(f"alphavantage: {payload[k]}")
    series = next((v for k, v in (payload or {}).items() if "Time Series" in k), None)
    if not series:
        raise MarketDataError("alphavantage: no data")
    rows = []
    for d, r in series.items():
        c = r.get("4. close")
        if c is not None:
            rows.append((d, float(c), float(r.get("5. adjusted close", c))))
    return {"currency": "USD", "rows": sorted(rows)}


def parse_fred(text: str) -> list[tuple[str, float]]:
    out = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) == 2 and row[0][:1].isdigit() and row[1] not in (".", ""):
            out.append((row[0], float(row[1]) / 100))
    return out


class MarketAdapter:
    name = "market"

    def __init__(self, yahoo: BytesClient | None = None, alphavantage: BytesClient | None = None,
                 fred: BytesClient | None = None, cache: FileCache | None = None,
                 av_key: str | None = None):
        self._yahoo, self._alphavantage, self._fred = yahoo, alphavantage, fred
        self.av_key = av_key if av_key is not None else os.environ.get("ALPHAVANTAGE_API_KEY", "")
        self.cache = cache

    # clients are built lazily, so tests and cache-only runs need no network or key
    def _client(self, which: str) -> BytesClient:
        attr = f"_{which}"
        if getattr(self, attr) is None:
            gap = {"yahoo": 0.5, "alphavantage": 1.5}.get(which, 0.2)
            setattr(self, attr, HttpClient(BROWSER_UA, min_interval=gap, contact_required=False))
        return getattr(self, attr)

    def _redact(self, msg: str) -> str:
        return msg.replace(self.av_key, "***") if self.av_key else msg

    def _get(self, which: str, url: str, key: str) -> bytes:
        if self.cache and (hit := self.cache.get(key)):
            return hit[0]
        try:
            data = self._client(which).get_bytes(url)
        except HttpError as e:
            raise MarketDataError(self._redact(str(e))) from None
        if self.cache:
            self.cache.put(key, data)
        return data

    # ------------------------------------------------------------- sources
    def yahoo(self, symbol: str, start: date, end: date, interval: str) -> dict:
        url = YAHOO_URL.format(symbol=quote(symbol, safe=""), p1=_epoch(start), p2=_epoch(end + timedelta(days=1)), interval=interval)
        return parse_yahoo(json.loads(self._get("yahoo", url, f"yahoo_{symbol}_{interval}_{start}_{end}")))

    def alphavantage(self, symbol: str, start: date, end: date, interval: str) -> dict:
        """One call returns the whole series (daily: latest 100 days; monthly: full history);
        start/end only filter it. Cached per symbol and day, so a run never asks twice."""
        if not self.av_key:
            raise MarketDataError("alphavantage: no ALPHAVANTAGE_API_KEY")
        function, extra = (("TIME_SERIES_MONTHLY_ADJUSTED", "") if interval == "1mo"
                           else ("TIME_SERIES_DAILY", "&outputsize=compact"))
        url = AV_URL.format(function=function, symbol=quote(symbol, safe=""), extra=extra, key=self.av_key)
        doc = parse_alphavantage(json.loads(self._get("alphavantage", url, f"av_{function}_{symbol}_{date.today()}")))
        rows = [r for r in doc["rows"] if start.isoformat() <= r[0] <= end.isoformat()]
        if not rows:
            raise MarketDataError(f"alphavantage: no {symbol} data between {start} and {end}")
        return {**doc, "rows": rows}

    def risk_free(self, as_of: str, series: str = "DGS10") -> dict:
        """Last 10-year Treasury yield on or before as_of, as a decimal."""
        end = date.fromisoformat(as_of)
        url = FRED_URL.format(series=series, start=end - timedelta(days=14), end=end)
        rows = parse_fred(self._get("fred", url, f"fred_{series}_{end}").decode())
        if not rows:
            raise MarketDataError(f"fred: no {series} observation in the two weeks to {as_of}")
        d, v = rows[-1]
        return {"series": series, "value": v, "date": d, "source": "FRED (Federal Reserve H.15)"}

    # ------------------------------------------------------------- one company
    def _series(self, which: str, ticker: str, as_of: date) -> dict:
        sym = yahoo_symbol(ticker) if which == "yahoo" else av_symbol(ticker)
        fetch = self.yahoo if which == "yahoo" else self.alphavantage
        daily = [r for r in fetch(sym, as_of - timedelta(days=14), as_of, "1d")["rows"] if r[0] <= as_of.isoformat()]
        if not daily:
            raise MarketDataError(f"{which}: no close for {ticker} in the two weeks to {as_of}")
        start = date(as_of.year - BETA_YEARS, as_of.month, 1) - timedelta(days=31)
        m = fetch(sym, start, as_of, "1mo")
        idx_sym = YAHOO_INDEX if which == "yahoo" else AV_INDEX
        idx = fetch(idx_sym, start, as_of, "1mo")
        cut = lambda rows: [(d, a) for d, _, a in rows if d <= as_of.isoformat()]  # noqa: E731
        return {"source": which, "currency": m.get("currency"), "price": daily[-1][1], "price_date": daily[-1][0],
                "monthly": _months(cut(m["rows"])), "index": {"symbol": idx_sym, "monthly": _months(cut(idx["rows"]))}}

    def _close_on(self, which: str, ticker: str, on: str) -> tuple[str, float] | None:
        d = date.fromisoformat(on)
        sym = yahoo_symbol(ticker) if which == "yahoo" else av_symbol(ticker)
        rows = (self.yahoo if which == "yahoo" else self.alphavantage)(sym, d - timedelta(days=14), d, "1d")["rows"]
        rows = [r for r in rows if r[0] <= on]
        return (rows[-1][0], rows[-1][1]) if rows else None

    def fetch(self, ticker: str, as_of: str, cross_check: bool = False) -> dict:
        t, end = ticker.upper(), date.fromisoformat(as_of)
        errors: list[str] = []
        doc = None
        for which in ("yahoo", "alphavantage"):
            try:
                doc = self._series(which, t, end)
                break
            except (HttpError, MarketDataError, ValueError, KeyError) as e:
                errors.append(self._redact(f"{which}: {e}"))
        if doc is None:
            raise MarketDataError(f"{t}: no market data ({'; '.join(errors)})")
        doc["fallback"] = doc["source"] != "yahoo"
        doc["check"] = self.check(t, doc) if cross_check and not doc["fallback"] else None
        return {"schema_version": SCHEMA_VERSION, "ticker": t, "as_of": as_of, **doc, "errors": errors,
                "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}

    def check(self, ticker: str, doc: dict) -> dict:
        """Compare the primary close with Alpha Vantage's on the same day."""
        base = {"source": "alphavantage", "tolerance": CHECK_TOLERANCE}
        if not self.av_key:
            return {**base, "status": "skipped", "note": "no ALPHAVANTAGE_API_KEY"}
        try:
            got = self._close_on("alphavantage", ticker, doc["price_date"])
        except (HttpError, MarketDataError, ValueError, KeyError) as e:
            return {**base, "status": "unavailable", "note": self._redact(str(e))}
        if not got:
            return {**base, "status": "unavailable", "note": f"no Alpha Vantage close on or before {doc['price_date']}"}
        d, p = got
        diff = p / doc["price"] - 1 if doc["price"] else None
        status = "ok" if diff is not None and abs(diff) <= CHECK_TOLERANCE and d == doc["price_date"] else "mismatch"
        return {**base, "status": status, "price": p, "price_date": d, "diff_pct": diff}
