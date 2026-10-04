# Valuation Model — Layer Architecture (v4)

*Supersedes §2 of `app_layer_frameworks.md` for the Valuation app. Decided 2026-10-02.*

| Version | Change |
|---|---|
| v2 | Forecast and WACC moved inside each model |
| v3 | Normalization moved from L0 into L1; L0 is raw ingest only |
| v4 | Simulation, export and reconciliation folded into L2; app becomes L3; runner, packs, lineage and point-in-time added |

## Layers

```
 L0  Ingest            adapters only, no interpretation
                       → raw_filing.json, raw_market.json
      |
 L1  Company Detail    stage 1 normalize → canonical_statements.json
                       stage 2 build     → company_detail.json
                         (annual | quarterly | ttm, market join, ratios)
      |
 L2  Models            dcf/ comps/ lbo/ ipo/ precedents/
                         each: run → own Monte Carlo → model_results/{model}.json
                               + own Excel template (export extra)
                       reconcile/  reads model_results/*.json only
                         → comparison.json, football field, memo, scenario_result.json
      |
 L3  App               static site on GitHub Pages (site/); Actions run python -m valuation
                       and publish JSON; the page renders it and holds no model logic
                       (projections come from L1's trend case or the DCF)
```

| Framework doc layer | v4 home |
|---|---|
| L0 Data Adapters | L0 |
| L1 Normalization | L1 stage 1 |
| L2 Driver & Forecast, L3 Cost of Capital | inside each L2 model |
| L4 Valuation Methods | L2 models |
| L5 Simulation & Reconciliation | per-model simulation + L2 reconcile |
| L6 Export | per-model templates + reconcile memo |
| L7 App | L3 |

## Folder layout

```
valuation/
  src/valuation/                 the engine (pip install -e . puts it on the path); python -m valuation run|sector
    L0_ingest/                   adapters (companyfacts, sector frames, market data), cache, raw schema, CLI
    L1_detail/                   registry, normalize, periods, analysis, build, profile, forecast,
                                 sector screen, taxonomy
    L2_models/                   base, dcf (simulated), comps, reconcile; lbo/ ipo/ precedents scaffolded
    L3_app/                      publish (outputs -> site/data), similar, demo/
    _core/                       projection, cost_of_capital, dcf, simulation, shares, num, market;
                                 imports nothing else from the package (test enforced) until it moves to courtoy-core
    runner/                      paths, company plan/execute, sector, cli
    lineage.py                   lineage block helper
  configs/public/                everything edited by hand for the public site
    assumptions/                 {TICKER}/{model}.json, _template/
    packs/                       sector packs (default.json)
    sectors/                     taxonomy.json, sic_codes.json, custom ticker lists
  scripts/export_site.py         public door: brand → site/brand, demo, changelog.json, index refresh
  app/run_private.py             private door: private/inputs.json → private/data, private/site
  private/                       gitignored (README and example only); personal-time data only
  brand/                         Decision Models brand kit (copied into site/brand at export)
  site/                          GitHub Pages app: index.html, assets/, data/ (brand/ and demo/ generated)
  tests/  docs/  CHANGELOG.md  .github/workflows/
```

## Data layout

```
data/{TICKER}/raw/raw_filing.json                     L0, refreshed via cache
data/{TICKER}/{as_of}/raw_market.json                L0 market data (docs/L0_market.md)
data/_market/{as_of}/risk_free.json                   L0 10-year Treasury (FRED)
data/{TICKER}/{as_of}/canonical_statements.json       L1 stage 1
data/{TICKER}/{as_of}/company_detail.json             L1 stage 2
data/{TICKER}/{as_of}/model_results/{model}.json      L2 models
data/{TICKER}/{as_of}/comparison.json                 L2 reconcile
data/_screen/{as_of}/raw_screen.json                  L0 sector frames (all filers)
data/_screen/{as_of}/sic_{code}.json                  L0 EDGAR company list for a SIC code
data/sectors/{sector_id}/{as_of}/sector.json          L1 sector screen (docs/L1_sector.md)
configs/public/sectors/{name}.json                                   custom sector lists (in the repo)
```

Everything from L1 onward is keyed by `as_of`, so a past valuation can be rerun and compared.

## Cross-cutting rules

**Runner.** `runner/` holds sequencing only (`python -m valuation` is its entry point) (`--stop-after L1` skips models): ingest and build for the target and any peers, then models, then reconcile. It stops at the first step that isn't built or fails and marks the rest skipped. Peers whose company detail already exists for the same `as_of` are reused, not rebuilt. `--dry-run` prints the plan. The app starts the runner through the Pipeline GitHub Action; every layer still runs on its own.

```bash
python -m valuation run AAPL --models dcf,comps --as-of 2026-09-30 --dry-run
```

**Shared helpers.** `core/num.py` (`div`, None-safe division) is used across L1; `profile.py` holds the trait classifiers used by both full profiles and sector screens; `L3_app/similar.py` is the one similarity ranking behind Similar Companies and the peer picker.

**Projection horizon.** Year 1 is the fiscal year after the last 10-K (DCF `base_period` defaults to `annual`). The trend case runs 10 years, fading to its terminal rates by Year 10.

**Lineage.** Every file from L1 onward carries `schema_version`, `as_of`, and `inputs: [{file, sha256}]`. Reconcile warns when models used different versions of the same input or different `as_of` dates.

**Point-in-time.** L1 normalize keeps only facts with `filed <= as_of`. Without this, back-testing a past forecast silently uses later restatements. L0 already stores `filed` on every fact.

