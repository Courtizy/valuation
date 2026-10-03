# L3 App: GitHub Pages Site

*Status: built. Replaces the planned Streamlit app.*

## How it fits together

```
 Run Pipeline tab ──► Pipeline action (workflow_dispatch)
   (or Actions page,       pipeline.py run TICKER --stop-after L1|L2
    or gh CLI)             python -m L3_app.publish  → commits site/data/
                                   │
                                   ▼
                       Pages action (on push, or after Pipeline)
                           uploads site/ → GitHub Pages
                                   │
                                   ▼
                       Browser: index.html reads data/index.json,
                       data/{TICKER}/{as_of}/company_detail.json, comparison.json
```

GitHub Pages only serves static files, and the SEC API can't be called from a browser (no CORS, and it needs a contact User-Agent). So all fetching and computation runs in Actions; the page only renders.

The page does no valuation math. Projections are calculated in Python and published with the data: the DCF's projection when a DCF has run, otherwise the L1 trend case (`company_detail.json` → `projection`). There are no driver selectors on the site; to change a projection, edit `inputs/assumptions/{TICKER}/dcf.json` and rerun.

## Code layout (site/assets)

Plain ES modules, no build step. `main.js` loads `index.json`, concepts, companies and the taxonomy in parallel, then each run's files together.

| Module | Holds |
|---|---|
| `main.js` | start-up, company and run selection, tabs, theme |
| `state.js` | shared state, `$`, `getJSON`, banners |
| `format.js` | the presentation standard (below): numbers, periods, Title Case, labels |
| `tables.js` | statement rows (`finRow`, `acct`) |
| `charts.js` | SVG charts: column, line (dashed estimates), area, range, scatter, bar list, spread, grouped bars |
| `company.js` | Company Detail: tiles, Revenue, Returns, Margins, Cash Conversion, statements, ratios |
| `sector.js` | Versus Sector and Sector cards, level switch |
| `valuation.js` | headline, football field, profile, comps, peer picker, DCF, similar companies |
| `run.js`, `github.js` | Run Pipeline form; GitHub API (dispatch, read/write repo JSON) |

The Pages workflow stamps every stylesheet and module import with `?v=<commit>`, so a deploy is never hidden by the browser cache.

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

## Tabs

| Tab | Shows |
|---|---|
| Company Detail | KPI tiles (Revenue CAGR 5Y / 10Y projected); **Revenue** area chart (reported area, projection dashed, Bear–Bull band); **Returns**: RNOA and ROCE lines with the spread shaded green (leverage adds) or red (leverage subtracts), plus WACC; legend only, no definitions; **Margins** (gross, EBITDA, operating; estimates dashed); **Cash Conversion** (net income vs FCF, conversion in the tooltip); the four charts follow the Statements switch: Annual (with estimates), Quarterly (Returns as rolling LTM at each quarter end) or LTM; statements: five fiscal years, LTM reference, Years 1–4, 5 and 10 (DCF case, else the 10-year trend case), with a full-history download; ratios in five framework views; one **Sector** section: picker and Sector › Group › Industry switch, then **Relative Performance** (quartiles and gap to median) and **Companies** (charts and table) (`docs/L1_sector.md`). Statements, Ratios and Sector are collapsible: Statements open and the others closed on a first visit, then each viewer's choice is remembered in the browser |
| Valuation | Value vs price headline; football field (range, base, upside, weight; the reason on its own line; Bear / Base / Bull toggle; precedents tagged Illustrative); company profile; comps card with a dot plot of each peer's implied price (range = IQR with 4+ peers, else min–max); peer picker; DCF with EV bridge, discount rates, projection (Years 1–4, 5, 10, terminal) and a WACC × terminal growth sensitivity grid; similar companies (`docs/L2_reconcile.md`) |
| Run Pipeline | **Company:** ticker, as-of, a *Company Details* box and one box per model (built: DCF, Comps). Details alone runs through L1; ticking a model runs through L2 and locks details on. **Sector:** a company's sector (default), a taxonomy sector, SIC code, trait group or list. Starts the Pipeline action with a token, or links to the Actions page and prints the `gh` command |

Light and dark themes follow the OS, with a manual toggle. The layout works down to phone width.

## One-time setup

1. Create an empty repository (for example `valuation`), then push this folder to `main`:

   ```bash
   git init -b main && git add . && git commit -m "Initial commit"
   git remote add origin https://github.com/<you>/valuation.git && git push -u origin main
   ```

2. **Settings → Pages → Source: GitHub Actions.**
3. **Settings → Secrets and variables → Actions → New repository secret:** `SEC_USER_AGENT` = `Your Name you@example.com`.
4. **Settings → Actions → General → Workflow permissions:** read and write (the Pipeline job commits `site/data`).
5. Run a ticker from the **Run Pipeline** tab, or run:

   ```bash
   gh workflow run pipeline.yml -f ticker=AAPL -f stop_after=L1
   gh workflow run pipeline.yml -f sector=sic-of:AAPL
   ```

   The site redeploys when it finishes.

For the Run tab's direct start button, create a **fine-grained personal access token** limited to this repository with **Actions: Read and write**; add **Contents: Read and write** so the peer picker can save `comps.json`. The token stays in your browser and is sent only to api.github.com. It's saved on the device only if you tick "Remember". Without a token, use the Actions page link.

## Demo data

```bash
python -m L3_app.demo
```

This writes three synthetic companies (`DEMO` manufacturing, `DEMOG` high-growth software, `DEMOU` leveraged utility), built by the real L1 build from made-up records, so the profile, method plan and similar-companies table have contrasting cases. Each gets a real DCF on made-up market inputs plus synthetic comps and precedents. Everything is flagged `demo: true`, and the site shows a banner. Delete `site/data/DEMO*` once real tickers are published, then run `python -m L3_app.publish`.

## Local preview

```bash
python -m L3_app.publish            # (after pip install -e ., or with PYTHONPATH=model) data/ → site/data, rebuild index.json, concepts.json and companies.json
python -m http.server -d site 8000  # open http://localhost:8000
```

## What publish writes

- `company_detail.json` is a site slice (11 years annual, 16 quarters and LTM points, recent analysis); `company_detail_full.json` keeps everything and is linked from the statements card.
- JSON is compact. Each ticker keeps its latest 3 runs; older ones are removed from `site/data`.
- `companies.json` holds one card per company, with its classification, the top 10 similar companies and the top 25 ranked peers within each sector screen (`L3_app/similar.py`).
- `taxonomy.json` is copied for the level switch.

## What's public

The site shows SEC-derived figures only. Market prices are left out until a licensed source is chosen; the public Altman Z and the market reference line on the football field appear once `raw_market.json` exists.

Course workbooks and notes never enter the repo:

- parity-test paths live in `tests/course_cases.local.json`
- notes live in `notes_local/`

Both are gitignored.
