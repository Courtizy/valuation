# Valuation Model

*What is the business worth, and how sure are we?* Part of **Decision Models** by Jason C. Courtoy.

Company detail, three-statement projections and simulated valuation ranges built from SEC filings, with a static site on GitHub Pages (Overview · Results · Method). Analysis of method, not investment advice.

```
L0  Ingest          SEC companyfacts → raw_filing.json
L1  Company detail  normalize → canonical_statements.json; build → company_detail.json
L2  Models          dcf (simulated), comps, precedents → model_results/; reconcile → comparison.json
L3  App             site/ on GitHub Pages; Actions run the pipeline and publish JSON
```

## Folder layout (two front doors)

| Folder | Door | Purpose |
|---|---|---|
| `src/valuation/` | both | The engine: layers L0–L3, `runner/`, and `_core/` (shared math, imports nothing else from the app) |
| `configs/public/` | public | Hand-edited assumptions, packs and sectors for the published companies |
| `scripts/export_site.py` | public | Copies `brand/` into `site/brand`, rebuilds the demo, writes `site/data/changelog.json`, refreshes the index |
| `site/` | public | Static Pages site; displays the JSON only |
| `brand/` | public | Decision Models brand kit (CSS, JS palette, icons) |
| `app/run_private.py` | private | Same engine on `private/inputs.json`, real market data, output in `private/site` |
| `private/` | private | Gitignored except the README and example. Personal-time data only; work data goes through official channels, never a repo |

## Quick start

```bash
pip install -e ".[dev]"
pytest -q
export SEC_USER_AGENT="Your Name you@example.com"
python -m valuation run AAPL --stop-after L1        # data/AAPL/<today>/company_detail.json
python -m valuation sector sic-of:AAPL              # data/sectors/sector-technology/<today>/sector.json
python scripts/export_site.py                       # brand, demo, changelog, index
python -m http.server -d site 8000                  # http://localhost:8000 (?demo=1 for the demo)
python app/run_private.py --config private/inputs.json   # private door
```

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
| `docs/L2_dcf.md` | DCF, including the simulation |
| `docs/L3_site.md` | GitHub Pages app, Actions, setup |
| `CHANGELOG.md` | releases (shown on the Method page) |

Stdlib-only at runtime. Not investment advice.
