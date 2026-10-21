# Changelog

All notable changes to the Valuation Model. Newest first.

## [0.3.0] - 2026-10-21
- Weekly Refresh builds about 40 real companies and two sector screens from SEC filings, so visitors browse them with no token.
- Published data moves to the site-data branch, replaced by one commit on each save, so main stays code only.
- Run in this browser: anyone can value a company from the Run page with no token. The same Python engine runs in the browser (Pyodide), and the results are saved on that device only.
- Browser prices: a Finnhub key of your own (today's quote and reported beta) beside Alpha Vantage, and Yahoo when the site is opened from localhost (the proxy relays Yahoo for localhost only).
- In the browser, without a token: Save Peers and Run Comps (peers kept on the device), sector screens, and Build Company Detail from a sector table. An optional Alpha Vantage key (the visitor's own) adds prices.
- worker/: a Cloudflare Worker proxy (SEC, FRED and Damodaran only) that the in-browser Run fetches through.
- README: a Data and licensing section listing each source and where it appears.
- Industry betas and the implied equity risk premium from Aswath Damodaran's datasets (NYU Stern): the public site's DCF uses the industry's unlevered beta, relevered at the company's own D/E, in place of the illustrative sector beta; the default case uses the implied ERP in place of a flat 5%.
- Pages deploys no longer get cancelled by a skipped run.

## [0.2.1] - 2026-10-21
- Comps peer lists for AAPL, DELL, HPQ and KO restored under configs/public/assumptions (dropped in the 0.2.0 layout move).
- README rewritten: live links, status by layer, validation and course workbook parity, publishing real companies, roadmap.
- SEC requests retry when a read times out, instead of failing the pipeline run.
- Apache 2.0 license; package version now matches this changelog (a test checks it).

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
