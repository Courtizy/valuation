# Valuation Model

Company detail, three-statement projections and valuation ranges built from SEC filings, with a static web app on GitHub Pages.

```
L0  Ingest          SEC companyfacts → raw_filing.json
L1  Company detail  normalize → canonical_statements.json; build → company_detail.json
                    (annual / quarterly / TTM, ratios in two frameworks)
L2  Models          dcf, comps, lbo, ipo, precedents → model_results/; reconcile → comparison.json
L3  App             site/ on GitHub Pages; Actions run the pipeline and publish JSON
model/              all Python: the layers above, core/ (shared math), runner/ (sequencing)
inputs/             hand-edited: assumptions/, packs/, sectors/
```

## Quick start

```bash
pip install -e ".[dev]"                             # puts model/ on the path
pytest
export SEC_USER_AGENT="Your Name you@example.com"
python pipeline.py run AAPL --stop-after L1          # data/AAPL/<today>/company_detail.json
python pipeline.py sector sic-of:AAPL                # data/sectors/sector-technology/<today>/sector.json
python -m L3_app.publish && python -m http.server -d site 8000
```

## Docs

| Doc | Covers |
|---|---|
| `docs/architecture.md` | layers, data layout, cross-cutting rules |
| `docs/L0_ingestor_design.md` | SEC ingest |
| `docs/L1_concepts.md`, `docs/L1_normalize.md` | concept registry, normalizer |
| `docs/L1_build.md` | frequency views and ratio analysis |
| `docs/L1_sector.md` | sector screens: sources, figures, benchmarks, site |
| `docs/core_projection.md` | projection engine |
| `docs/L3_site.md` | GitHub Pages app, Actions, setup |

Stdlib-only at runtime. Not investment advice.
