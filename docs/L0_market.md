# Market Data

Share prices, beta and the risk-free rate, point-in-time at `as_of`. Code: `src/valuation/L0_ingest/market.py` (fetch), `src/valuation/_core/market.py` (beta, WACC estimate), `src/valuation/L1_detail/build.py` (market block).

## Sources

| Role | Source | Key | Notes |
|---|---|---|---|
| Primary prices | Yahoo chart API (`query1.finance.yahoo.com/v8/finance/chart`) | none | the endpoint yfinance uses; unofficial |
| Backup + cross-check | Alpha Vantage (`TIME_SERIES_DAILY` compact, `TIME_SERIES_MONTHLY_ADJUSTED`) | free, `ALPHAVANTAGE_API_KEY` secret | free plan: 25 requests a day; the daily series covers the latest 100 trading days. The key must go in the URL, so it is redacted from every stored message |
| Risk-free rate | FRED `DGS10` (10-year Treasury, H.15) | none | last observation on or before `as_of` |
| Index for beta | S&P 500 (`^GSPC`) on Yahoo; `SPY` on Alpha Vantage (no index series) | | |

## Rules

- **Price** = the last close on or before `as_of`. A past `as_of` never sees later prices.
- **Fallback:** when Yahoo fails or returns nothing, Alpha Vantage becomes the source and the site says so (3 requests: daily, monthly, SPY monthly).
- **Cross-check:** for the company being run and its comps peers, Alpha Vantage's close for the same day is compared with Yahoo's (1 request each, cached for the day). Within 2% = `ok`, otherwise `mismatch` (shown in red next to the price). With no key the check is `skipped`; past the daily cap, or for an as-of date older than ~100 trading days, it is `unavailable`.
- **Budget:** 25 requests a day, shared across every run that day: a company plus 6 peers uses 7 checks, so about three such runs a day, fewer if fallbacks are needed. Rate-limit notices come back as HTTP 200 with an `Information` or `Note` key and are treated as unavailable, never as data.
- **Optional step:** if both sources fail, the run continues without market figures and reports a warning, not a failure.
- **Share count** = the newest filed count (the 10-K/10-Q cover page), so market cap = price × shares outstanding.

## Yahoo as the backup after SEC filings (private runs)

With prices allowed (`--market all`), the market step also pulls Yahoo's fundamentals timeseries (`query1.finance.yahoo.com/ws/fundamentals-timeseries`, no key) into `raw_market.json` → `fundamentals`. L1 (`src/valuation/L1_detail/backfill.py`) then fills gaps:

- **Only gaps:** a Yahoo value is added only where no filed record exists for the same concept and period. Filed values always win.
- **Only filed periods:** the fiscal year and quarter labels come from the SEC record with the same end date (within 7 days, for 52/53-week years), so Yahoo can never add or relabel a period. A company the filings don't cover (a 20-F filer in IFRS) stays unsupported.
- **Point-in-time:** Yahoo gives no filing date, so a period counts only 60 days after a fiscal year end and 40 after a quarter end.
- **Items:** revenue, cost of revenue, gross profit, operating income, D&A, interest expense and income, pretax income, tax, net income, R&D, SG&A, operating cash flow, capex (sign flipped to the filed convention), cash and short-term investments, debt, equity, total assets and liabilities, current assets and liabilities, shares outstanding and diluted average shares. Derived lines (EBITDA, FCF) recompute from them.
- **Shown as `y`** on the statements; company detail lists every filled value under `backfill`.
- **Never public:** showcase runs don't call Yahoo, and `publish` in showcase mode skips any run that carries backfill.

Prices for comps peers and beta already come from Yahoo in the same private runs.

## Derived figures (L1)

| Figure | Rule |
|---|---|
| Beta | 60 monthly returns on adjusted closes vs the index; `cov / var`; needs 24+ months. AAPL to 2026-10-02: 1.08 (Yahoo shows 1.09) |
| Market cap, EV | price × shares; EV = market cap + debt − cash |
| WACC estimate | r_E = r_f + beta × 5%; r_D = interest / debt when it lands between r_f and r_f + 10%, else r_f + 1.5%; market equity and book debt weights; tax = effective rate if 0–50%, else 21% |

The WACC estimate fills tables (Similar Companies). The DCF keeps its own cost of capital: market data fills `market.price`, `cost_of_capital.beta` and `cost_of_capital.risk_free` only when the assumptions file leaves them `null`, and the file always wins. Comps takes each peer's price the same way; a price typed in `comps.json` overrides it.

## Files

```
data/{TICKER}/{as_of}/raw_market.json     L0: price, monthly adjusted closes, index series, check, errors
data/_market/{as_of}/risk_free.json       L0: DGS10 on or before as_of
company_detail.json → market              L1: price, date, source, check, shares, market cap, beta, WACC estimate
```

## What reaches the public site: showcase mode (default)

Yahoo's terms bar automated collection and commercial reuse, and Alpha Vantage's free key covers private, individual use only. A public showcase goes beyond both, so by default **no real market figures are published**:

- The Pipeline action runs with `--market risk-free`: only the FRED rate is fetched, no prices.
- The DCF then runs without a price: beta = the sector's illustrative beta (`configs/public/sectors/taxonomy.json` → `typical_beta`, carried in company detail as `sector_beta`), today's D/E = the target D/E or book D/E, and implied mode falls back to forecast mode. Values are intrinsic only; there is no upside against a price.
- Comps runs only with prices you typed into `comps.json`.
- `publish --market-data showcase` also strips any real market block, market-based price and upside, and any comps result built on market prices, in case a run with prices is published by mistake.
- The synthetic examples (DEMO, DEMOG, DEMOU) keep made-up but reproducible market figures: their demo price, the sector beta, a WACC at a fixed 4.5% risk-free rate, all labelled "Synthetic Example".
- The footer carries FRED's required notice.

**Real mode:** set the repository variable `SITE_MARKET_DATA` to `real` (Settings → Secrets and variables → Actions → Variables) only for a private site or with licensed data. Runs then fetch prices (`--market all`) and publish real figures. Locally, `python -m valuation run …` fetches prices by default; `--market risk-free` mirrors the public site.

## Setup

Add the repository secret **`ALPHAVANTAGE_API_KEY`** (free key from alphavantage.co). Without it, Yahoo still supplies prices; there is no backup or cross-check.
