# Valuation L1 — Canonical Concept Registry

*Status: registry 0.2.0. Normalizer built; see `L1_normalize.md`.*

## What's in it

`L1_detail/concepts.json` holds 112 concepts in three kinds:

| Kind | Count | Rule |
|---|---|---|
| `reported` | 95 | edgartools' standard concepts, names kept in `edgartools_concept` |
| `memo` | 11 | valuation additions; may overlap reported items, **never summed into totals** |
| `derived` | 6 | computed by `formula` from other concepts; never read from tags |

Concept set and display names come from edgartools' standardization (MIT), based on mpreiss9's taxonomy. Attribution is stored in the JSON.

Each concept carries: `id` (snake_case), `display_name`, `edgartools_concept`, `statement` (BS / IS / CF / SHARES / DISCLOSURE / DERIVED), `section`, `period_type` (instant / duration), `unit_type` (monetary / shares / per_share / ratio), `kind`, `source`, `aggregation` (first / sum), `primary_tags`, `components` (sum only), and `formula` (derived only).

## Sum rule (0.2.0)

| Concept | Total tag (wins if present) | Components (alternatives in each) |
|---|---|---|
| `cash_and_marketable_securities` | CashCashEquivalentsAndShortTermInvestments | [CashAndCashEquivalentsAtCarryingValue] + [MarketableSecuritiesCurrent / ShortTermInvestments / AvailableForSaleSecuritiesDebtSecuritiesCurrent] |
| `short_term_debt` | DebtCurrent | [ShortTermBorrowings / CommercialPaper] + [LongTermDebtCurrent] |

Within a component only the first alternative with a value counts, so overlapping tags never double count. The trade-off: a company reporting both commercial paper and other short-term borrowings separately is undercounted. Packs can override.

## The integrity rule that shapes everything

edgartools' mapping file is built to **sum every line item on a statement's face** that maps to a concept. For example, it maps `Goodwill`, `GoodwillGross` and `GoodwillImpairedAccumulatedImpairmentLoss` all to `Goodwill`. That works when only face-statement lines are present.

Companyfacts contains every fact, including notes. Summing there would double count. So L1 runs in two modes:

- **Companyfacts mode (now):** each concept has a `primary_tags` priority list. For each period, the first tag with a value wins. The validator blocks any tag being claimed by two reported concepts.
- **Presentation mode (later):** once an L0 adapter supplies statement placement (SEC Financial Statement Data Sets), L1 can load edgartools' full `gaap_mappings.json` and sum face-statement lines safely.

## Valuation additions

| id | Why | Tags (priority order) |
|---|---|---|
| `operating_cash_flow` | DCF, FCF | NetCashProvidedByUsedInOperatingActivities |
| `investing_cash_flow` | completeness / tie-out | NetCashProvidedByUsedInInvestingActivities |
| `financing_cash_flow` | completeness / tie-out | NetCashProvidedByUsedInFinancingActivities |
| `depreciation_amortization_cf` | EBITDA; IS often embeds D&A | DepreciationDepletionAndAmortization, DepreciationAmortizationAndAccretionNet, DepreciationAndAmortization |
| `share_based_compensation` | edgartools buries it in other opex | ShareBasedCompensation, AllocatedShareBasedCompensationExpense |
| `change_in_working_capital` | FCF bridge | IncreaseDecreaseInOperatingCapital |
| `income_taxes_paid` | cash tax rate | IncomeTaxesPaidNet |
| `interest_paid` | cost of debt check | InterestPaidNet |
| `stock_repurchased` | gross buybacks (edgartools' concept nets issuance) | PaymentsForRepurchaseOfCommonStock |
| `eps_basic`, `eps_diluted` | comps cross-check | EarningsPerShareBasic / Diluted |

## Derived concepts

| id | Formula |
|---|---|
| `ebitda` | operating_income_loss + depreciation_amortization_cf |
| `free_cash_flow` | operating_cash_flow − capital_expenses |
| `total_debt` | short_term_debt + long_term_debt |
| `net_debt` | total_debt − cash_and_marketable_securities |
| `lease_liabilities` | operating lease current + non-current |
| `effective_tax_rate` | income_taxes / pretax_income_loss |

## Known approximations (fix before L3/L4 rely on them)

- **Cash excludes non-current marketable securities.** Apple holds most of its investment portfolio as non-current, so net debt is still overstated for companies like it. Whether to include them is a valuation choice, best set per model.
- **`free_cash_flow` is a proxy.** CFO already deducts interest, so this is closer to levered FCF. L2 should build unlevered FCF from EBIT.
- **Lease commitments:** the ASC 842 `LesseeOperatingLeaseLiabilityPaymentsDue…` tags are listed ahead of the pre-2019 `OperatingLeasesFutureMinimumPaymentsDue…` tags that edgartools lists.
- **Sign conventions:** capex and buybacks are reported as positive payments; formulas assume that.

## Unmapped concepts (28)

Reported concepts with no companyfacts tags yet. Most are "Other…" buckets that only make sense in presentation mode; the rest need sum rules or sector-pack choices. `registry.unmapped()` lists them; the count should fall as packs and the presentation adapter land.

## Next steps

1. Sector packs override `primary_tags` per industry (banks and insurers need different revenue and debt concepts).
2. Presentation-mode adapter (Financial Statement Data Sets) and load `gaap_mappings.json`.

The output record format is documented in `L1_normalize.md`.
