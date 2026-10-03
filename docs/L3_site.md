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

The one exception is the **projection what-if**. `site/assets/projection.js` is a line-for-line port of `core/projection.py`, and `tests/test_site_projection.py` runs both on the same inputs under Node, requiring identical results.

## Tabs

| Tab | Shows |
|---|---|
| Company detail | KPI tiles; revenue (annual, quarterly or TTM) and RNOA/ROCE charts; statements with derived quarters marked; ratios in five framework views |
| Projection | Driver form (growth fade, % of sales, ΔNWC/ΔSales, tax, financing); FCF chart; projected IS, MBS, CF and FCF with balance checks; drivers download as JSON |
| Valuation | Value vs price headline; football field with each method's range, selected value, upside, weight and reason, plus a Bear / Base / Bull toggle; company profile card; DCF detail; similar companies ranked by profile with multiples and rates (`docs/L2_reconcile.md`) |
| Run pipeline | Starts the Pipeline action. With a token it calls the GitHub API directly; without one it links to the Actions page and prints the `gh` command |

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
   ```

   The site redeploys when it finishes.

For the Run tab's direct start button, create a **fine-grained personal access token** limited to this repository with **Actions: Read and write**. The token stays in your browser and is sent only to api.github.com. It's saved on the device only if you tick "Remember". Without a token, use the Actions page link.

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