**Sector packs.** Data files in `configs/public/packs/`. In L1 they override tag priorities, concepts and profile thresholds (banks have no gross profit). In L2 they set default assumptions. They do **not** decide which models apply: that comes from the company profile.

**Triangulation by company profile.** L1 measures four traits (stage, cash-flow predictability, asset intensity, capital structure). Reconcile turns them into a primary method, a cross-check and default weights, each with a reason (`docs/L2_reconcile.md`). `configs/public/assumptions/{TICKER}/reconcile.json` can override the weights or switch to the acquisition context.

**Peers.** `configs/public/assumptions/{TICKER}/comps.json` lists peers. The runner adds L0 and L1 steps for each peer only when a selected model has `needs_peers` (comps, ipo). All L1 work finishes before any model runs.

## L0 rules

- Fetch, cache, and write source data faithfully. No dedupe, filtering, or tag mapping.
- One adapter per source. Market data gets its own adapter and file.

## L1 rules

- **Two stages, two files.** `canonical_statements.json` is the checkpoint where a bad tag mapping is caught before it spreads into ratios.
- **Market data is a separate input.** Price-based ratios recompute from fresh `raw_market.json` without rerunning stage 1. `company_detail.json` records the statement date and price date separately.
- **Quarterly is the base.** Q4 = full year − nine-month YTD (`method: q4_derived`). Annual from 10-K values; TTM sums four quarters.
- **Instant vs duration.** Balance-sheet items take the period-end value and never sum.
- **Average-based ratios** (ROE, ROA, turnover) need one extra prior period.
- **Calendarization.** Keep fiscal labels; add calendar year/quarter for peer alignment.

## L2 rules

**Each model owns its forecast, WACC, and simulation.** It runs with only `company_detail.json`, its assumptions file, and peers if flagged.

```python
def run(detail: dict, assumptions: dict, peers: list[dict] | None = None) -> ModelResult
```

**Isolation (tested).** A model imports only `L2_models.base` and `core/`, never another model. Reconcile imports no model and reads result files only.

**Shared math, not shared data.** WACC build, discounting, simulation and Excel writing come from `core/`, so the same inputs always give the same answer.

**Export is optional.** Excel and memo need the `export` extra (`pip install valuation[export]`); models run headless without it.

**Standard `assumptions_used` block** in every result:

```jsonc
{
  "forecast": {"years": 5, "frequency": "annual",
               "revenue_growth": [0.06, 0.06, 0.05, 0.05, 0.04],
               "ebit_margin": [0.30, 0.30, 0.31, 0.31, 0.31],
               "capex_pct_revenue": 0.03, "nwc_pct_revenue": -0.05, "tax_rate": 0.16},
  "cost_of_capital": {"risk_free": 0.042, "equity_risk_premium": 0.05, "beta": 1.1,
                      "pre_tax_cost_of_debt": 0.05, "target_debt_weight": 0.10, "wacc": 0.089},
  "terminal": {"method": "gordon", "growth": 0.025},
  "sources": {"risk_free": "UST 10Y 2026-10-01", "beta": "5Y monthly vs S&P 500"}
}
```

Fields a model doesn't use are omitted, not zeroed. Reconcile flags fields present in two or more models whose values differ; that is the "inputs vs method" split.

**Reconcile outputs** `comparison.json`: football-field ranges, assumption differences, and warnings. It will also emit `scenario_result.json` for the optional cross-app interop in framework §5.

## What each model needs beyond L1

| Model | Model-owned inputs | Data gaps to close |
|---|---|---|
| DCF | forecasts, WACC, terminal value, diluted shares (options/RSUs) | option/RSU detail from filing notes |
| Comps | peer set, multiples, calendarized periods | forward (NTM) consensus estimates, usually paid |
| LBO | entry multiple, debt tranches and rates, fees, min cash, exit year and multiple | existing debt maturities from notes |
| IPO | peer multiples, primary/secondary shares, use of proceeds, IPO discount | S-1 financials (no companyfacts history pre-IPO) |
| Precedents | deal set, deal multiples | deal database; SEC has no usable source |

## Testing

- Tests per layer, runnable alone (`tests/test_L0_*`, `test_L1_*`, `test_L2_*`, `test_pipeline.py` (the runner)).
- Isolation rules are tests, not conventions.
- Planned in `core.validate`: Excel parity tests per model, and a forecast back-test harness every model uses the same way.

## Open decisions

- **Peer caching:** reuse a peer's `company_detail.json` for the same `as_of`, or rebuild every run? Reuse is faster; lineage hashes make it safe to detect staleness.
- **Market-data source:** FMP, yfinance, or another; affects licensing for public demos.

## Next steps

1. ~~L1 stage 1 normalizer~~ (done, see `L1_normalize.md`).
2. ~~L1 stage 2: frequency views, analysis in both frameworks, market join~~ (done, see `L1_build.md`).
3. ~~Three-statement projection in `core/`~~ (done, see `core_projection.md`).
4. ~~`core/` cost of capital and treasury stock method; L2 `dcf` (forecast and implied modes)~~ (done, see `L2_dcf.md`).
5. ~~Public comps~~ (done, see `L2_comps.md`).
6. `just_synergy` and `dcf_synergy`, then LBO, then precedents (needs a deal list).
7. IFRS / foreign-currency filers (20-F): map `ifrs-full` tags, convert currency, handle ADR ratios. Until then such companies fail at L1 with a clear message.
6. Market-data adapter and Treasury yields.
