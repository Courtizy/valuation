# Valuation L0 — Financial Statement Ingestor (SEC companyfacts)

*Status: schema 0.2.0. Scope: L0 only. Output: `raw_filing.json`.*

## Purpose

Fetch a company's XBRL facts from the SEC companyfacts API, cache the raw payload, and write one flat, schema-checked `raw_filing.json` for L1 (Company Detail) to normalize and build on.

## What L0 does and doesn't do

L0 **does**: resolve ticker → CIK, fetch, cache the exact bytes, flatten the nested JSON into fact records, sort deterministically, hash the source, validate.

L0 **does not**: dedupe, pick "the latest" value, filter forms, map tags to canonical line items, or handle restatements. Those are judgement calls and belong to L1, where the sector pack lives. Keeping L0 faithful means any L1 bug can be diagnosed against an untouched source.

## Source details

| Item | Value |
|---|---|
| Ticker map | `https://www.sec.gov/files/company_tickers.json` |
| Facts | `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json` (10-digit, zero-padded) |
| User-Agent | Required, must include contact info (`$SEC_USER_AGENT` or `--user-agent`) |
| Rate limit | SEC fair-access limit is 10 req/s; client spaces requests ≥ 0.12 s apart |
| Retries | 429 and 5xx, exponential backoff, max 3; 404 fails immediately |

## Output contract: `raw_filing.json` (schema 0.2.0)

```jsonc
{
  "schema_version": "0.2.0",
  "source": "sec_companyfacts",
  "source_url": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
  "retrieved_at": "2026-10-02T13:20:00+00:00",  // time of the network fetch, even when served from cache
  "from_cache": false,
  "content_sha256": "…",                         // hash of the raw source bytes
  "entity": {"cik": "0000320193", "name": "Apple Inc.", "ticker": "AAPL"},
  "facts": [
    {
      "taxonomy": "us-gaap", "tag": "Revenues", "label": "Revenues",
      "description": "Amount of revenue recognized from …",  // taxonomy definition, repeated per fact
      "unit": "USD", "value": 383285000000,
      "start": "2022-09-25", "end": "2023-09-30",   // start is null for instant facts
      "fy": 2023, "fp": "FY", "form": "10-K",
      "filed": "2023-11-03", "accn": "0000320193-23-000106",
      "frame": "CY2023"                             // null when SEC didn't assign one
    }
  ]
}
```

Required on every fact: `taxonomy, tag, unit, value (numeric), end, form, filed, accn`. Always present but nullable: `label, description, start, fy, fp, frame`. Facts are sorted by `(taxonomy, tag, unit, end, start, filed, accn)`, so the same source gives a byte-identical file.

## Field mapping to SEC source

Field names are ours and stable; this table is the trace back to the SEC JSON.

| raw_filing.json | SEC companyfacts | Note |
|---|---|---|
| `taxonomy` | key under `facts` (e.g. `us-gaap`, `dei`) | derived from nesting |
| `tag` | concept key (e.g. `Revenues`) | XBRL calls this a *concept* or *element* |
| `label` | concept `label` | standard taxonomy label, **not** the company's line-item text |
| `description` | concept `description` | taxonomy definition; null if absent |
| `unit` | key under `units` (e.g. `USD`, `shares`, `USD/shares`) | derived from nesting |
| `value` | `val` | **renamed** |
| `start`, `end`, `fy`, `fp`, `form`, `filed`, `accn`, `frame` | same | verbatim |
| `entity.cik` | `cik` (int) | zero-padded 10-char string |
| `entity.name` | `entityName` | renamed |

## Data integrity caveats

- **`label` ≠ what the filing shows.** It's the shared dictionary label. Apple's "Total net sales" arrives as `Revenues` / "Revenues". Company-specific wording isn't in companyfacts.
- **`fy`/`fp` belong to the filing, not the period.** A prior-year comparative in the FY2023 10-K has `fy: 2023`. L1 must key periods on `start`/`end`.
- **No dimensions.** Companyfacts holds only company-wide totals; segment and geographic breakdowns are absent, so totals won't always tie to filing detail.
- **No precision attribute.** Values are as reported (often rounded to millions); treat small differences between sources as possible rounding.
- **`frame` ending in `I` means an instant** (balance-sheet date), e.g. `CY2023Q3I`.
- **Size cost of `description`.** It repeats on every fact for a tag. If files get too large, move it to a top-level `concepts` map keyed by `taxonomy:tag` in a later schema version.

## Changelog

- **0.2.0** — added nullable `description` on every fact. 0.1.0 files fail validation (missing key).
- **0.1.0** — initial contract.

## Layout

```
valuation/
  L0_ingest/
    __init__.py
    __main__.py          # CLI
    schema.py            # SCHEMA_VERSION + validate_raw_filing()
    http.py              # stdlib client: UA, throttle, retry
    cache.py             # file cache with TTL, atomic writes
    sec_companyfacts.py  # adapter + flatten_facts()
  tests/
    fixtures/            # trimmed sample payloads, no network needed
    test_L0_sec_companyfacts.py
  docs/L0_ingestor_design.md
  pyproject.toml
```

Stdlib-only at runtime. `pytest` is the only dev dependency.

## Usage

```bash
export SEC_USER_AGENT="Your Name you@example.com"
cd valuation
python -m L0_ingest sec-companyfacts --ticker AAPL --out data/raw/AAPL/raw_filing.json
python -m L0_ingest validate data/raw/AAPL/raw_filing.json
pytest
```

From Python:

```python
from L0_ingest import SecCompanyFactsAdapter
from L0_ingest.cache import FileCache

doc = SecCompanyFactsAdapter(cache=FileCache(".cache/sec")).fetch(ticker="AAPL")
```

## Design decisions

- **Adapter takes an injected client.** Anything with `get_bytes(url) -> bytes` works, which is how the tests run offline and how a future adapter (local files, another vendor) slots in.
- **Cache stores raw bytes, not parsed JSON.** The hash and any re-flatten come from exactly what SEC sent. The file's mtime doubles as `retrieved_at`.
- **Lazy HTTP client.** A cache-only run never needs a User-Agent, so offline demos work.
- **Comparative-period duplicates are kept.** A 10-K reports prior-year figures again under a new `accn`; L0 keeps both rows.

## Open questions for L1 handoff

- Dedupe rule: prefer `frame`-tagged facts, or latest `filed` per `(tag, start, end)`?
- Amendments (`10-K/A`) and restatements: override originals, or keep both with a flag?
- Fiscal vs calendar periods: does L1 key on `fy/fp` or on `start/end` dates?
- Should L0 accept a `--forms 10-K,10-Q` pre-filter purely for file size, or stay unfiltered?

## Next steps

1. Run against 3–5 real tickers and spot-check fact counts and file sizes.
2. Add a JSON Schema file (`raw_filing.schema.json`) mirroring `schema.py` for non-Python readers.
3. Second adapter (local file / companyconcept) to prove the interface.
4. Start L1: tag → canonical line item mapping for one sector pack.
