# L2 Public Comps

*Status: built. Inputs are `company_detail.json` (target), `inputs/assumptions/{TICKER}/comps.json`, and `company_detail.json` for each SEC peer, which the pipeline ingests first.*

## Peers

- **SEC peers.** A peer listed by ticker gets its sales, EBITDA, net income, debt, cash and shares from its own filings (latest TTM, else latest fiscal year). Its **price** comes from `comps.json` until a market-data adapter exists.
- **Manual peers.** `"sec": false` adds a peer from typed figures, for example a foreign filer or a private benchmark.
- **Overrides.** Any SEC figure can be overridden in the peer's entry.
- **Failures don't stop the run.** A peer that fails to ingest is reported, and the target's run continues.

## Math (matches the course public-comps sheet)

- Market value = price × shares.
- Net debt = (short-term + long-term debt) − cash and short-term investments.
- EV = market value + net debt.
- Multiples are EV/Sales, EV/EBITDA and P/E, each used only when positive. Peer averages count positive multiples only.
- Implied target price:
  - (multiple × target metric − target net debt) ÷ target shares, for EV multiples.
  - multiple × target net income ÷ target shares, for P/E.
- **Range:**
  - `min_max` (course default): lowest / median / highest implied price across peers.
  - `quartiles`: Q1 / median / Q3.
- **Blend.** Multiples are combined with `weights` (equal by default). A multiple whose target metric isn't positive is dropped with a note; for example, P/E is dropped for a loss-maker.

## Output

- `value_per_share`: conservative / expected / aggressive, shown as Bear / Base / Bull.
- `details`: the target row, peer rows (figures, EV, multiples, EBITDA margin, revenue CAGR, implied prices), per-multiple ranges and averages, and the blend.

## Parity

Checked against the three course workbooks: peer EV, EV/Sales, EV/EBITDA, each peer's implied target price for both multiples, and the peer averages all match to 1e-9. The course picks conservative and aggressive peers by judgment; the default `min_max` rule (lowest and highest implied price) reproduces those picks.

## Choosing peers

Peers should share the target's characteristics (stage, predictability, asset intensity, leverage), not just its sector. The site's "Similar companies" table ranks every published company by those traits as a starting list.
