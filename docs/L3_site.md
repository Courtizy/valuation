# L3 App: GitHub Pages Site

*Status: built. Replaces the planned Streamlit app.*

## How it fits together

```
 Run page (Run ▸) ──► Pipeline action (one ticker or sector, on demand)
   (or Actions page,       python -m valuation run TICKER --stop-after L1|L2
    or gh CLI)
                       Refresh action (weekly, configs/public/universe.json)
                           scripts/refresh_universe.py → every sector and company listed
                                   │
                         both: python -m valuation.L3_app.publish over the site-data branch
                               scripts/site_data.sh save → force-pushes one commit to site-data
                                   │
                                   ▼
                       Pages action (on push to main, or after Pipeline / Refresh)
                           pytest → site_data.sh load → scripts/export_site.py → uploads site/
                                   │
                                   ▼
                       Browser: index.html reads data/index.json,
                       data/{TICKER}/{as_of}/company_detail.json, comparison.json
```

GitHub Pages only serves static files, and the SEC API can't be called from a browser (no CORS, and it needs a contact User-Agent). So published data is fetched and computed in Actions, and the page only renders it. The one exception is a visitor's own run (below).

## Run in this browser

Anyone can value a company from the **Run ▸** page with no token. The results stay on their device.

```
 Run in This Browser ──► assets/pyworker.js (web worker)
                           Pyodide 0.29.4 (CDN) + py/valuation.zip (built by export_site.py:
                           src/valuation and configs/public)
                           valuation.L3_app.web.run(ticker) → same plan as the pipeline, L0 → L2 (DCF)
                                   │  every request: sync XHR to the proxy, ?url=<SEC | FRED | Damodaran>
                                   ▼
                       worker/ (Cloudflare Worker): allowlist, SEC User-Agent, edge cache
                                   │
                                   ▼
                       the visitor's site-data files → IndexedDB (assets/device.js)
                       listed in the company menu as "on this device", read through getJSON("device/…")
```

