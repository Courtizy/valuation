# core/projection.py: Three-Statement Projection

*Status: built. Shared math for every L2 model. Stdlib only, and imports no layer (tested).*

## Purpose

Takes a base year plus drivers and returns projected:

- income statement
- balance sheet
- cash-flow statement
- managerial balance sheet
- unlevered free cash flow

Each model owns its drivers (its forecast). This module only turns drivers into statements, so the same drivers always give the same statements.

```python
from core.projection import base_from_detail, project
base = base_from_detail(detail["views"]["ttm"][-1]["values"])
out = project(base, drivers, years=10)   # out["years"][i]: statements for year i+1
```

## Drivers

| Item | Methods |
|---|---|
| revenue | `growth` (rates), `fade` (g0 → g_terminal linearly over fade_years; optional per-year `adjust` replaces the fade), `values` |
| cogs, sga, rnd, other_opex | `pct_of_sales` (value or null = base ratio; optional per-year `adjust`), `same_as_base` |
| depreciation, amortization | `pct_of_sales`, `pct_of_fixed_assets` (beginning FA), `same_as_base` |
| costs_include_da | true (cost lines contain D&A: EBITDA = sales − costs + D&A) / false |
| interest | `rate_on_debt` (beginning or average basis; average iterates to a fixed point), `pct_of_sales`, `same_as_base` |
| tax_rate | number or per-year list |
| cash | `pct_of_sales`, `same_as_base`, `min` (floor under a cash/revolver plug) |
| receivables | `pct_of_sales`, `days` |
| inventory | `pct_of_sales`, `turnover` (COGS/Inv), `days` |
| payables | `pct_of_sales`, `days_purchases` (purchases = COGS + ΔInv) |
| nwc | `items` (default) or `incremental`: WCR_t = WCR_t-1 + k × ΔSales |
| capex | `pct_of_sales`, `replacement` (= D&A) |
| fixed_assets | `roll_forward` (FA + capex − D − A), `same_as_base`, `pct_of_sales` (capex implied) |
| debt, other LT liabilities | `same_as_base`, `schedule` |
| dividends | `payout` share of net income |
| plug | `equity` / `cash` / `revolver` |
| amortization_tax_deductible, provisions | FCF adjustments |

## Outputs per year

- All statement lines, plus `cash_flow` (CFO, CFI, CFF, and a `ties` flag)
- `managerial` (cash, WCR, fixed assets, invested capital, capital employed)
- `free_cash_flow`: EBITDA(1 − t) + D·t + A·t·deductible − capex − ΔNWC − provisions
- `balance_check` (invested capital − capital employed, should be 0)

## How the course methods map to drivers

| Course method | Drivers |
|---|---|
| Course DCF (sales-driven) | `fade` revenue with the template's adjustment row, cost lines / D&A / capex as `pct_of_sales` with common-cost ratios, `nwc: incremental`, `costs_include_da: true` |
| Pro forma balance-sheet forecast | `values` revenue, `costs_include_da: false`, `turnover` inventory, `days_purchases` payables, `same_as_base` FA / debt, `plug: equity` |

## Parity results (local workbooks, `tests/test_course_parity.py`)

| Check | Result |
|---|---|
| One-year pro forma BS and MBS projection | all lines match |
| Operating and financial ratios (two years) | all match |
| MBS free cash flow (two years) | all match |
| Reformulated ratio definitions (4 years, average and beginning) | all match |
| Firm DCF rows: sales, EBITDA, D, EBIT, capex, ΔNWC, FCF, years 0–10, three companies | match to 1e-9 |

Run with `VALUATION_COURSE_DIR=<folder holding the course folders>`. Tests skip when the variable is unset.
