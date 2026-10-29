# Changelog

All notable changes to the Valuation Model. Newest first.

## [Unreleased]
- Fix: a negative revenue fact in the latest year (bad tagging in a filing) made the profile's revenue CAGR a complex number and crashed stage classification. The stage is now "unknown" in that case. Found by the forecast-accuracy study in `Courtizy/research`.

## [0.7.0] - 2026-10-22
- **LBO** (Deal → LBO): what a financial sponsor could pay. Debt sized by collateral and a 2.0x coverage target (senior, subordinated, mezzanine), interest on the average balance, a cash sweep, an exit at today's multiple plus a change. Shows the max price at the sponsor's target IRR (range at ±5 points), the IRR at the offer, sources and uses, the debt paydown and two sensitivity grids. Inputs on the Deal page or in `lbo.json`.
- **Course checks on the DCF**, each with a status icon: terminal growth band (capped at 4.5%), steady-state growth when the terminal value starts, terminal value share of EV (50-75%), implied exit EV/EBITDA against the comps, and year-1 revenue against a seasonal (Foster) model of the quarters.
- **Tornado**: seven DCF inputs moved one at a time, sorted by swing.
- **Discount rate options**: country risk premium, a synthetic rating from interest coverage when interest / debt can't be measured, and a private-firm mode (total beta, illiquidity discount). Finite-life terminal value.
- **Synthesized firm**: a third comps set, peers weighted to match the target's growth, discount rate, margin and leverage. A note explains when EV/Sales and EV/EBITDA disagree (margins).
- **Prior deals**: Lines Up with Target lights per deal, the premium regression on EV/EBITDA with its sign check, and announced synergies / sales.
- **Synergy checks**: the synergies needed for the offer price, the share of cost synergies that can last (the normal-profit test), and synergies / sales against prior deals.
- **Financial statement analysis**: what moved core RNOA (margin vs turnover effect), economic value added (NOPAT - WACC × NOA), EBITDA / interest and cash-flow coverage of debt.
- The simulation reports the mean's standard error and 95% interval.

## [0.6.0] - 2026-10-22
- Comps values two peer sets. **Sector Peers** is the traditional set from the target's own industry (picked automatically: nearest in size); **Closest Match** is the companies closest on fundamentals from anywhere in the sector. Both show on the Valuation and Deal football fields; the sector set carries the comps weight, the closest set is shown without weight to check it against.
- How Close Each Peer Is, the course's underlying value method: a multiple is a DCF over current earnings, so each peer is rated against the target on its DCF drivers (analysts' 5-year earnings growth, past 5-year growth, discount rate, EBITDA margin for the long run, net debt / EV), green / yellow / red as on the course's stoplight. Size is shown, not rated. Peer averages (simple and weighted) sit under the target.
- Peers are weighted by closeness, and the equal-weight value is shown next to it. A peer rated below 50% is flagged Weak.
- Analysts' 5-year growth comes from Yahoo's Analysis page (the proxy Worker now fetches the session crumb Yahoo requires), else Alpha Vantage's EPS estimates (one year ahead, labelled), and can be typed in the peer picker or comps.json. Past growth comes from the filings (EPS, else net income).

## [0.5.0] - 2026-10-22
- Action titles: every chart and section on Valuation, Deal and Company Detail is headed by a sentence stating what it shows ("DEMO is worth about $44.96 a share, in line with the $45.00 share price"), written by the engine from the same figures (`comparison.json` and `company_detail.json` → `headlines`). Where a figure is missing the plain label stays.
- Deal opens on one summary sheet: the answer, four key figures, the football field grouped into Standalone and Transaction, a value bridge (price → synergies → most a buyer can pay → offer) and where the bid's premium sits among past deals. The method detail (Prior Deals, Whole Firm with Synergies, Just Synergies) moves into tabs; the inputs fold into one section.
- Valuation opens on the answer sheet (value vs. price and the football field), then spread and sensitivity side by side. DCF, Public Comps and Similar Companies sit in Method Detail tabs; Market Snapshot, Company Profile, the simulation figures and Inputs Compared in Appendix tabs.
- Company Detail: the Annual / Quarterly / LTM switch moves to the top, since it drives the charts too, and Statements, Ratios and Sector become tabs instead of collapsible sections. Each tab set remembers its open tab in this browser.

## [0.4.1] - 2026-10-21
- Values that were blank after a run: projected interest expense and income in the statements' estimate columns; Altman Z (public form) for the latest fiscal year, at the as-of market value; the Target row of Public Comps now shows the peers' median implied value per multiple.
- The demo bid has an initial offer ($54.00 against $45.00, a 20% premium), so the Deal view shows the offer premium and the share of synergies paid.

## [0.4.0] - 2026-10-21
- Deal view (Results → Deal), the acquisition side of the course model. Enter the expected synergies and Save and Run Deal values the target two ways in the browser: the whole-firm DCF with synergies (faster revenue growth, COGS and SG&A cut, integration costs in the closing year) and just synergies (the synergies' own DCF added to the pre-announcement price). Both match the course workbooks to the cent.
- The course Summary: standalone range (comps, DCF, 52-week low / current / high) and offer price range (synergy models now; prior deals and the LBO once built), with weights you can edit, the blank-row rule, the relative power of the target setting the best guess, premiums, and the share of synergies paid to the target. A deal football field shows both against the pre-announcement and offer prices.
- Prior deals (transaction comps): upload a deal list as CSV or paste it from Excel (an SDC export works as is). Best deals give lowest / average / highest implied values; all deals give the course's central tendency (premium quartiles, multiples at the percentile where the target's own multiple ranks). They fill five rows of the summary. Matches Best_TC_Comps and Cent_Tend_TC in the course workbooks.
- Sensitivity grids: % of cost synergies realized × revenue growth added, and the lasting share × annual synergies.
- The demo includes a synthetic bid for DEMO and a synthetic list of 24 deals (five marked best), so the Deal view shows every part.
- Ratios: the line charts are replaced by Against the Sector: each framework's nearest figures from the sector screen (quartiles, gap to the median, a position bar), the way a peer benchmark table reads.
- A run's outcome (Done, or Done with problems) stays in view after the page redraws.

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
