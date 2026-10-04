# Valuation L1 Stage 1 — Normalizer

*Status: built. Input `raw_filing.json` → output `canonical_statements.json` (schema 0.1.0).*

## Usage

```bash
python -m valuation.L1_detail normalize data/AAPL/raw/raw_filing.json --as-of 2026-09-30 \
    --out data/AAPL/2026-09-30/canonical_statements.json [--pack configs/public/packs/default.json]
python -m valuation.L1_detail validate data/AAPL/2026-09-30/canonical_statements.json
```

The pipeline runner calls the same function as its "normalize" step.

## Rules, in order

1. **Point-in-time.** Only facts with `filed <= as_of` are visible. The output records how many later facts were excluded.
2. **Period type.** Instant concepts only see facts without a start date; duration concepts only see facts with one.
3. **Unit.** Monetary = USD, shares = shares, per-share = USD/shares. A concept whose tags appear only in other units produces a warning, not a record.
4. **Value per period** (registry `aggregation`):
   - `first` — highest-priority tag with a value for that period. Priority is per period, so a company that switched tags in 2018 is still covered on both sides of the switch.
   - `sum` — a total tag if present; otherwise sum the components. Each component is a list of alternatives, priority-picked, so `ShortTermBorrowings` and `CommercialPaper` never both count. Records list the components used and how many were missing.
5. **Across filings.** `value` = latest filing; `value_as_filed` = earliest filing across all of the concept's tags; `restated` = they differ.
6. **Fiscal labels** come from the earliest filing, since companyfacts' `fy`/`fp` describe the filing. Example: FY2022 revenue repeated in the FY2023 10-K is still labeled fiscal 2022.
7. **Derived concepts** are computed only where every input exists for the exact same period, in dependency order (`total_debt` before `net_debt`). Division by zero yields no record.
8. **Identity checks** run on every period where both sides exist, with 0.5% tolerance:
   - assets = liabilities and equity
   - gross profit = revenue − cost of revenue
   - profit/loss = net income + noncontrolling interest share

Durations of 3, 6, 9 and 12 months are all kept, with their length in `months`. Choosing quarterly, annual or TTM views, and deriving Q4, is stage 2's job.

## Output record

```jsonc
{
  "concept": "short_term_debt", "statement": "BS", "period_type": "instant", "unit": "USD",
  "start": null, "end": "2023-09-30", "months": null,
  "fiscal_year": 2023, "fiscal_period": "FY",
  "value": 16000000000, "value_as_filed": 16000000000, "restated": false,
  "method": "summed",                         // reported | summed | derived
  "source": {"tags": ["us-gaap:CommercialPaper", "us-gaap:LongTermDebtCurrent"],
             "accn": "...", "filed": "2023-11-03", "form": "10-K"},
  "components": [{"tag": "us-gaap:CommercialPaper", "value": 6000000000}, ...],  // summed only
  "components_missing": 0
}
```

Derived records carry `source.formula` and `source.inputs` instead of tags.

Top level also holds `lineage` (hash of the input file), `checks`, `coverage` (concepts with data, missing list), and `warnings`.

## Known limits

- **Fiscal labels for pre-XBRL periods** that first appear as comparatives inside a later filing take that filing's labels. Rare after 2011.
- **As-filed for summed concepts** sums each component's earliest value, which can mix filings if components were first reported at different times.
- **Companyfacts has no dimensions**, so segment totals and non-controlling splits beyond the face totals aren't available.
- **Non-USD filers** (most 20-F filers, e.g. TSM) report under `ifrs-full` in their home currency. Stage 1 records the `reporting_basis` (taxonomy, currency, fact counts) and warns. Stage 2 then stops with a clear message, rather than publishing empty statements, until IFRS mapping and currency conversion are built.
