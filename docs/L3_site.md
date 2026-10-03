# L3 App: GitHub Pages Site

*Status: built. Replaces the planned Streamlit app.*

## How it fits together

```
 Run pipeline tab ──► Pipeline action (workflow_dispatch)
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

The page does no valuation math. Projections are calculated in Python and published with the data: the DCF's projection when a DCF has run, otherwise the L1 trend case (`company_detail.json` → `projection`). There are no driver selectors on the site; to change a projection, edit `assumptions/{TICKER}/dcf.json` and rerun.

## Table formatting

Financial tables use a hybrid statement look (`finRow` / `acct` in `app.js`, styles under "tables" in `styles.css`): accounting structure with modern shading.

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
| Company detail | KPI tiles incl. projected revenue CAGR; revenue area chart (reported area from the TTM base, projection as a dashed line, Bear–Bull band = projected growth ± the DCF growth step, 1 pt for the trend case; tooltip shows growth); statements with derived quarters marked and, in the Annual view, a TTM base column plus five shaded estimate columns (DCF case, else trend case); a Growth and margins block (revenue growth, gross, EBITDA, operating, net margin) across history and estimates; projected unlevered FCF; ratios in five framework views; **Versus its sector** benchmarks and a **Sector** card with charts and a sortable table (`docs/L1_sector.md`) |
| Valuation | Value vs price headline; football field with each method's range, selected value, upside, weight and reason, plus a Bear / Base / Bull toggle; company profile card; DCF detail; comps peer picker from the company's sector (saves `comps.json`); similar companies ranked by profile with multiples and rates (`docs/L2_reconcile.md`) |
| Run pipeline | **Company:** ticker, as-of, a *Company details* box and one box per model (built: DCF, Comps). Details alone runs through L1; ticking a model runs through L2 and locks details on, since models use them. **Sector:** SIC code, a company's code, trait group or list. Starts the Pipeline action with a token, or links to the Actions page and prints the `gh` command |

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
5. Run a ticker from the **Run pipeline** tab, or run:

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
python -m L3_app.publish            # data/ → site/data, rebuild index.json, concepts.json and companies.json
python -m http.server -d site 8000  # open http://localhost:8000
```

## What's public

The site shows SEC-derived figures only. Market prices are left out until a licensed source is chosen; the public Altman Z and the market reference line on the football field appear once `raw_market.json` exists.

Course workbooks and notes never enter the repo:

- parity-test paths live in `tests/course_cases.local.json`
- notes live in `notes_local/`

Both are gitignored.
