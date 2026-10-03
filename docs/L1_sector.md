# Sector screens

A sector screen gives every company in a sector the same dozen figures, cheaply, so a company can be read against its sector and comps peers can be picked from it. Full company detail (statements, ratios, profile) is still built per company, when you open one.

```
python pipeline.py sector sic:3674                                   # SEC industry code
python pipeline.py sector sic-of:AAPL                                # the code a company files under
python pipeline.py sector "traits:stage=high growth;asset_intensity=light"
python pipeline.py sector list:example_chips                         # sectors/example_chips.json
```

From the site: **Run pipeline → Sector**, or the **Screen SIC …** button on Company detail.

## Sources (L0, `L0_ingest/sec_sector.py`)

| Source | What | Notes |
|---|---|---|
| SEC frames `api/xbrl/frames/us-gaap/{tag}/USD/{period}.json` | one line item for every filer in one call | `CY2025` = a ~year duration mapped to that calendar year; `CY2025Q4I` = an instant. A missing frame (404, e.g. retired tags) is recorded, not guessed |
| EDGAR company list `cgi-bin/browse-edgar?action=getcompany&SIC=…` | CIKs filed under an industry code, 100 per page | includes companies that stopped filing; the screen drops anyone without recent frames data |
| `submissions/CIK….json` | a company's own SIC code | also stored on every ingested company (`entity.sic`), so Company detail can offer "Screen SIC …" |
| `company_tickers.json` | CIK → ticker | first listed ticker per CIK (the main share class) |

About 70 frames per screen (each well under 1 MB), cached in `.cache/sec` and saved as `data/_screen/{as_of}/raw_screen.json`, so further sectors on the same date reuse them. The screen year is the latest calendar year most 10-Ks cover: as_of year − 1 from April, else year − 2.

## Figures per company (L1, `L1_detail/sector.py`)

Latest calendar year with revenue; a filer that hasn't reported it yet falls back one year and is flagged `stale`.

| Figure | Rule |
|---|---|
| Revenue | largest of `RevenueFromContractWithCustomerExcludingAssessedTax`, `Revenues`, `SalesRevenueNet`, `…IncludingAssessedTax` |
| Growth, 3-yr CAGR | same tags, earlier years (2-yr CAGR when three back is missing) |
| Gross, operating, net margin | `GrossProfit`, `OperatingIncomeLoss`, `NetIncomeLoss` ÷ revenue |
| EBITDA | operating income + D&A; D&A = a combined tag (`DepreciationDepletionAndAmortization`, …), else `Depreciation` + `AmortizationOfIntangibleAssets`; EBIT alone if neither (basis recorded) |
| Capex | `PaymentsToAcquirePropertyPlantAndEquipment`, else `PaymentsToAcquireProductiveAssets` |
| FCF, FCF margin and its stdev | operating cash flow − capex, three years |
| Debt | `LongTermDebt` (incl. current portion), else noncurrent + current; plus `ShortTermBorrowings` unless it equals the current portion (some filers tag the same amount twice) |
| Liabilities | `Liabilities`, else assets − equity |
| ROA, ROE, debt/EBITDA, liabilities/assets | from the above |

**Traits** use the same rules as the full company profile (`profile.py` → `classify_*`). Asset intensity uses capex/sales only (NOA turnover needs the full balance sheet). The stage rule checks *declining* (CAGR < 0) before *not yet profitable*, so a shrinking loss-maker is declining rather than high growth; this applies to full profiles too.

**Members:** `sic` = EDGAR's list ∩ companies with data; `list` = the file's tickers; `traits` = every company with data whose traits match. All keep the 100 largest by revenue (`--limit`), with notes on who was left out and why.

**Benchmarks:** Q1 / median / Q3 of each figure across the members.

Checked against real frames for NVDA, AMD, INTC, TXN, MU, QCOM, ADI and AAPL (`tests/fixtures/sec_frames_semis.json`).

## Output

`data/sectors/{id}/{as_of}/sector.json` (id `sic-3674`, `traits-stage-high-growth`, `list-example-chips`), published to `site/data/sectors/…`; `index.json` → `sectors` lists each sector's latest screen with its member tickers.

## On the site (layout: spread into existing tabs)

| Where | What |
|---|---|
| Company detail → **Versus its sector** | each figure's Q1 / median / Q3, this company's value, gap to median, and a position bar; a picker when the company is in several sectors; "Screen SIC …" when it's in none |
| Company detail → **Sector** | growth vs operating margin scatter, revenue ranking, sortable table. Clicking a company opens it, or offers **Build company detail** (a Pipeline run through company details) |
| Valuation → **Comps peers from …** | sector companies ranked by closeness (z-scores of growth, margins, FCF margin, capex intensity, leverage, size, plus shared traits); tick peers, type prices, **Save to comps.json** or **Save and run comps** (GitHub contents API; token needs Contents: read and write). Peers the picker doesn't show (hand-entered, or outside this sector) are kept |
| Run pipeline → **Sector** | SIC code, a company's code, a trait group, or a list |
