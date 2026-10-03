# L2 DCF (standalone)

*Status: built. `L2_models/dcf` uses `core/projection`, `core/cost_of_capital`, `core/dcf` and `core/shares`. Inputs are `company_detail.json` and `assumptions/{TICKER}/dcf.json` (see `assumptions/README.md`).*

## Steps

1. **Base period.** The latest TTM, or the latest fiscal year. COGS, SG&A and R&D stay at their ratios to sales. "Other operating" is the residual, so base-year EBIT equals reported operating income. D&A and capex are ratios to sales.
2. **Projection.** The model calls `core.projection`:
   - Revenue grows at g0, fading linearly to terminal growth over N years. Explicit per-year adjustments can replace the fade.
   - Working capital grows by (ΔNWC/ΔSales) × ΔSales. By default that ratio is measured from up to four years of managerial WCR history, falling back to 0.20.
   - The projection runs N + 1 years, and year 1 is the closing year.
3. **Discount rates.** The model calls `core.cost_of_capital`:
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

- `value_per_share`: p10 = conservative, p50 = expected, p90 = aggressive, mean = expected. These are scenario values, not simulated percentiles; Monte Carlo comes later.
- `assumptions_used`: the standard block (forecast path, cost of capital including both WACCs, terminal).
- `details`: rates, bridge, terminal (FCF_T, TV, EV/EBITDA, ROIC), scenarios, projection rows and drivers. The site's Valuation tab shows these.

## Parity (local workbooks)

Checked against the three course cases:

| Check | Result |
|---|---|
| Discount rates (unlevered/relevered beta, cost of equity, weights, both WACCs) | match to 1e-12 |
| Firm DCF: EV, equity, value per share, TV share, terminal value, terminal EV/EBITDA, ROIC, EBITDA margin | match to 1e-9 |
| Scenario range (where the workbook's cached data tables are current) | matches |
| Implied growth (solving g0 for the pre-announcement price) | recovers each workbook's growth input within 0.01% |

## Not yet

- **Data-driven market inputs:** price, Treasury rates and beta are typed into the assumptions file until the market-data adapter exists.
- **Synergy models:** the DCF with synergies and the just-synergies model are next.
