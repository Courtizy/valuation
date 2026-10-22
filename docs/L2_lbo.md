# L2 LBO (what a financial sponsor could pay)

`L2_models/dcf/lbo.py` on the math in `_core/lbo.py` (course Week 7 LBO model and Week 9 LBO review). It starts from the standalone DCF's inputs (`dcf.json` or the default case) and reads the sponsor's assumptions from `lbo.json` (`configs/public/assumptions/{TICKER}/lbo.json`, or the Deal page's LBO inputs).

## Inputs (`lbo.json`)

| Key | Default | Meaning |
|---|---|---|
| `sponsor_irr` | 0.20 | target return in place of WACC (15-25% typical) |
| `hold_years` | 5 | years to the exit |
| `offer_premium` | 0.30 | over the pre-announcement (else today's) price |
| `exit_multiple_change` | 0 | exit EV/EBITDA = today's multiple + this |
| `coverage` | 2.0 | EBIT / interest the lenders allow |
| `securable_assets` | filings | PP&E + receivables + inventories, else assets - goodwill - intangibles - cash |
| `pct_secured`, `sub_to_senior` | 1.0, 0.6 | senior up to securable × %; subordinated = 60% of senior |
| `senior_rate`, `rate_step` | DCF cost of debt, 0.03 | subordinated + 1 step, mezzanine + 2 |
| `fees` | 0.02 | of new debt |
| `steps` | 0 | `growth_add`, `margin_add` (COGS share cut), `capex_add`, `nwc_change` (year-1 share of working capital released, e.g. -0.10) |

## Math

- **Debt** is sized at close on base-year EBIT: senior capped by collateral, subordinated a share of senior, mezzanine fills until EBIT / interest = coverage. If senior and subordinated alone break the coverage, both shrink and there is no mezzanine.
- **Each year:** interest on the average balance (solved by iteration, the model's circularity); cash taxes = tax × (EBIT - interest); cash for debt = EBITDA - capex - ΔNWC - interest - taxes; the sweep pays senior, then subordinated, then mezzanine; anything left goes to the sponsor.
- **PEMV(r)** = Σ to sponsor_t / (1+r)^t + (EBITDA_H × exit multiple - remaining debt) / (1+r)^H.
- **Max price** at the target IRR = (PEMV + LBO debt - net debt - fees) / shares. **IRR at the offer** solves PEMV(r) = offer × shares + net debt + fees - LBO debt.
- The premium moves the IRR but not the max price; the target IRR moves the max price but not the IRR.

## Output

`value_per_share`: max price at IRR + 5 points (conservative), at the IRR (expected), at - 5 points (aggressive). `details`: debt (tranches, rates, leverage, coverage), sources and uses, the yearly schedule, exit, `max_price`, `max_premium`, `irr_at_offer`, money multiple, the standalone DCF per share, and two grids: max price by sponsor IRR × exit multiple change, IRR at the offer by coverage × exit multiple change.

Notes flag years where cash doesn't cover interest, and when collateral keeps coverage above the target.