- **What runs here.** Run Here (a company: the DCF, plus comps when it has peers), Screen Here (a sector), and on the Results pages Save Peers, Run Comps, Screen and Build Company Detail. Without a GitHub token these all run in the browser; with the owner's token on a published company they start the Pipeline as before (`useGitHub()` in `run.js`).
- **Peers on the device.** Save Peers writes `_assumptions/{TICKER}/comps.json` in IndexedDB, which `web.run` lays over `configs/public/assumptions`. Run Comps saves the ticks first, then runs `dcf,comps`; the peers are built too and listed as device companies.
- **Prices.** Yahoo is never called. With the visitor's own Alpha Vantage key (Run page ▸ Settings, kept in this browser) the worker calls alphavantage.co directly, about three requests a company, at most one a second, and the run gets a price and a price-based beta. Without a key the DCF uses Damodaran's industry beta (relevered at the company's D/E), the implied ERP and the 10-year Treasury, and comps needs peer prices typed in the picker.
- **Sector screens** read the SEC's frames for every filer (four years of figures) and EDGAR's industry lists, so the first screen takes a few minutes; the proxy's edge cache makes repeats faster. A device screen hides the published one with the same id.
- **Nothing is published.** Each run returns the device's whole `data/` folder (earlier runs are passed back in), which replaces what IndexedDB holds. **Clear** on the Run page removes it.
- **The proxy URL** is `PROXY_URL` in `site/assets/config.js` (https://valuation.jason-courtoy.workers.dev). A visitor can set another under **Data Proxy** on the Run page; it's remembered in this browser. Without one, Run Here explains that the proxy isn't set up.
- The first run downloads Pyodide (about 10 MB, then cached by the browser). The engine itself is about 140 KB.

## Published data and the weekly refresh

Published data lives on the **`site-data` branch**, not on `main`. Each save replaces that branch with a single commit, so refreshing about 40 companies a week (roughly 1.1 MB of JSON each per run) doesn't grow the repository's history, and `main` holds only code and configuration. Pipeline and Refresh share the `pipeline-publish` concurrency group, so two saves never race.

The **Refresh** workflow runs every Monday at 07:00 UTC, or by hand (`gh workflow run refresh.yml`). It builds every sector and ticker in `configs/public/universe.json`: the DCF for each company, plus comps where `configs/public/assumptions/{TICKER}/comps.json` exists (its peers are built too). Visitors then pick from those companies with no token. One company failing doesn't stop the rest; the run summary lists failures. To change what's on the site, edit `universe.json`.

The page does no valuation math. Projections are calculated in Python and published with the data: the DCF's projection when a DCF has run, otherwise the L1 trend case (`company_detail.json` → `projection`). There are no driver selectors on the site; to change a projection, edit `configs/public/assumptions/{TICKER}/dcf.json` and rerun.

## Code layout (site/assets)

Plain ES modules, no build step. `main.js` loads `index.json`, concepts, companies and the taxonomy in parallel, then each run's files together.

| Module | Holds |
|---|---|
| `main.js` | start-up, company and run selection, page routing (`route`), theme, Demo switch |
| `pages.js` | Overview and Method pages |
| `state.js` | shared state, `$`, `getJSON` (reads `device/…` paths from memory), `runRoot`, `fileHref`, banners |
| `format.js` | the presentation standard (below): numbers, periods, Title Case, labels |
| `tables.js` | statement rows (`finRow`, `acct`) |
| `charts.js` | SVG charts: column, line (dashed estimates), area, range, scatter, bar list, spread, grouped bars, histogram |
| `company.js` | Company Detail: tiles, Revenue, Returns, Margins, Cash Conversion, statements, ratios |
| `sector.js` | Versus Sector and Sector cards, level switch |
| `valuation.js` | Results side column, KPI row, football field with why they differ, spread of simulated outcomes, sensitivity, value vs price, profile, comps, peer picker, DCF detail, similar companies |
| `run.js`, `github.js` | Run page: Run in This Browser, and the owner's Publish form; GitHub API (dispatch, read/write repo JSON) |
| `device.js`, `pyworker.js`, `config.js` | runs in this browser: IndexedDB store, the Pyodide worker, the proxy URL |

The Pages workflow stamps every stylesheet and module import with `?v=<commit>`, so a deploy is never hidden by the browser cache.

## Brand

The site uses the Decision Models brand kit in `brand/` at the repo root, copied to `site/brand/` by `scripts/export_site.py` (the same folder as the other portfolio apps; edit colors only in `brand/palette.py`, then run `python brand/build.py`). `data-app="valuation"` on `<html>` picks the indigo brand fill and the series order (indigo, teal, orange, sky, plum). `brand/css/brand.css` owns colors, Space Grotesk / JetBrains Mono, square corners and light/dark (dark by default, light follows the OS, the Theme button forces one); `assets/styles.css` maps the site's own token names onto it and hard-codes no colors. Hub bar first (← Decision Models, Jason C. Courtoy), then the header: 6px brand stripe, tile, name, the question and the status (In development). Footer: the brand disclaimer (personal project · public or synthetic data only · not investment advice · not endorsed by DoD or the U.S. Air Force) plus the market line and the FRED notice.

## Presentation standard

- Titles, headers, line items and buttons in Title Case (small words lower case, acronyms kept); notes in sentence case.
- Periods: `2025` reported fiscal year, `Q3 2026` fiscal quarter, `LTM Jun 2026`, `2027E` estimate; in charts and tables alike.
- Estimates shown: Years 1–4, then Year 5 and Year 10 (tagged), with LTM as a reference column. Year 1 is the fiscal year after the last 10-K (the closing year).
- $ millions with one decimal in tables; $5.76B in tiles; percentages one decimal; valuation multiples one decimal (`11.1x`, `NM` on a negative base); turnover two decimals; `–` = no data.
- Every card ends with a source line.

## Table formatting

Financial tables use a hybrid statement look (`finRow` / `acct` in `tables.js`, styles under "tables" in `styles.css`): accounting structure with modern shading.

| Row kind | Look | Used for |
|---|---|---|
| section (`group`) | uppercase heading with a rule under it | Income statement, Balance sheet, ratio groups |
| `head` | muted sub-heading, components indented under it | Operating expenses, Assets, Returned to shareholders |
| item (indent 1–2) | plain, indented | components |
| `sub` | bold on a light grey band | Gross profit, Operating income, Total current assets, EV, Equity value |
| `grand` | bold on an accent band | Net income, Total assets, Total liabilities and equity, Value per share |
| `key` | bold, no band | Revenue, RNOA, ROCE, CFO |
| `memo` | muted italic | EBITDA, D&A, Net debt, projected UFCF, PV |

Amounts: negatives in parentheses (positives reserve the ")" so digits align); costs, capex, buybacks and dividends shown as deductions. No row lines; rows highlight on hover. Number columns hug their figures and the label column takes the slack. Lists of companies (`table.list`) keep faint row lines and tint the target row. (Classic rules/double underlines and a fully modern style were compared; hybrid was chosen.)

## Pages

Overview · Results · Method, plus an owner's **Run ▸** link. The hash names the page or view: `#overview` (default), `#valuation`, `#company`, `#method`, `#run`; `#results` opens the last view used.

| Page | Shows |
|---|---|
| Overview | 03 · Deals, the one-line insight, a short explanation, See results / How it works, the headline card (middle 90% of simulated values per share, median, terminal value share, from the selected company's `dcf.json` → `details.simulation`), How it works in three steps, What it can't tell you, Built on |
| Results → Valuation (default) | Company picker, as-of and the view switch on top. Left column: company, key assumptions (the simulated ranges), run info (runs, seed, as-of, latest filing), JSON downloads. Right: KPI row (median per share, middle 90%, terminal value share, runs used); **Where the Methods Agree** football field (DCF (Simulated), comps, precedents, blend; Bear / Base / Bull toggle) with a *why they differ* line; **Spread of Simulated Outcomes** histogram (middle 90% solid, tails faded, median and price markers); **Sensitivity** (discount rate × terminal growth, darker = lower value); value vs price; company profile; comps; peer picker; DCF detail (bridge, discount rates, projection); similar companies (`docs/L2_reconcile.md`) |
| Results → Company Detail | KPI tiles; **Revenue**, **Returns**, **Margins**, **Cash Conversion** charts following the Annual / Quarterly / LTM switch; statements (five fiscal years, LTM, Years 1–4, 5 and 10, full-history download); ratios in five framework views; one **Sector** section (Sector › Group › Industry, Relative Performance, Companies; `docs/L1_sector.md`). Statements, Ratios and Sector are collapsible and remembered per browser |
| Method | On-page nav; Problem; Inputs and sources (a source per row); The model (Normalize, Value, Simulate, Reconcile); Validation checklist (Done / Done locally / Planned, matching what the tests actually cover); Limits; Changelog from `site/data/changelog.json` (parsed from `CHANGELOG.md`) |
| Run ▸ | **Company:** ticker, as-of, a *Company Details* box and one box per model (built: DCF, Comps). **Sector:** a company's sector (default), a taxonomy sector, SIC code, trait group or list. Starts the Pipeline action with a token, or links to the Actions page and prints the `gh` command |

On a phone the same content stacks: the KPI tiles become a 2×2 grid, the Method nav a horizontal scroller, touch targets ≥ 44px.

Light and dark themes follow the OS, with a manual toggle. The layout works down to phone width.

## One-time setup

1. Create an empty repository (for example `valuation`), then push this folder to `main`:

   ```bash
   git init -b main && git add . && git commit -m "Initial commit"
   git remote add origin https://github.com/<you>/valuation.git && git push -u origin main
   ```

2. **Settings → Pages → Source: GitHub Actions.**
3. **Settings → Secrets and variables → Actions → New repository secret:** `SEC_USER_AGENT` = `Your Name you@example.com`.
4. **Settings → Actions → General → Workflow permissions:** read and write (Pipeline and Refresh push the `site-data` branch).
   Optional: secret `ALPHAVANTAGE_API_KEY` (free key) for backup prices and the price cross-check (`docs/L0_market.md`).
5. Run a ticker from the **Run ▸** page, or run:

   ```bash
   gh workflow run pipeline.yml -f ticker=AAPL -f stop_after=L1
   gh workflow run pipeline.yml -f sector=sic-of:AAPL
   ```

   The site redeploys when it finishes.

For the Run tab's direct start button, create a **fine-grained personal access token** limited to this repository with **Actions: Read and write**; add **Contents: Read and write** so the peer picker can save `comps.json`. The token stays in your browser and is sent only to api.github.com. It's saved on the device only if you tick "Remember". Without a token, use the Actions page link.

## Demo

A pre-loaded demo shows every feature on synthetic companies run through the real pipeline code (L1 build, market block, DCF, comps, reconcile, sector screen, publish). It lives in its own data root, `site/demo/data`, so it never mixes with real tickers.

- **Demo button** (header) switches between the demo and your data; the choice is remembered per browser. `?demo=1` / `?demo=0` in the URL forces it (handy for sharing). A first visit to a site with no real data opens the demo.
- **Take the Tour** (strip under the header, demo only): 26 steps that switch page and company, open the section and highlight it: the Overview headline, tiles, Revenue, Returns, the period switch, statements and their `d` / `y` marks, ratios, sector levels, relative performance, the sector table, the KPI row, assumptions and run column, football field, spread of outcomes, sensitivity, value vs. price, profile, comps, peer picker, DCF, implied mode, the default case, similar companies, the Method page and the Run page. ← → move, Esc closes.
- **What's in it:** DEMO (mature manufacturer: your own dcf.json, comps against six detailed peers plus a hand-entered one, an illustrative precedents row, price checked against the backup source), DEMOG (high-growth software: implied mode, a price-mismatch flag), DEMOU (leveraged utility: default-case DCF, backup price source, two years of D&A filled from Yahoo-style fundamentals), ZZA–ZZF (detailed peers with default-case DCFs) and Demo Industrials (Synthetic): 23 companies across Capital Goods (Machinery, Electrical Equipment) and Transportation (Ground Transportation). All seeded, so every rebuild is identical; every name says "(synthetic)".
- **Always current:** the Pages workflow runs `python scripts/export_site.py` (which rebuilds the demo) on every deploy (and deploys when `src/valuation/` changes), so new features appear in the demo automatically. `site/demo/` is not committed.
- **Kept out of real data:** `publish` removes any demo-flagged company or sector from `site/data` (left there by older versions).

Locally: `python scripts/export_site.py` then `python -m http.server -d site 8000` and open `http://localhost:8000/?demo=1`.

## Local preview

```bash
scripts/site_data.sh load           # optional: the published companies from the site-data branch
python scripts/export_site.py       # brand, demo, changelog; publishes data/ → site/data and rebuilds the index
python -m http.server -d site 8000  # open http://localhost:8000
```

## What publish writes

- `company_detail.json` is a site slice (11 years annual, 16 quarters and LTM points, recent analysis); `company_detail_full.json` keeps everything and is linked from the statements card.
- JSON is compact. Each ticker keeps its latest 3 runs; older ones are removed from `site/data`.
- `companies.json` holds one card per company, with its classification, the top 10 similar companies and the top 25 ranked peers within each sector screen (`src/valuation/L3_app/similar.py`).
- `taxonomy.json` is copied for the level switch.

## What's public

The public site shows SEC-derived figures and the FRED risk-free rate only (showcase mode); real market prices and anything derived from them are not published. The example companies use synthetic market figures. The repository variable `SITE_MARKET_DATA=real` switches this off for a private site or licensed data (`docs/L0_market.md`).

Course workbooks and notes never enter the repo:

- parity-test paths live in `tests/course_cases.local.json`
- notes live in `notes_local/`

Both are gitignored.
