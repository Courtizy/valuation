# Assumptions

One folder per ticker, one file per model: `assumptions/{TICKER}/{model}.json`.
Copy from `_template/` and fill it in. The pipeline stops at a model whose
file is missing and names the file it expected.

## dcf.json

| Key | Meaning |
|---|---|
| `mode` | `forecast` (your growth gives a value) or `implied` (solve growth so value = price) |
| `base_period` | `annual` (default: the last reported fiscal year, so Year 1 = the fiscal year in progress, the closing year) or `ttm` (latest twelve months) |
| `market.price`, `price_date` | share price used for market D/E, the TSM and implied mode |
| `market.basic_shares` | overrides the share count from filings |
| `market.options` | `[[options_outstanding, weighted_avg_strike], ...]` for the treasury stock method |
| `forecast.years_to_terminal` | N; the projection runs N + 1 years (year 1 is the closing year) |
| `forecast.revenue_growth` | near-term growth g0; fades linearly to terminal growth over N years |
| `forecast.growth_adjust` | optional per-year adjustments replacing the fade (all zeros = constant g0) |
| `forecast.terminal_growth` | Gordon growth after year N |
| `forecast.cost_pct_revenue` | optional overrides, e.g. `{"cogs": 0.6}`; default is the base period's ratio |
| `forecast.capex_pct_revenue`, `nwc_to_sales_change`, `tax_rate` | null = from the filings |
| `cost_of_capital.risk_free` | today's long-term government rate |
| `cost_of_capital.risk_free_terminal` | normalized long-run rate for the terminal-year WACC (null = same) |
| `cost_of_capital.beta`, `equity_risk_premium` | CAPM inputs |
| `cost_of_capital.pre_tax_cost_of_debt` | null (default) = interest expense / total debt from the filings; a number overrides it |
| `cost_of_capital.pre_tax_cost_of_debt_fallback` | used only when interest / debt can't be measured, e.g. bond yield to maturity |
| `cost_of_capital.target_debt_to_equity` | long-run D/E to relever beta and weight WACC (null = today's) |
| `bridge.operating_cash_pct` | share of cash needed to run the business, not netted against debt (default 0.5) |
| `bridge.include_longterm_investments` | count long-term investments (non-current marketable securities) as cash in the bridge (default false) |
| `terminal.weight` | share of the terminal value to count (default 1) |
| `discounting.convention` | `closing_year_zero` (default), `end_of_year`, `mid_year` |
| `sensitivity.*` | step sizes for the conservative / aggressive range |

## reconcile.json (optional)

```json
{"context": "standalone", "weights": {"dcf": 0.7, "comps": 0.3}}
```

Without it, the company profile sets the primary method, cross-check and weights (`docs/L2_reconcile.md`). `context` is `standalone` (default) or `acquisition` (offer-price view: synergy methods and precedents).

## comps.json

| Key | Meaning |
|---|---|
| `peers` | tickers, or objects. A ticker's figures come from its SEC filings (the pipeline ingests it first); `price` (and `shares` if filings lack it) must be given. `"sec": false` = manual peer: give `price`, `shares`, `debt`, `cash`, `sales`, `ebitda`, `net_income` |
| `target.shares`, `market.price` | target share count (default from filings) and price (for upside) |
| `multiples` | any of `ev_ebitda`, `ev_sales`, `pe` (default EV/EBITDA and EV/Sales) |
| `weights` | blend weights per multiple (default equal) |
| `range` | `min_max` (course: lowest / median / highest implied price) or `quartiles` |

Any SEC-derived figure can be overridden by typing it into the peer's object.
