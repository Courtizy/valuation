# Sector screens

A sector screen gives every company in a sector the same dozen figures, cheaply, so a company can be read against its sector and comps peers can be picked from it. Full company detail (statements, ratios, profile) is still built per company, when you open one.

```
python pipeline.py sector sic-of:AAPL                                # the whole sector a company belongs to (Technology)
python pipeline.py sector sector:technology                          # a sector of inputs/sectors/taxonomy.json
python pipeline.py sector sic:3674                                   # one SEC industry code
python pipeline.py sector "traits:stage=high growth;asset_intensity=light"
python pipeline.py sector list:example_chips                         # inputs/sectors/example_chips.json
```

From the site: **Run Pipeline → Sector**, or the **Screen {Sector}** button on Company Detail.

## Classification: sector › industry group › industry

SEC assigns each filer one four-digit SIC code, and a single code is often too narrow to compare against (Apple's 3571, Electronic Computers, has six filers). `sectors/taxonomy.json` groups SEC's 444 SIC codes into a GICS-style tree, so you read a company from the top down:

```
Technology                      sector          (11 sectors)
 └ Hardware & Equipment         industry group
    └ Hardware & Peripherals    industry        ← SIC 3571, 3572, 3575, 3577 …
```

- 439 codes are mapped. Five are left out on purpose (6189 asset-backed, 8880/8888 foreign governments, 9721 international affairs, 9995 non-operating shells).
- SIC 7370 sits under Communication Services › Interactive Media (GICS puts Alphabet and Meta there); 7371–7374 stay in Technology › Software & Services.
- `sectors/sic_codes.json` is SEC's official list, kept for reference. Each industry has an empty `naics` list reserved: SEC doesn't publish NAICS, so SIC stays the building block.
- `L1_detail/taxonomy.py` loads the tree: `classify(sic)` returns sector, group and industry with names.

**Default screen = the whole sector.** `sic-of:TICKER` looks up the company's SIC, classifies it, and screens every code in its sector, with a note such as "AAPL files under SIC 3571 (Electronic Computers): Technology › Hardware & Equipment › Hardware & Peripherals". Every member row carries its `sic` and `classification`, and the screen lists its `levels` (groups and industries with counts), so the site can narrow to the group or industry without another run.

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

**Members:** `sector` = EDGAR's list for every code in the sector ∩ companies with data; `sic` = one code's list ∩ companies with data; `list` = the file's tickers; `traits` = every company with data whose traits match. A sector keeps the 300 largest by revenue, the others 100 (`--limit` overrides), with notes on who was left out and why.

**Benchmarks:** Q1 / median / Q3 of each figure across the members. The site recomputes them for the group or industry level you pick.

Checked against real frames for NVDA, AMD, INTC, TXN, MU, QCOM, ADI and AAPL (`tests/fixtures/sec_frames_semis.json`).

## Output

`data/sectors/{id}/{as_of}/sector.json` (id `sector-technology`, `sic-3674`, `traits-stage-high-growth`, `list-example-chips`), published to `site/data/sectors/…`; `index.json` → `sectors` lists each sector's latest screen with its member tickers.

## On the site

| Where | What |
|---|---|
| Company Detail → **Sector** (collapsible; one breadcrumb Sector › Group › Industry with member counts drives both parts) | **Relative Performance:** each figure's Q1 / median / Q3, this company's value, gap to median (green favourable, red unfavourable, tiny gaps neutral) and a position bar; "Screen {Sector}" when no screen covers the company |
| | **Companies:** growth vs operating margin scatter (median crosshairs, dot size = revenue), revenue ranking, sortable table with an Industry column. Clicking a company opens it, or offers **Build Company Detail** (a Pipeline run through company details) |
| Valuation → **Comps Peers from …** | ranked by the one similarity score (`L3_app/similar.py`, computed at publish). Opens at the company's industry if it has 6+ members, else widens. Tick peers, type prices, **Save Peers**, then **Run Comps** (GitHub contents API; token needs Contents: Read and write). Peers the picker didn't show (hand-entered, or outside the level in view) are kept |
| Run Pipeline → **Sector** | a company's sector (default), a taxonomy sector, a SIC code, a trait group, or a list |
