"""L0 market data: share prices and the risk-free rate, point-in-time at as_of.

Sources
-------
  Yahoo chart API (primary)   query1.finance.yahoo.com/v8/finance/chart/{symbol}
                              no key; unofficial (the endpoint yfinance uses)
  Alpha Vantage (backup +     www.alphavantage.co/query (TIME_SERIES_DAILY compact,
  check)                      TIME_SERIES_MONTHLY_ADJUSTED); free key in $ALPHAVANTAGE_API_KEY.
                              The free plan allows 25 requests a day, so it is used sparingly:
                              one call per cross-check, three for a full fallback.
  Finnhub (last resort)       finnhub.io/api/v1/quote and /stock/metric; free key in $FINNHUB_API_KEY.
                              The free plan has no price history, only today's quote and a reported
                              beta, so it serves an as_of within a week of today and nothing older.
  FRED DGS10 (risk-free)      fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10, no key

Rules
-----
- Price = the last close on or before as_of (a past as_of never sees later prices).
- Monthly adjusted closes for 5 years plus the market index (^GSPC on Yahoo, SPY on
  Alpha Vantage, which has no index series) feed the beta in L1.
- Yahoo fails or returns nothing -> Alpha Vantage becomes the source (`fallback: true`), then Finnhub.
  Finnhub's beta arrives as `beta_reported` (no monthly series to compute one from).
- cross_check=True also asks Alpha Vantage for the same close and records the gap:
  ok within 2%, else mismatch. No key -> the check is skipped and says so.
- Alpha Vantage's free daily series covers the latest 100 trading days, so a fallback or
  check for an older as_of reports "unavailable" rather than guessing.
- The key has to go in the query string; it is redacted from every stored error message.
- quote: the as_of day's open, high, low, close and volume, the previous close, the 52-week
  range and 3-month average volume, from a year of daily bars (Yahoo; Alpha Vantage's free
  100 days give no 52-week range; Finnhub gives today's open, range and previous close).
- L0 stores what the sources said; beta, market cap and WACC are L1's job.

raw_market.json
---------------
  {schema_version, ticker, as_of, source, fallback, currency, price, price_date,
   monthly: [{month, adj_close}], index: {symbol, monthly}, quote, check, estimates, errors, fetched_at}
  estimates: {source, horizon "5y" | "1y", growth_5y | growth_1y, growth_past_5y} analysts' earnings
  growth (Yahoo earningsTrend, else Alpha Vantage EPS estimates); today's consensus, not point-in-time
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
FINNHUB_QUOTE_URL = "https://finnhub.io/api/v1/quote?symbol={symbol}&token={key}"
FINNHUB_METRIC_URL = "https://finnhub.io/api/v1/stock/metric?symbol={symbol}&metric=all&token={key}"
FINNHUB_MAX_AGE_DAYS = 7
# analysts' growth estimates: Yahoo's earningsTrend (+5y: next five years per annum, -5y: past five),
# else Alpha Vantage's EPS estimates (current to next fiscal year: a one-year horizon, said so)
YAHOO_TREND_URL = "https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}?modules=earningsTrend"
AV_ESTIMATES_URL = "https://www.alphavantage.co/query?function=EARNINGS_ESTIMATES&symbol={symbol}&apikey={key}"
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}&cosd={start}&coed={end}"
FUNDAMENTALS_URL = ("https://query1.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/{symbol}"
                    "?type={types}&period1={p1}&period2={p2}")
# Yahoo fundamentals fetched as a backup for statement items SEC filings lack (private and in-browser runs;
# L1_detail/backfill.py maps them to concepts and fills gaps, never overwriting a filed value)
FUNDAMENTAL_ITEMS = ("TotalRevenue", "CostOfRevenue", "GrossProfit", "OperatingIncome", "ReconciledDepreciation",
                     "InterestExpense", "InterestIncome", "PretaxIncome", "TaxProvision", "NetIncome",
                     "ResearchAndDevelopment", "SellingGeneralAndAdministration", "OperatingCashFlow", "CapitalExpenditure",
                     "CashCashEquivalentsAndShortTermInvestments", "LongTermDebt", "CurrentDebt", "StockholdersEquity",
                     "TotalAssets", "TotalLiabilitiesNetMinorityInterest", "CurrentAssets", "CurrentLiabilities",
                     "OrdinarySharesNumber", "DilutedAverageShares")
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
    """Chart API JSON -> {currency, rows: [(date, close, adj_close)], bars: [(date, open, high, low, close, volume)]}."""
    chart = payload.get("chart") or {}
    if chart.get("error"):
        raise MarketDataError(f"yahoo: {chart['error']}")
    res = (chart.get("result") or [None])[0]
    if not res or not res.get("timestamp"):
        raise MarketDataError("yahoo: no data")
    q = (res.get("indicators", {}).get("quote") or [{}])[0].get("close") or []
    adj = ((res.get("indicators", {}).get("adjclose") or [{}])[0].get("adjclose")) or q
    rows = [(_day(t), c, a) for t, c, a in zip(res["timestamp"], q, adj) if c is not None]
    ind = (res.get("indicators", {}).get("quote") or [{}])[0]
    col = lambda k: ind.get(k) or [None] * len(q)  # noqa: E731
    bars = [(_day(t), o, h, lo, c, v) for t, o, h, lo, c, v in
            zip(res["timestamp"], col("open"), col("high"), col("low"), q, col("volume")) if c is not None]
    return {"currency": (res.get("meta") or {}).get("currency"), "rows": rows, "bars": bars}


def parse_alphavantage(payload: dict) -> dict:
    """TIME_SERIES_DAILY / TIME_SERIES_MONTHLY_ADJUSTED JSON -> {currency, rows}. Rate-limit and
    error notices arrive as HTTP 200 with a "Note", "Information" or "Error Message" key."""
    for k in ("Error Message", "Note", "Information"):
        if k in (payload or {}):
            raise MarketDataError(f"alphavantage: {payload[k]}")
    series = next((v for k, v in (payload or {}).items() if "Time Series" in k), None)
    if not series:
        raise MarketDataError("alphavantage: no data")
    rows, bars = [], []
    num = lambda r, k: float(r[k]) if r.get(k) not in (None, "") else None  # noqa: E731
    for d, r in series.items():
        c = r.get("4. close")
        if c is not None:
            rows.append((d, float(c), float(r.get("5. adjusted close", c))))
            bars.append((d, num(r, "1. open"), num(r, "2. high"), num(r, "3. low"), float(c), num(r, "5. volume") or num(r, "6. volume")))
    return {"currency": "USD", "rows": sorted(rows), "bars": sorted(bars)}


def quote_from_bars(bars: list[tuple], as_of: str, source: str) -> dict | None:
    """The as_of day's bar, the previous close, 52-week range and 3-month average volume.
    bars: [(date, open, high, low, close, volume)], any order; later dates are ignored."""
    bars = sorted(b for b in bars if b[0] <= as_of and b[4] is not None)
    if not bars:
        return None
    d, o, h, lo, c, v = bars[-1]
    cut = (date.fromisoformat(d) - timedelta(days=365)).isoformat()
    year = [b for b in bars if b[0] > cut]
    full_year = bars[0][0] <= (date.fromisoformat(d) - timedelta(days=358)).isoformat()
    highs = [(b[2] if b[2] is not None else b[4], b[0]) for b in year]
    lows = [(b[3] if b[3] is not None else b[4], b[0]) for b in year]
    vols = [b[5] for b in bars if b[0] > (date.fromisoformat(d) - timedelta(days=91)).isoformat() and b[5]]
    return {"source": source, "date": d, "close": c, "open": o, "day_high": h, "day_low": lo, "volume": v,
            "prev_close": bars[-2][4] if len(bars) > 1 else None,
            "wk52_high": max(highs)[0] if full_year else None, "wk52_high_date": max(highs)[1] if full_year else None,
            "wk52_low": min(lows)[0] if full_year else None, "wk52_low_date": min(lows)[1] if full_year else None,
            "avg_volume_3m": sum(vols) / len(vols) if vols else None}


def parse_fundamentals(payload: dict) -> dict:
    """fundamentals-timeseries JSON -> {"annualTotalRevenue": [{end, value, period, currency}], ...}."""
    out = {}
    for res in ((payload or {}).get("timeseries") or {}).get("result") or []:
        t = ((res.get("meta") or {}).get("type") or [None])[0]
        rows = [{"end": r.get("asOfDate"), "value": (r.get("reportedValue") or {}).get("raw"),
                 "period": r.get("periodType"), "currency": r.get("currencyCode")}
                for r in (res.get(t) or []) if r and r.get("asOfDate") and (r.get("reportedValue") or {}).get("raw") is not None]
        if t and rows:
            out[t] = rows
    return out


def parse_earnings_trend(payload: dict) -> dict:
    """Yahoo quoteSummary earningsTrend -> {growth_5y, growth_past_5y} (decimals; None when absent)."""
    res = ((payload.get("quoteSummary") or {}).get("result") or [None])[0] or {}
    trend = {t.get("period"): t for t in (res.get("earningsTrend") or {}).get("trend") or []}
    raw = lambda p: ((trend.get(p) or {}).get("growth") or {}).get("raw")  # noqa: E731
    out = {"growth_5y": raw("+5y"), "growth_past_5y": raw("-5y")}
    out = {k: float(v) for k, v in out.items() if isinstance(v, (int, float))}
    if not out:
        raise MarketDataError("yahoo: no five-year growth estimate")
    return out


def parse_av_estimates(payload: dict) -> dict:
    """Alpha Vantage EARNINGS_ESTIMATES -> next fiscal year's EPS growth over the current year's."""
    for k in ("Note", "Information", "Error Message"):
        if k in payload:
            raise MarketDataError(f"alphavantage: {payload[k]}")
    by = {e.get("horizon"): e for e in payload.get("estimates") or []}
    num = lambda h: float((by.get(h) or {}).get("eps_estimate_average") or "nan")  # noqa: E731
    cur, nxt = num("current fiscal year"), num("next fiscal year")
    if not (cur == cur and nxt == nxt) or cur <= 0:
        raise MarketDataError("alphavantage: no usable EPS estimates")
    return {"growth_1y": nxt / cur - 1}


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
                 av_key: str | None = None, damodaran: BytesClient | None = None,
                 finnhub: BytesClient | None = None, finnhub_key: str | None = None):
        self._yahoo, self._alphavantage, self._fred, self._damodaran = yahoo, alphavantage, fred, damodaran
        self._finnhub = finnhub
        self.av_key = av_key if av_key is not None else os.environ.get("ALPHAVANTAGE_API_KEY", "")
        self.finnhub_key = finnhub_key if finnhub_key is not None else os.environ.get("FINNHUB_API_KEY", "")
        self.cache = cache

    # clients are built lazily, so tests and cache-only runs need no network or key
    def _client(self, which: str) -> BytesClient:
        attr = f"_{which}"
        if getattr(self, attr) is None:
            gap = {"yahoo": 0.5, "alphavantage": 1.5, "finnhub": 1.0}.get(which, 0.2)
            setattr(self, attr, HttpClient(BROWSER_UA, min_interval=gap, contact_required=False))
        return getattr(self, attr)

    def _redact(self, msg: str) -> str:
        for k in (self.av_key, self.finnhub_key):
            msg = msg.replace(k, "***") if k else msg
        return msg

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

    def finnhub(self, ticker: str, as_of: date) -> dict:
        """Today's quote and Finnhub's reported beta. No history on the free plan, so an as_of more
        than a week before the quote can't be served."""
        if not self.finnhub_key:
            raise MarketDataError("finnhub: no FINNHUB_API_KEY")
        sym = quote(av_symbol(ticker), safe="")
        q = json.loads(self._get("finnhub", FINNHUB_QUOTE_URL.format(symbol=sym, key=self.finnhub_key), f"finnhub_quote_{sym}_{date.today()}"))
        if not q.get("c") or not q.get("t"):
            raise MarketDataError(f"finnhub: no quote for {ticker}")
        on = datetime.fromtimestamp(q["t"], timezone.utc).date()
        if on > as_of or (as_of - on).days > FINNHUB_MAX_AGE_DAYS:
            raise MarketDataError(f"finnhub: the free plan has today's quote only ({on}), not a close for {as_of}")
        try:
            m = json.loads(self._get("finnhub", FINNHUB_METRIC_URL.format(symbol=sym, key=self.finnhub_key), f"finnhub_metric_{sym}_{date.today()}"))
            beta = (m.get("metric") or {}).get("beta")
        except (MarketDataError, ValueError):
            beta = None
        f = lambda k: float(q[k]) if isinstance(q.get(k), (int, float)) and q[k] else None  # noqa: E731
        return {"source": "finnhub", "currency": "USD", "price": float(q["c"]), "price_date": on.isoformat(),
                "monthly": [], "index": {"symbol": None, "monthly": []},
                "quote": {"source": "finnhub", "date": on.isoformat(), "close": float(q["c"]), "open": f("o"),
                          "day_high": f("h"), "day_low": f("l"), "prev_close": f("pc"), "volume": None,
                          "wk52_high": None, "wk52_high_date": None, "wk52_low": None, "wk52_low_date": None, "avg_volume_3m": None},
                "beta_reported": float(beta) if isinstance(beta, (int, float)) else None}

    def fundamentals(self, ticker: str, as_of: str) -> dict:
        """Annual and quarterly statement items from Yahoo, periods ending on or before as_of."""
        end = date.fromisoformat(as_of)
        types = ",".join(f"{f}{i}" for f in ("annual", "quarterly") for i in FUNDAMENTAL_ITEMS)
        sym = yahoo_symbol(ticker)
        url = FUNDAMENTALS_URL.format(symbol=quote(sym, safe=""), types=types,
                                      p1=_epoch(date(end.year - 6, 1, 1)), p2=_epoch(end + timedelta(days=1)))
        series = parse_fundamentals(json.loads(self._get("yahoo", url, f"yahoo_fund_{sym}_{end}")))
        series = {k: [r for r in v if r["end"] <= as_of] for k, v in series.items()}
        return {"source": "yahoo", "series": {k: v for k, v in series.items() if v}}

    def estimates(self, ticker: str) -> dict:
        """Analysts' earnings growth: Yahoo's five-year estimate, else Alpha Vantage's next-year EPS
        growth (labelled one-year). Today's consensus only: no point-in-time history exists."""
        errors = []
        try:
            sym = yahoo_symbol(ticker)
            got = parse_earnings_trend(json.loads(self._get("yahoo", YAHOO_TREND_URL.format(symbol=quote(sym, safe="")),
                                                            f"yahoo_trend_{sym}_{date.today()}")))
            return {"source": "yahoo", "horizon": "5y", **got}
        except (HttpError, MarketDataError, ValueError, KeyError, IndexError) as e:
            errors.append(self._redact(f"yahoo: {e}"))
        if self.av_key:
            try:
                sym = av_symbol(ticker)
                got = parse_av_estimates(json.loads(self._get("alphavantage", AV_ESTIMATES_URL.format(symbol=quote(sym, safe=""), key=self.av_key),
                                                              f"av_estimates_{sym}_{date.today()}")))
                return {"source": "alphavantage", "horizon": "1y", **got, "errors": errors}
            except (HttpError, MarketDataError, ValueError, KeyError) as e:
                errors.append(self._redact(f"alphavantage: {e}"))
        raise MarketDataError("; ".join(errors) or "no estimates source")

    def risk_free(self, as_of: str, series: str = "DGS10") -> dict:
        """Last 10-year Treasury yield on or before as_of, as a decimal."""
        end = date.fromisoformat(as_of)
        url = FRED_URL.format(series=series, start=end - timedelta(days=14), end=end)
        rows = parse_fred(self._get("fred", url, f"fred_{series}_{end}").decode())
        if not rows:
            raise MarketDataError(f"fred: no {series} observation in the two weeks to {as_of}")
        d, v = rows[-1]
        return {"series": series, "value": v, "date": d, "source": "FRED (Federal Reserve H.15)"}

    def damodaran(self, as_of: str) -> dict:
        """Damodaran's US industry betas and latest implied ERP (L0_ingest/damodaran.py).
        Updated each January, so cached per month."""
        from .damodaran import BETAS_URL, ERP_URL, parse_betas, parse_erp
        month = as_of[:7]
        betas = parse_betas(self._get("damodaran", BETAS_URL, f"damodaran_betas_{month}").decode("utf-8", "replace"))
        erp = parse_erp(self._get("damodaran", ERP_URL, f"damodaran_erp_{month}").decode("utf-8", "replace"))
        return {"source": "Aswath Damodaran, NYU Stern (pages.stern.nyu.edu/~adamodar)", "as_of": as_of,
                "betas": betas, "erp": erp}

    # ------------------------------------------------------------- one company
    def _series(self, which: str, ticker: str, as_of: date) -> dict:
        sym = yahoo_symbol(ticker) if which == "yahoo" else av_symbol(ticker)
        fetch = self.yahoo if which == "yahoo" else self.alphavantage
        got = fetch(sym, as_of - timedelta(days=372 if which == "yahoo" else 14), as_of, "1d")   # a year: the 52-week range
        daily = [r for r in got["rows"] if r[0] <= as_of.isoformat()]
        if not daily:
            raise MarketDataError(f"{which}: no close for {ticker} in the two weeks to {as_of}")
        start = date(as_of.year - BETA_YEARS, as_of.month, 1) - timedelta(days=31)
        m = fetch(sym, start, as_of, "1mo")
        idx_sym = YAHOO_INDEX if which == "yahoo" else AV_INDEX
        idx = fetch(idx_sym, start, as_of, "1mo")
        cut = lambda rows: [(d, a) for d, _, a in rows if d <= as_of.isoformat()]  # noqa: E731
        return {"source": which, "currency": m.get("currency"), "price": daily[-1][1], "price_date": daily[-1][0],
                "monthly": _months(cut(m["rows"])), "index": {"symbol": idx_sym, "monthly": _months(cut(idx["rows"]))},
                "quote": quote_from_bars(got.get("bars") or [], as_of.isoformat(), which)}

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
        for which in ("yahoo", "alphavantage", "finnhub"):
            try:
                doc = self.finnhub(t, end) if which == "finnhub" else self._series(which, t, end)
                break
            except (HttpError, MarketDataError, ValueError, KeyError) as e:
                errors.append(self._redact(f"{which}: {e}"))
        if doc is None:
            raise MarketDataError(f"{t}: no market data ({'; '.join(errors)})")
        doc["fallback"] = doc["source"] != "yahoo"
        doc["check"] = self.check(t, doc) if cross_check and not doc["fallback"] else None
        try:
            doc["estimates"] = self.estimates(t)
        except (HttpError, MarketDataError, ValueError, KeyError) as e:
            doc["estimates"] = None
            errors.append(f"estimates: {e}")
        try:
            doc["fundamentals"] = self.fundamentals(t, as_of)
        except (HttpError, MarketDataError, ValueError, KeyError) as e:
            doc["fundamentals"] = None
            errors.append(f"yahoo fundamentals: {e}")
        return {"schema_version": SCHEMA_VERSION, "ticker": t, "as_of": as_of, **doc, "errors": errors,
                "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}

    def check(self, ticker: str, doc: dict) -> dict:
        """Compare the primary close with Alpha Vantage's on the same day (else Finnhub's quote,
        when it is for that day)."""
        base = {"source": "alphavantage", "tolerance": CHECK_TOLERANCE}
        if not self.av_key and self.finnhub_key:
            base["source"] = "finnhub"
            try:
                got = self.finnhub(ticker, date.fromisoformat(doc["price_date"]))
            except (HttpError, MarketDataError, ValueError, KeyError) as e:
                return {**base, "status": "unavailable", "note": self._redact(str(e))}
            if got["price_date"] != doc["price_date"]:
                return {**base, "status": "unavailable", "note": f"Finnhub's quote is for {got['price_date']}, not {doc['price_date']}"}
            diff = got["price"] / doc["price"] - 1 if doc["price"] else None
            return {**base, "status": "ok" if diff is not None and abs(diff) <= CHECK_TOLERANCE else "mismatch",
                    "price": got["price"], "price_date": got["price_date"], "diff_pct": diff}
        if not self.av_key:
            return {**base, "status": "skipped", "note": "no ALPHAVANTAGE_API_KEY or FINNHUB_API_KEY"}
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
