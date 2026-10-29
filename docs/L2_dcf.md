# L2 DCF (standalone)

*Status: built. `L2_models/dcf` uses `core/projection`, `core/cost_of_capital`, `core/dcf` and `core/shares`. Inputs are `company_detail.json` and `configs/public/assumptions/{TICKER}/dcf.json` (see `configs/public/assumptions/README.md`).*

## Steps

1. **Base period.** The latest TTM, or the latest fiscal year. COGS, SG&A and R&D stay at their ratios to sales. "Other operating" is the residual, so base-year EBIT equals reported operating income. D&A and capex are ratios to sales.
2. **Projection.** The model calls `core.projection`:
   - Revenue grows at g0, fading linearly to terminal growth over N years. Explicit per-year adjustments can replace the fade.
   - Working capital grows by (ΔNWC/ΔSales) × ΔSales. By default that ratio is measured from up to four years of managerial WCR history, falling back to 0.20.
   - The projection runs N + 1 years, and year 1 is the closing year.
3. **Discount rates.** The model calls `core.cost_of_capital`:
   - Pre-tax cost of debt is interest expense ÷ total debt from the base period, unless a number is given. If that can't be measured, a fallback (bond yield to maturity) is required. A rate below the risk-free rate is flagged.
   - Beta is unlevered at today's market D/E and relevered at the target D/E.
   - Cost of equity is r_f + β × MRP.
   - The pre-terminal WACC uses today's r_f.
   - The terminal-year WACC uses a normalized r_f,T, with the debt spread kept.
4. **Value.** The model calls `core.dcf`:
   - Each year's FCF is discounted at the pre-terminal WACC with exponent (t − 1).
   - The terminal value is FCF_T × (1 + g) / (WACC_T − g), where FCF_T = EBITDA(1 − t) − Sales × capex%(1 − t) − Sales × g × ΔNWC/ΔSales. It is discounted with the last year's exponent.
   - Equity value = EV − (debt − cash beyond operating needs).
   - Value per share = equity value / diluted shares, with dilution by the treasury stock method.
5. **Range.**
   - **Conservative** blends (g0 − 1%, WACC + 1%) with (g_T − 0.5%, WACC_T + 0.5%), weighted by the terminal value's share of EV.
   - **Aggressive** is the mirror image.
   - **Expected** is the base value.

## Modes

- **forecast:** your g0 gives a value per share.
- **implied:** solves g0 so that value equals `market.price` (bisection over −50% to +100%), then builds the range around it. This is the course's practice of calibrating the standalone DCF to the pre-announcement price.

## Output

`model_results/dcf.json` holds:

