# L2 Reconcile: Profile-Driven Triangulation

*Status: built. Inputs are `model_results/*.json`, `company_detail.json` (profile and price) and an optional `inputs/assumptions/{TICKER}/reconcile.json`. Output is `comparison.json` (schema 0.2.0).*

## Principle

No single method. Every valuation has a **primary** method and at least one **cross-check**; anything else is **reference** with zero weight. The choice follows the company's **characteristics**, not its sector label.

## Company profile (L1, `L1_detail/profile.py`)

| Trait | Measured from | Labels |
|---|---|---|
| Stage | revenue CAGR (up to 5 fiscal years), operating margin | high growth (> 15% or unprofitable), mature grower (3–15%), mature (0–3%), declining (< 0) |
| Cash-flow predictability | FCF (CFO − capex) by year: share positive, FCF-margin stdev | high (≥ 80% positive and ≤ 3 pts), low (≤ 50% or ≥ 8 pts), medium |
| Asset intensity | capex/sales, NOA turnover | light (< 3% and > 3x), heavy (> 10% or < 1x), moderate |
| Capital structure | debt/EBITDA, liabilities/assets | financial (liabilities ≥ 85% of assets), low (< 2x), moderate, high (> 4x or EBITDA ≤ 0) |

The thresholds are in `L1_detail/profile_rules.json`, and a pack can override them under `l1.profile_rules`. Each trait records its measures and the rule that fired.

## Method plan (`L2_models/reconcile/methods.py`)

| Profile | Primary | Cross-check | Why |
|---|---|---|---|
| Financial-style balance sheet | comps (P/B, P/E) 100% | DCF reference | for a lender, debt is operating, so a WACC/FCF DCF misreads it |
| High growth or low predictability | comps 60% | DCF 40% | multiples anchor better than distant cash flows; the DCF tests the multiple |
| Declining | DCF 50% (short horizon) | comps 50% | asset or liquidation value is the floor to check |
| Mature or mature grower, high predictability | DCF 60% | comps 40% | steady positive FCF is the most direct measure |
| Otherwise (medium) | DCF 50% | comps 50% | |

**Standalone context (default).** Precedent transactions and LBO are reference only: precedents include a control premium, and an LBO prices what a financial buyer could pay.

**Acquisition context** (`"context": "acquisition"`). This is the course's offer-price view: just synergies 33%, DCF with synergies 33%, precedents (premium paid) 34%, with LBO and standalone DCF as reference.

**Missing methods.** Weights for methods that didn't run are dropped, and the rest renormalized, as the course summary does with blank rows.

**Overrides.** `inputs/assumptions/{TICKER}/reconcile.json` can replace the weights, for example `{"weights": {"dcf": 0.7, "comps": 0.3}}`. Roles then follow the weights.

## Output additions (schema 0.2.0)

- `profile`: the L1 profile.
- `plan`: context, summary, and the methods list (role, weight, default weight, reason, ran, value_per_share).
- `blend`: weighted P10 / P50 / P90, shown on the site as Bear / Base / Bull.
- `price`, `price_source` and `upside` per scenario.

## Pipeline

Models are soft steps: one model failing (or not built) doesn't stop the others, and reconcile blends whatever finished.

## Site (Valuation tab)

1. **Value vs price.** Price, blended value for the selected scenario, and upside, with the primary and cross-check methods named.
2. **Football field.** One row per method: a bar from bear to bull, a tick at the selected scenario and a dashed line at the price. Each row also shows the bear–bull range, the selected value, its upside, the weight and the reason for its role. A blended row comes last, and the Bear / Base / Bull toggle drives both cards.
3. **Company profile.** The four traits, each with its measures and the rule that fired, followed by "so: primary / cross-check" with reasons.
4. **DCF detail.**
5. **Similar companies.** Every company published on the site, ranked by closeness of profile measures (z-scored growth, margin, FCF stability, capex intensity, NOA turnover, leverage, size), not by sector. Each row shows multiples (P/E, EV/EBITDA, EV/Sales, P/B, FCF yield), rates (growth, margin, RNOA, debt/EBITDA, WACC) and a peer median.
