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

`DCFModel.simulate` reruns the firm DCF many times with three inputs drawn from triangular distributions centred on the stated case. Draws go through `_core/simulation.py` (`rng(seed)`, `sample`, `summarize`, `histogram`), pure Python with the same interface as the Shared Core numpy version, so the same inputs and seed give the same numbers everywhere.

| Input | Default range | Note |
|---|---|---|
| Near-term growth (g0) | ±3 pts | the fade path shifts with it |
| WACC | ±1.5 pts | the terminal WACC shifts by the same amount |
| Terminal growth | ±0.75 pt | |

- 2,000 runs, seed 7 (500 runs for demo peers to keep the deploy fast).
- A run is dropped when the terminal WACC is not at least 0.5 pt above terminal growth; `runs_used` reports what's left.
- Override per ticker in `dcf.json`: `{"simulation": {"runs": 5000, "seed": 11, "wacc": {"dist": "triangular", "low": 0.08, "mode": 0.09, "high": 0.11}}}` (`growth`, `wacc`, `terminal_growth` take a full spec; `growth_spread` etc. take a width).
- `details.simulation` = `{runs, runs_used, seed, inputs, per_share (mean, p5…p95), middle_90, terminal_value_share, histogram {counts, edges, below, above}, base_per_share}`. The histogram spans p0.5–p99.5; runs outside it are counted in `below` / `above`.
- The site's headline range is `middle_90` (5th–95th percentile); the football field's DCF Bear / Bull are p10 / p90.

## Parity (local workbooks)

Checked against the three course cases:

| Check | Result |
|---|---|
| Discount rates (unlevered/relevered beta, cost of equity, weights, both WACCs) | match to 1e-12 |
| Firm DCF: EV, equity, value per share, TV share, terminal value, terminal EV/EBITDA, ROIC, EBITDA margin | match to 1e-9 |
| Scenario range (where the workbook's cached data tables are current) | matches |
| Implied growth (solving g0 for the pre-announcement price) | recovers each workbook's growth input within 0.01% |

## Not yet

- **Synergy models:** the DCF with synergies and the just-synergies model are next.

## Default case (no dcf.json)

When `configs/public/assumptions/{TICKER}/dcf.json` doesn't exist, the runner values the company on `default_assumptions(detail)` instead of skipping the DCF:

| Input | Default |
|---|---|
| Mode | forecast |
| Revenue growth | the company's historical revenue CAGR from the L1 trend case, capped to −5%…20%, fading to 2.5% over 10 years |
| Equity risk premium | 5% |
| Risk-free | FRED 10-year Treasury on or before as_of (company detail `risk_free`) |
| Beta | market beta when prices are allowed, else the sector's illustrative beta |
| Cost of debt | interest / debt from the filings, else risk-free + 1.5% |
| Shares | newest filed share count (cover page) |
| Costs, capex, tax, working capital | from the filings, as in any DCF |

The result carries `default_case: true`, its first note says so, and the site tags the DCF card **Default Assumptions**. Adding a `dcf.json` always replaces the default case.

**No market price (showcase mode or no data):** today's D/E is solved at the model's own equity value: D/E = debt / equity value from a DCF at the WACC that D/E implies, iterated to a fixed point (`debt_to_equity_basis: "model equity value"`). Book D/E isn't used, because buybacks leave many companies (Dell, for one) with tiny or negative book equity.
