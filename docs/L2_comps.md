# L2 Public Comps

*Status: built. Inputs are `company_detail.json` (target), `configs/public/assumptions/{TICKER}/comps.json`, and `company_detail.json` for each SEC peer, which the pipeline ingests first.*

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
- `details`: the target row, peer rows (figures, EV, multiples, EBITDA margin, revenue CAGR, beta, implied prices, `match`), per-multiple ranges and averages, the blend, `match_rules`, and `closest` (the second set's peer rows, multiples and blend) when `comps.json` lists one.

## Parity

Checked against the three course workbooks: peer EV, EV/Sales, EV/EBITDA, each peer's implied target price for both multiples, and the peer averages all match to 1e-9. The course picks conservative and aggressive peers by judgment; the default `min_max` rule (lowest and highest implied price) reproduces those picks.

## Choosing peers: two sets

A sector is not always a good comparison: a peer in the same industry that grows at half the rate or carries five times the debt trades on different multiples. So comps values two sets, the way the course's Pub_Comps sheet asks of each peer "would you use this comparable?":

- **Sector Peers** (`peers` in `comps.json`): the traditional set from the target's own industry. When peers are picked automatically, the narrowest level (industry, then group, then sector) with at least six companies, nearest in size. This set is the model's value and carries the comps weight.
- **Closest Match** (`closest`, optional): the companies closest on fundamentals from anywhere in the sector screen (growth, margins, cash-flow stability, capital intensity, leverage and size; `L3_app/similar.py`). It is valued the same way, reported under `details.closest`, and reconciled as its own row, `comps_closest`, shown on the Valuation and Deal football fields without weight. Give it a weight in `reconcile.json` or the Deal weights to use it.

**How close each peer is.** Every peer in either set is checked against the target on five figures (`match` in each peer row):

| Figure | Close when |
|---|---|
| Revenue growth | within 3 points |
| EBITDA margin | within 3 points |
| Net debt / EV | within 5 points |
| Size (sales) | 0.5× to 2× the target's |
| Levered beta | within 0.3 |

A peer close on 2 or fewer of the figures it has is flagged **weak** (a note names it); it stays in the range until it is unticked in the peer picker. Fewer than three figures to compare is "unchecked". `"match": {"revenue_growth": 0.05}` in `comps.json` changes a tolerance. The site's "Similar companies" table ranks every published company by the same kind of closeness as a starting list.

**Share counts and missing prices.** Target and peer share counts come from the newest filed count (the 10-K/10-Q cover page, `shares_outstanding` in company detail), else the statements. If no peer has a price (the public site's showcase mode fetches none), comps raises `NoPeerPrices`, which the runner reports as a warning rather than a failure; type peer prices in `comps.json` to value against them.
