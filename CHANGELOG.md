# Changelog

All notable changes to the Valuation Model. Newest first.

## [0.2.0] - 2026-10-04
- Repository moved to the Decision Models layout: engine in src/valuation (shared math in _core), public door scripts/export_site.py, private door app/run_private.py.
- DCF is now simulated: 2,000 seeded runs over near-term growth, WACC and terminal growth; Bear and Bull are the 10th and 90th percentiles, the course scenarios are kept for reference.
- Site follows the portfolio layout: hub bar, Overview, Results and Method pages, In development status.
- Pre-loaded demo with a guided tour, rebuilt on every deploy.
- DCF default case for companies without a dcf.json; debt-to-equity solved at the model's own equity value when there's no price.
- Yahoo as a backup for items the SEC filings lack (private runs only).

## [0.1.0] - 2026-10-03
- SEC filings to normalized statements, ratios in three frameworks and a company profile.
- DCF (forecast and implied modes) matching the course workbooks; public comps; reconciliation by company profile.
- Sector screens over a GICS-style taxonomy of SEC industry codes, with benchmarks and a peer picker.
- Static site on GitHub Pages, with showcase mode keeping licensed market data off the public pages.
