# Valuation L1 Stage 2: Company Detail

*Status: built. Input `canonical_statements.json` (+ optional `raw_market.json`) → output `company_detail.json` (schema 0.1.0).*

## Usage

```bash
python -m valuation.L1_detail build data/AAPL/2026-09-30/canonical_statements.json --as-of 2026-09-30 \
    --out data/AAPL/2026-09-30/company_detail.json [--market raw_market.json] [--pack configs/public/packs/default.json]
python -m valuation.L1_detail validate-detail data/AAPL/2026-09-30/company_detail.json
```

The pipeline runs the same function as its "build detail" step.

## 1. Frequency views (`periods.py`)

| View | Rule |
|---|---|
| annual | 12-month periods; balance-sheet items at the fiscal year end |
| quarterly | 3-month periods. Unreported quarters are derived from YTD: Q2 = 6M − Q1, Q3 = 9M − 6M (`ytd_derived`), Q4 = FY − 9M (`q4_derived`) |
| ttm | four contiguous quarters summed; instants at the last quarter end |

- **Fiscal calendar.** Built from the YTD chains of every additive concept, so one sparse line can't hide a quarter. Cash-flow lines in 10-Qs are YTD only, which is why Q2 and Q3 derivation matters.
- **Additive items only** are differenced or summed: monetary durations, reported or memo. Shares, per-share figures and ratios are taken only where reported for that exact period.
- **Derived concepts** (EBITDA, FCF proxy, net debt, effective tax rate) are recomputed in every view period from that period's own values.
- **Labels.** Every period keeps its fiscal label and adds `calendar_year` / `calendar_quarter`. Period ends in the first week of a month count toward the prior month.
- **Traceability.** `methods` records how each value was obtained; `restated` lists concepts whose value changed in a later filing.

## 2. Analysis (`analysis.py`)

Runs on every 12-month period (annual and TTM). Average-based ratios use the period one year earlier, checked to be 350–380 days apart. Missing inputs give `null`, never zero.

### Managerial balance sheet

**Cash + WCR + Fixed assets = Invested capital = STD + LT financing + Equity**

- WCR = (current assets − cash) − (current liabilities − short-term debt)
- Fixed assets = total assets − current assets

**Ratios:**

- NLF = equity + LT financing − fixed assets
- NSF = STD − cash
- Liquidity ratio = NLF / WCR
- WCR / sales
- Collection period = AR / (sales / 365)
- Days inventory = Inv / (COGS / 365); inventory turnover = COGS / Inv
- Payment period = AP / (purchases / 365), where purchases = COGS + ΔInv
- Current ratio, acid test

**FCF (MBS)** = EBIT(1 − t) + depreciation − ΔWCR − capex, with capex = ΔFixed assets + depreciation.

### Reformulated statements

**Balance sheet**, built from totals:

- OA = total assets − financial assets
- OL = total liabilities − financial obligations
- NOA = OA − OL
- NNO = financial obligations + preferred/mezzanine − financial assets
- CSE (incl. NCI) = NOA − NNO

**Income statement:**

- NFE = (interest expense − interest income)(1 − t)
- NOPAT = net income incl. NCI + NFE
- Core NOPAT adds back restructuring and goodwill write-offs after tax.

**Ratios**, on average and on beginning balances:

- NOAT, NOPM, RNOA
- ROCE = RNOA + FLEV × (RNOA − NBC)
- FLEV, NBC, spread
- OLLEV, ROOA = (NOPAT + r × OL) / OA, OLSPREAD = ROOA − r

Also: FCF = NOPAT − ΔNOA.

### Traditional

- Profit margin = (NI + interest expense × (1 − t)) / sales
- Asset turnover, ROA = PM × ATO
- Leverage = avg TA / avg equity
- ROE

### Risk

- **Altman Z (public):** 1.2 WC/TA + 1.4 RE/TA + 3.3 EBIT/TA + 0.6 MVE/TL + 1.0 S/TA. Needs market data. Zones: < 1.8 distress, < 2.99 grey.
- **Altman Z (private):** 0.717, 0.847, 3.107, 0.420 × BVE/TL, 0.998. Zones: < 1.2 distress, < 2.9 grey.
- **Credit metrics:** EBIT/interest, debt/EBITDA, FFO/debt, return on capital, EBIT margin, debt/book capital, capex/depreciation.

### Signals

**Year-over-year:**

- Gross margin: %ΔGM − %ΔSales
- SG&A: %ΔSales − %ΔSG&A
- R&D: %ΔR&D − %ΔSales
- Receivables: %ΔSales − %ΔAR
- Inventory: %ΔSales − %ΔInv

**Diagnostics:** CFO/OI, CFO/avg NOA, accruals/ΔSales, sales/AR, depreciation/capex, sales/deferred revenue, allowance/gross AR.

## 3. Trend case projection (`forecast.py`)

`company_detail.json` carries `projection`: five years calculated from the filings with no inputs, so the site can show current and projected growth side by side. It is not a valuation; when a DCF has run, the site shows the DCF's projection instead.

| Driver | Rule |
|---|---|
| Revenue | g0 = revenue CAGR (up to 5 fiscal years, bounded −20%..+40%), fading linearly to 3% in year 5 |
| COGS, SG&A, R&D, other opex | base-period ratios to sales; other opex is the residual so base EBIT = reported operating income |
| D&A, capex | base-period ratios to sales (capex defaults to D&A) |
| ΔNWC | ΔWCR/ΔSales from managerial balance sheet history, else 0.20 |
| Tax | base effective rate if 0–50%, else 21% |
| Interest | base amount held flat |

Base period is the latest TTM (else latest fiscal year). The math is `core.projection`, the same engine the DCF uses. `None` when there's no revenue.

## Classification (`classification.json`)

| Setting | Default | Why |
|---|---|---|
| `marginal_tax_rate` | 0.21 | tax allocated to NFE; packs or models set their own |
| `financial_assets` | cash & marketable securities, long-term investments | long-term investments are mostly debt securities for large filers; a pack moves equity-method stakes |
| `financial_obligations` | short- and long-term debt, dividends payable | |
| `leases_are_financial` | false | keeps NOA consistent with the DCF bridge (net debt = debt − cash) |
| `implicit_borrowing_rate_after_tax` | 0.015 | ROOA / OLSPREAD |

A pack overrides any key under `l1.classification`.

## Market join

`raw_market.json` uses this shape: `{price, price_date, shares_outstanding, source}`.

- `statement_date` (latest balance sheet) and `market.price_date` are stored separately.
- A price dated after `as_of` is rejected.
- Market cap feeds the public Z-score.
- The market adapter itself isn't built yet.

## Registry additions (0.3.0)

New memo concepts: `retained_earnings`, `deferred_revenue_current`, `allowance_for_doubtful_accounts`.

## Open choices

- **Traditional profit margin:** this build adds back after-tax interest *expense*. The course template's formula adds back *net* interest, which goes the wrong way when interest is a net expense. Confirm.
- **FFO:** defined as net income + D&A. The credit sheet's version also adds deferred taxes; there's no deferred-tax *expense* concept yet.
- **Inventory components** (FG / WIP / RM), **warranty** and **bad-debt expense** signals need concepts that aren't tagged yet.
