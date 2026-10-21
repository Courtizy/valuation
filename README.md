# Valuation Model

*What is the business worth, and how sure are we?* Part of **[Decision Models](https://courtizy.github.io/)** by Jason C. Courtoy.

[![Tests](https://github.com/Courtizy/valuation/actions/workflows/tests.yml/badge.svg)](https://github.com/Courtizy/valuation/actions/workflows/tests.yml)
[![Pages](https://github.com/Courtizy/valuation/actions/workflows/pages.yml/badge.svg)](https://github.com/Courtizy/valuation/actions/workflows/pages.yml)
![Status: In development](https://img.shields.io/badge/status-in%20development-4F46E5)

**[Open the model](https://courtizy.github.io/valuation/)** · **[Guided demo](https://courtizy.github.io/valuation/?demo=1)** · [Changelog](CHANGELOG.md)

The Valuation Model turns a company's SEC filings into normalized statements, ratio analysis, projections and a simulated value range, then compares methods side by side. Real companies and sector screens are built from public SEC data by a GitHub Actions pipeline. A synthetic demo company with a guided tour shows every feature. It is analysis of method, not investment advice.

## What it does

- **Reads SEC filings directly.** XBRL company facts and EDGAR industry codes, with a declared User-Agent, within the SEC's fair-access limits.
- **Normalizes point in time.** Only facts filed on or before the as-of date count. One tag is chosen per period, restatements are flagged, and the balance sheet, gross profit and net income checks run on every build.
- **Analyzes statements three ways.** Standard ratios, managerial (working capital) ratios and reformulated operating/financing ratios, with definitions taken from MBA course workbooks.
- **Values with a simulated DCF.** 2,000 seeded runs over near-term growth, WACC and terminal growth. Bear and Bull are the 10th and 90th percentiles.
- **Compares methods.** Public comparables, plus reconciliation into a football field that explains why the methods differ.
- **Screens sectors.** GICS-style groups of SEC industry codes, with benchmarks and a peer picker that saves comps peer lists back to the repo.

## Status

| Layer | Part | Status |
|---|---|---|
| L0 Ingest | SEC company facts, sector frames, risk-free rate, market data adapter | Built |
| L1 Company detail | Normalize, annual / quarterly / TTM views, ratios, company profile, sector screens | Built |
| L2 Models | DCF (simulated), public comps, reconcile | Built |
| L2 Models | Precedent transactions, LBO, IPO | Scaffolded, not built |
| L2 Models | Excel export, memo PDF, back-testing | Planned |
| L3 App | Static site on GitHub Pages (Overview, Results, Method), demo and tour | Built |

The public site runs in **showcase mode**: it publishes SEC-derived figures only, with no licensed market prices. Price-dependent outputs (market multiples, upside to price) appear in the demo and in private runs.

## Validation

| Check | Where it runs |
|---|---|
| Unit and integration tests (L0 to L3, offline fixtures) | Every push, in CI |
| Statement identities tie on every normalization | Every pipeline run |
| Models never import each other; `_core` imports nothing else from the app | Enforced by tests in CI |
| Simulation is seeded and reproducible | Tests in CI |
| Parity with MBA course workbooks | Locally, when the workbooks are present (below) |

### Course workbook parity

The course workbooks are not in the repo. `tests/test_course_parity.py` reads them at test time and checks that the Python code reproduces their numbers. Without them those tests skip, which is why CI shows skips.

| Course | Workbook (key in `course_cases.local.json`) | What it checks |
|---|---|---|
| MBA 772 | `projection_bs` | Projected balance sheet, managerial balance sheet, cash ties |
| MBA 772 | `ratios_operating_financial` | Liquidity, working-capital and turnover ratios |
| MBA 772 | `mbs_fcf` | NOPLAT, change in working capital, capex and free cash flow |
| MBA 733 | `reformulated_ratios` | RNOA, ROCE, NOAT, FLEV and FCF on beginning and average balances |
| MBA 789 | `firm_dcf` (one entry per case) | Projection rows, discount rates, EV-to-equity bridge, scenario range, implied growth, public comps |

To run them, copy `tests/course_cases.example.json` to `tests/course_cases.local.json` (gitignored), point each key at your workbook, then:

```bash
pip install -e ".[dev,export]"
VALUATION_COURSE_DIR=/path/to/workbooks pytest tests/test_course_parity.py
```

Legacy `.xls` files are converted with LibreOffice if it is installed.

## Quick start

```bash
pip install -e ".[dev]"
pytest -q
export SEC_USER_AGENT="Your Name you@example.com"         # the SEC requires contact details
python -m valuation run AAPL --stop-after L1               # data/AAPL/<today>/company_detail.json
python -m valuation run AAPL --models dcf,comps            # through L2 and reconcile
python -m valuation sector sector:technology               # data/sectors/sector-technology/<today>/sector.json
python -m valuation.L3_app.publish --data-dir data --site-dir site
python scripts/export_site.py                              # brand, demo, changelog, index
python -m http.server -d site 8000                         # http://localhost:8000 (?demo=1 for the demo)
python app/run_private.py --config private/inputs.json     # private door, real market data
```

### Publishing real companies

The **Pipeline** workflow runs a ticker or a sector on GitHub Actions and commits the results to `site/data/`; **Pages** then redeploys. Start it from the Actions tab or with:

```bash
gh workflow run pipeline.yml -f ticker=DELL -f models=dcf,comps -f stop_after=L2
gh workflow run pipeline.yml -f sector=sector:technology
```

It needs the repository secret `SEC_USER_AGENT`. Comps peer lists live in `configs/public/assumptions/{TICKER}/comps.json`; the site's peer picker can save them there.

## Layers

```
L0  Ingest          SEC companyfacts, sector frames, market data → raw_filing.json, raw_market.json
L1  Company detail  normalize → canonical_statements.json; build → company_detail.json
L2  Models          dcf (simulated), comps; precedents, lbo, ipo scaffolded → model_results/
                    reconcile reads model_results/*.json only → comparison.json
L3  App             site/ on GitHub Pages; Actions run the pipeline and publish JSON
```

Each layer talks to the next only through JSON files that record their inputs' hashes and as-of dates, so any run can be reproduced and mismatched inputs are flagged.

## Folder layout (two front doors)

| Folder | Door | Purpose |
|---|---|---|
| `src/valuation/` | both | The engine: layers L0–L3, `runner/`, and `_core/` (shared math, imports nothing else from the app) |
| `configs/public/` | public | Hand-edited assumptions, comps peers, packs and sectors for the published companies |
| `scripts/export_site.py` | public | Copies `brand/` into `site/brand`, rebuilds the demo, writes `site/data/changelog.json`, refreshes the index |
| `site/` | public | Static Pages site; displays the JSON only |
| `brand/` | public | Decision Models brand kit (CSS, JS palette, icons) |
| `app/run_private.py` | private | Same engine on `private/inputs.json`, real market data, output in `private/site` |
| `private/` | private | Gitignored except the README and example. Personal-time data only; work data goes through official channels, never a repo |

## Roadmap

1. Rerun and review real companies and sectors on the public site.
2. Excel export: a live-formula DCF workbook per run, then comps.
3. Precedent transactions, then LBO, then IPO, each with course parity tests.
4. Back-testing: score past DCF forecasts against what was later filed, using the as-of cutoff.
5. One-page memo PDF per company.
6. Move `_core/` into the Shared Core package (`courtoy-core`).

## Docs

| Doc | Covers |
|---|---|
| `docs/architecture.md` | layers, data layout, cross-cutting rules |
| `docs/L0_ingestor_design.md` | SEC ingest |
| `docs/L0_market.md` | market data: prices, beta, risk-free rate, cross-check |
| `docs/L1_concepts.md`, `docs/L1_normalize.md` | concept registry, normalizer |
| `docs/L1_build.md` | frequency views and ratio analysis |
| `docs/L1_sector.md` | sector screens: sources, figures, benchmarks, site |
| `docs/core_projection.md` | projection engine |
| `docs/L2_dcf.md`, `docs/L2_comps.md`, `docs/L2_reconcile.md` | DCF and its simulation, comparables, reconciliation |
| `docs/L3_site.md` | GitHub Pages app, Actions, setup |
| `CHANGELOG.md` | releases (shown on the Method page) |

## License

[Apache 2.0](LICENSE). Stdlib-only at runtime.

<sub>Personal project · public or synthetic data only · not endorsed by DoD or the U.S. Air Force · analysis of method, not investment advice.</sub>
