# Sysco: next year's cash flow and standalone value, as of the FY2025 10-K

*A dated study built from the Valuation Model's data and checked outside it. Cutoff: 2025-08-22, the day Sysco filed its fiscal 2025 10-K. Analysis of method, not investment advice.*

**The question.** Standing on 2025-08-22 with only what Sysco had filed, how much cash could the business generate in fiscal 2026 (ending June 2026), which assumptions matter most, and what do they imply for its value as a standalone company?

## Answer

| | Option A: working capital holds at 5.0% of sales | Option B: FY2025's step-up repeats |
|---|---:|---:|
| FY2026 operating cash flow (CFO) | **$2,873M** | **$2,597M** |
| FY2026 free cash flow to the firm (FCFF) | $2,360M | $2,084M |
| Standalone value per share, WACC 6.7% | $94.05 | $82.89 |
| Same, if Sysco is benchmarked to grocery retailers (WACC 7.5%) | $74.94 | $65.52 |

1. **Next year's cash flow turns on one judgment: how much working capital each new dollar of sales ties up.** At the cutoff the three-year evidence said about 4–5 cents (Option A, my choice at the time). FY2025 alone said 16 cents (Option B). That is a $276M swing, about 10% of CFO.
2. **Value turns more on the industry benchmark than on working capital.** Benchmarking Sysco's risk against food wholesalers rather than grocery retailers moves value by about $19 a share. Working capital moves it by about $11.
3. **Scored a year later, my choice was the wrong one.** Sysco reported FY2026 CFO of $2,638M. Option A overshot by 8.9%, Option B missed by 1.5%, and simply repeating FY2025's CFO missed by 4.9%. Inventory and receivables grew faster than sales for a second year, so the FY2025 step-up was not a one-off. One case shows the reasoning can be checked. It does not show the method forecasts well.
4. **The published engine gets Sysco's debt wrong.** The live site values Sysco with zero debt and calls it a lender. The cause is an XBRL tag the engine doesn't read, and this branch fixes it (see [What the engine did](#what-the-engine-did-and-didnt-do)).

## The cash-flow measure

Two measures, kept apart on purpose:

- **CFO** is cash from operations as Sysco reports it: net income + D&A + stock comp − the increase in trade working capital + other items.
- **FCFF** is what a DCF discounts: EBIT × (1 − tax rate) + D&A − capex − the increase in trade working capital. Stock comp is treated as a real cost, so it is not added back.

Trade working capital = receivables + inventory − payables. The bridge between the two, on Sysco's filed numbers ($M):

| | FY2025 | FY2026 |
|---|---:|---:|
| Operating cash flow, as reported | 2,510 | 2,638 |
| Less stock comp | (93) | (118) |
| Plus net interest × (1 − tax rate) | 481 | 554 |
| Less capex | (906) | (700) |
| Less other items in CFO (deferred taxes, accruals, other income) | (8) | (116) |
| **FCFF** | **1,983** | **2,257** |

"Other items" is a plug against FCFF computed directly from EBIT, and it is zero in the forecast by construction. FY2026's $116M of other items is part of the forecast miss.

## Frozen inputs

Everything comes from SEC EDGAR company facts in [`inputs.json`](inputs.json), with the tag, accession and filing date of each number. Only facts filed on or before the cutoff are used, and only their first-filed value, so later restatements can't leak in. FY2026 actuals sit in a separate `outcome` block and are used only for scoring.

| Driver | Value | From |
|---|---:|---|
| FY2026 revenue growth, fading to 2.5% by FY2030 | 3.20% | FY2025 growth |
| EBIT margin, held flat | 3.80% | FY2025 |
| Capex, % of sales | 1.07% | FY2023–FY2025 average |
| Tax rate | 24.3% | FY2025 effective |
| Debt, including finance leases | $13,309M | `DebtAndCapitalLeaseObligations`, FY2025 |
| Shares | 478.2M | 10-K cover, 2025-08-05 |
| Risk-free rate | 4.26% | FRED DGS10, 2025-08-22 |
| Equity risk premium | 4.33% | Damodaran implied ERP at the start of 2025 |
| Unlevered beta | 0.65 | Damodaran "Food Wholesalers", **January 2026 file** |
| Target debt / equity | 0.47 | Damodaran "Food Wholesalers", **January 2026 file** |

**Not available at the cutoff:** Damodaran's January 2025 industry file isn't online, so the beta and debt/equity come from the January 2026 file. Treat them as a later vintage. No market price is used anywhere (the site's data terms), so this study says what the business is worth on its assumptions, not whether the stock was cheap. Operating leases ($1,185M) stay out of debt because their cost stays in EBIT.

## The judgment: working capital per dollar of new sales

| | FY2023 | FY2024 | FY2025 | FY2023–25 |
|---|---:|---:|---:|---:|
| Increase in trade working capital ($M) | 97 | 76 | 393 | 566 |
| Revenue increase ($M) | 7,689 | 2,519 | 2,526 | 12,734 |
| Working capital per $ of new sales | 1.3% | 3.0% | **15.6%** | **4.4%** |

Trade working capital was 5.0% of sales at FY2025. Option A uses that ratio, which is close to the three-year marginal rate of 4.4%. Option B assumes FY2025's 15.6% repeats.

At the cutoff I chose A: three years of evidence against one, and a single-year inventory build (+8.0% against sales +3.2%) looked more likely to unwind than to repeat. Option B was defensible too. FY2026 settled it the other way. Working capital rose $408M, receivables grew 6.6% and inventory 5.6% against sales growth of 3.9%. A forecast for FY2027 made from the FY2026 10-K should weigh the step-up as persistent.

## Standalone value

WACC 6.71% = 68% × cost of equity 8.08% (beta 0.65 relevered to 0.88) + 32% × after-tax cost of debt 3.80%. Five years of FCFF, then a growing perpetuity at 2.5%, which is about 80% of the value. Debt is subtracted and cash added.

| Unlevered beta | 0.55 | **0.65** | 0.75 | 0.85 |
|---|---:|---:|---:|---:|
| WACC | 6.31% | 6.71% | 7.11% | 7.51% |
| Option A, $ a share | 106.62 | **94.05** | 83.67 | 74.94 |
| Option B, $ a share | 94.31 | 82.89 | 73.45 | 65.52 |

This is value as Sysco runs today, before any control premium or buyer's synergies. Precedent deals and synergy values answer a different question (what a buyer might pay) and are left out.

**Why 0.65 rather than 0.85.** Sysco's SIC code is 5140, wholesale groceries. It delivers to restaurants, hospitals and schools and runs no stores. The engine maps that code to Damodaran's "Retail (Grocery and Food)" industry (0.85). I use "Food Wholesalers" (0.65, 13 firms), the closer business. With so few firms in the set, the honest range is the table above, not one number.

## What the engine did and didn't do

**Used as is:** the point-in-time cutoff (`run SYY --as-of`), the FRED and Damodaran adapters, the company facts download and the normalized history. These made the replay possible in a few minutes.

**Had to reinterpret:**
- The published Sysco DCF uses **zero debt**. Sysco files its debt as `LongTermDebtAndCapitalLeaseObligations`, which the concept registry didn't read. Receivables and inventory were missing for the same reason. Coca-Cola, Philip Morris, CVS and Kraft Heinz use the same tags. This branch adds them, with a regression test. With the same code before and after, the engine's Sysco value moves from $117.50 to $93.41 a share at this cutoff, and from $97.90 to $67.96 on the 2026-11-18 data. The effect elsewhere is uneven: CVS falls from $92.11 to $52.38, while Coca-Cola and Philip Morris barely move because the engine's WACC gives the added debt more weight. Adobe's debt is still missing under a different tag.
- The engine calls Sysco a **"financial-style balance sheet"** because liabilities are 87% of assets. That share comes from buybacks, not lending, but the rule sets the DCF's weight to zero, so the site shows no blended value. The fix is a rule change and is proposed, not made (see the backlog item below).
- Replayed at a 2025 date, the engine still uses Damodaran's **2026** ERP and betas. That's a look-ahead the as-of rule doesn't cover yet.

**Done outside the app:** the CFO forecast (the engine forecasts FCFF, not reported CFO), the CFO-to-FCFF bridge, the working-capital options, the industry choice and the scoring against FY2026.

**Not used here and still useful elsewhere:** comps, precedents, synergies and the LBO scaffold. They answer deal and peer-pricing questions this assignment didn't ask.

## Reproduce and challenge it

```bash
python studies/sysco-fy2026/case.py             # prints the case from inputs.json, writes results.json
python studies/sysco-fy2026/case.py --check     # and confirms the workbook agrees ($0.5M, $0.01 a share)
pytest tests/test_study_sysco.py
```

[`sysco_fy2026.xlsx`](sysco_fy2026.xlsx) holds the same model in live formulas: Inputs (filed values with accessions), Drivers (yellow cells are assumptions), Forecast (both options), Bridge, Score and Sensitivity. Change the beta or the working-capital rate on Drivers and the Summary recalculates. To refreeze the inputs from EDGAR: `SEC_USER_AGENT="Name email" python studies/sysco-fy2026/build_inputs.py`.

## Limits

- One company and one year. Scoring one forecast can't establish accuracy.
- Growth and margin are simple carry-forwards. Sysco's own guidance, in its earnings release rather than its XBRL, isn't used.
- The beta and debt/equity are a later vintage than the cutoff.
- Net interest is held flat. Sysco's rose from $635M to $717M in FY2026.