- `value_per_share`: p10 and p90 = the 10th and 90th percentiles of the simulation, p50 = the stated (expected) case, mean = the simulation mean. p50 stays deterministic so it matches the course workbooks.
- `assumptions_used`: the standard block (forecast path, cost of capital including both WACCs, terminal).
- `details`: rates, bridge, terminal (FCF_T, TV, EV/EBITDA, ROIC), `scenarios` (the course's conservative / expected / aggressive method, kept for parity), `simulation`, projection rows, drivers and the sensitivity grid. The site's Results → Valuation view shows these.

## Simulation

`DCFModel.simulate` reruns the firm DCF many times. Revenue comes from a calibrated table of the model's past misses; WACC and terminal growth are drawn from triangular distributions centred on the stated case. Draws go through `_core/simulation.py` (`rng(seed)`, `sample`, `summarize`, `histogram`), pure Python with the same interface as the Shared Core numpy version, so the same inputs and seed give the same numbers everywhere.

| Input | Default range | Note |
|---|---|---|
| Revenue path | calibrated (below) | ±3 pts on g0 (triangular) when the table is off |
| WACC | ±1.5 pts | the terminal WACC shifts by the same amount |
| Terminal growth | ±0.75 pt | |

- **Calibrated revenue.** `configs/public/calibration/revenue_errors.json` (from the forecast-accuracy study in `Courtizy/research`) holds quantiles of ln(actual / forecast) by years out (1–5), divided by a company scale = standard deviation of yearly log revenue growth over up to six years + 0.10. Each run draws one percentile u and multiplies every year's revenue by exp(quantile_h(u) × scale); years past 5 keep year 5's level. Out of sample, a range built this way for 90% held 88–93% of outcomes; the old ±3-pt growth wobble's 80% range held about 14%. `details.simulation.revenue_range.bands` gives the 80% and 90% revenue ranges by year as multipliers of the stated case. Turn it off with `"revenue_errors": false`, or by setting `growth` explicitly.
- 2,000 runs, seed 7 (500 runs for demo peers to keep the deploy fast).
- A run is dropped when the terminal WACC is not at least 0.5 pt above terminal growth; `runs_used` reports what's left.
- Override per ticker in `dcf.json`: `{"simulation": {"runs": 5000, "seed": 11, "wacc": {"dist": "triangular", "low": 0.08, "mode": 0.09, "high": 0.11}}}` (`growth`, `wacc`, `terminal_growth` take a full spec; `growth_spread` etc. take a width).
- `details.simulation` = `{runs, runs_used, seed, inputs, per_share (mean, p5…p95), middle_80, middle_90, revenue_range, terminal_value_share, histogram {counts, edges, below, above}, base_per_share}`. The histogram spans p0.5–p99.5; runs outside it are counted in `below` / `above`.
- The site's headline range is `middle_80` (10th–90th percentile) with `middle_90` beside it; the football field's DCF bar is p10–p90 with a thin p5–p95 line. `revenue_range.tested` carries the study's out-of-sample hit rates for the 80 / 90 / 95% revenue ranges, which the site prints beside them.
- `details.momentum` (fade only) and `details.yardstick.flat_revenue_per_share` (revenue flat for five years, then the fade's rates) sit beside the blended base case.

## Parity (local workbooks)

Checked against the three course cases:

| Check | Result |
|---|---|
| Discount rates (unlevered/relevered beta, cost of equity, weights, both WACCs) | match to 1e-12 |
| Firm DCF: EV, equity, value per share, TV share, terminal value, terminal EV/EBITDA, ROIC, EBITDA margin | match to 1e-9 |
| Scenario range (where the workbook's cached data tables are current) | matches |
| Implied growth (solving g0 for the pre-announcement price) | recovers each workbook's growth input within 0.01% |

## Course checks (`_core/checks.py`, `details.checks`)

Each check has a status (good / warning) the site shows with an icon and a label:

| Check | Rule |
|---|---|
| Terminal growth | its band against a 4-6% nominal economy: with the economy 3.5-4.5%, slower 2.4-3.5%, flat real 1.5-2.4%, negative real 0-1.5%, rapid decline below 0. Above 4.5% is flagged: no firm outgrows the economy forever |
| Growth when the terminal value starts | the last forecast year's growth should be at steady state, 5% or below |
| Terminal value share of EV | usually 50-75% in a 10-year projection |
| Implied exit EV/EBITDA vs public comps | within 25% of the comps average (`comparison.json` → `cross_checks.exit_multiple`); exit multiples are usually too high |
| Year 1 revenue vs the seasonal model | reported quarters after the base year plus a Foster forecast for the rest, Q_t = Q_t-4 + δ + φ(Q_t-1 - Q_t-5), fit by OLS on the latest unbroken run of at least 10 quarters (`_core/stats.py`, `details.seasonal`) |

## Tornado (`details.tornado`)

Seven inputs moved one at a time, sorted by swing: WACC in both periods ±1.5 points, near-term revenue growth ±3 points, EBITDA margin ±2 points, terminal growth ±0.8 points, capex / sales ±1 point, terminal WACC ±0.5 points, ΔNWC / Δsales ±10%. Steps are in `TORNADO` in `L2_models/dcf/__init__.py`.

## Discount-rate options

- **Country risk premium:** `cost_of_capital.country_risk_premium` is added to the cost of equity in both periods.
- **Synthetic rating:** when interest / debt can't be measured (or `cost_of_debt_method: "rating"`), the pre-tax cost of debt is the risk-free rate plus the spread for the rating EBIT / interest suggests (`RATING_TABLE`, Damodaran's large-firm shape; `cost_of_capital.rating_spreads` overrides). `details.synthetic_rating` shows the coverage, rating and spread either way.
- **Private firm:** `"private": {"r_squared": 0.25, "discount": 0.25}` uses total beta = market beta / √R² (a private owner isn't diversified; `"total_beta": false` keeps the market beta) and takes the illiquidity discount (25% default) off the value per share.
- **Finite life:** `forecast.life_years` turns the terminal value into a growing annuity over that many years: TV × (1 - ((1+g)/(1+r))^L).

## Simulation precision

`simulation.per_share` adds the standard deviation, the standard error of the mean and its 95% interval (mean ± 1.96 se), shown under the KPIs.

## Default case (no dcf.json)

When `configs/public/assumptions/{TICKER}/dcf.json` doesn't exist, the runner values the company on `default_assumptions(detail)` instead of skipping the DCF:

| Input | Default |
|---|---|
| Mode | forecast |
| Revenue growth | **blend** for years 1–5: the geometric mean of no change, the fade (the company's historical revenue CAGR from the L1 trend case, capped to −5%…20%, fading to 2.5% over 10 years) and its sector's growth (median three-year CAGR of large filers in its SIC division, `configs/public/calibration/sector_growth.json`; the fade again when there's none). Years 6–10 grow at the fade's rates. Out of sample the blend beat no change by 7% three years out and 12% five years out; the fade alone did not, and it over-forecast the fastest growers by about 23% |
| Equity risk premium | Damodaran's implied ERP (FCFE) for the start of the year (company detail `equity_risk_premium`), else 5% |
| Risk-free | FRED 10-year Treasury on or before as_of (company detail `risk_free`) |
| Beta | market beta when prices are allowed; else Damodaran's US unlevered industry beta (cash-corrected), relevered at the company's own D/E (`discount_rates(beta_unlevered=...)`); else the sector's illustrative beta |
| Cost of debt | interest / debt from the filings, else risk-free + 1.5% |
| Shares | newest filed share count (cover page) |
| Costs, capex, tax, working capital | from the filings, as in any DCF |

`details.momentum` keeps the fade-only value per share (the company's own growth carried forward) beside the blended base case. A `dcf.json` opts in with `"forecast": {"revenue_method": "blend", "sector_growth": 0.03}`.

The result carries `default_case: true`, its first note says so, and the site tags the DCF card **Default Assumptions**. Adding a `dcf.json` always replaces the default case.

**No market price (showcase mode or no data):** today's D/E is solved at the model's own equity value: D/E = debt / equity value from a DCF at the WACC that D/E implies, iterated to a fixed point (`debt_to_equity_basis: "model equity value"`). Book D/E isn't used, because buybacks leave many companies (Dell, for one) with tiny or negative book equity.
