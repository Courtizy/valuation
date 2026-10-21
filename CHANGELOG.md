# Changelog

All notable changes to the Valuation Model. Newest first.

## [0.4.0] - 2026-10-21
- Deal view (Results → Deal), the acquisition side of the course model. Enter the expected synergies and Save and Run Deal values the target two ways in the browser: the whole-firm DCF with synergies (faster revenue growth, COGS and SG&A cut, integration costs in the closing year) and just synergies (the synergies' own DCF added to the pre-announcement price). Both match the course workbooks to the cent.
- The course Summary: standalone range (comps, DCF, 52-week low / current / high) and offer price range (synergy models now; prior deals and the LBO once built), with weights you can edit, the blank-row rule, the relative power of the target setting the best guess, premiums, and the share of synergies paid to the target. A deal football field shows both against the pre-announcement and offer prices.
- Prior deals (transaction comps): upload a deal list as CSV or paste it from Excel (an SDC export works as is). Best deals give lowest / average / highest implied values; all deals give the course's central tendency (premium quartiles, multiples at the percentile where the target's own multiple ranks). They fill five rows of the summary. Matches Best_TC_Comps and Cent_Tend_TC in the course workbooks.
- Sensitivity grids: % of cost synergies realized × revenue growth added, and the lasting share × annual synergies.
- The demo includes a synthetic bid for DEMO and a synthetic list of 24 deals (five marked best), so the Deal view shows every part.

## [0.3.1] - 2026-10-21
- One pull does it all: Run Here (and Build from a sector table) picks the company's six closest peers from its sector and runs comps with the DCF. The peer picker opens on those peers to change them.
- Everything on the site runs in the browser: the "Publish to the Site" card and the GitHub token are gone (publishing stays in GitHub Actions).
- Yahoo is relayed for the public site, not just localhost: prices, beta, and statement items the filings lack. Alpha Vantage or Finnhub keys are the fallback and cross-check Yahoo's close.
- Data checks: SEC figures tie out against themselves and are compared with Yahoo's for the same years; differences are listed under Statements and in the warnings.
- Statements: Income Statement / Balance Sheet / Cash Flow / Dividends / All toggles, each with a chart of its main lines (revenue, operating and net income; assets, liabilities, debt and cash; CFO, CFI, CFF and FCF; dividends and buybacks against earnings and FCF). The Dividends view adds dividends per share, payout ratio, total payout and FCF coverage. Cash from investing and financing added to the Cash Flow statement.
- Ratios: each framework opens on a chart of the ratios that carry it (RNOA, ROCE and NOPM; the operating cycle and cash conversion cycle; DuPont ROE, ROA and margin; Debt/EBITDA, interest cover and Altman Z; cash vs. accrual earnings), with a line on how to read it.
- A $K / $M / $B switch on Results sets the unit of every dollar table, remembered in this browser. Selected toggles are highlighted in the accent color.
- Market Snapshot on the Valuation page: price and change, previous close, open, day's range, 52-week range, volume and 3-month average, market cap, enterprise value, net debt, shares, beta, EPS, P/E, EV/Sales, EV/EBITDA, price/book and dividend yield. Point-in-time: the trading figures are for the as-of close, from a year of daily bars.
- The football field adds the 52-week trading range as an unweighted market reference row, as on the course Summary sheet.
- Sector screens in the browser read EDGAR's SIC lists from site/data/sic_members.json, which the weekly Refresh now publishes; the SEC refuses that EDGAR page to the proxy.

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
