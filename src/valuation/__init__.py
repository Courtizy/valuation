"""Valuation Model: what is the business worth, and how sure are we?

Layers (each runnable on its own):
  L0_ingest   SEC filings, sector frames, market data (raw, faithful to the source)
  L1_detail   normalized statements, ratios, profile, sector screens
  L2_models   DCF (simulated), comps, reconcile; lbo / ipo / precedents scaffolded
  L3_app      publish to the static site, the pre-loaded demo, similarity ranking
  _core       shared math (projection, discounting, cost of capital, simulation); imports
              nothing else from this package, so it can move to courtoy-core
  runner      sequencing: python -m valuation run|sector
"""
