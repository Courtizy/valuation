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

**How close each peer is: the underlying value method.** The course's point: EV/EBITDA is a DCF over current EBITDA, so a good comparable has the target's DCF profile (pre-terminal growth, discount rate and long run), whatever its industry or size. Each peer is rated on the course's Pub_Comps comparison rows:

| Figure | Stands for | Green within | Source |
|---|---|---|---|
| Analysts' 5-year earnings growth | growth before the terminal year | 2 points | Yahoo's Analysis page (`earningsTrend` +5y), else Alpha Vantage's EPS estimates (next year only, labelled), else typed |
| Past 5-year earnings growth | a check on the forecast | 5 points | diluted EPS (else net income) from the filings, else Yahoo's −5y |
| Discount rate | the rate | 0.5 points | the market WACC estimate from beta (`company_detail.market.wacc`) |
| EBITDA margin | the long run: high margins tend to fall back | 3 points | filings |
| Net debt / EV | capital structure, so EV and market-value multiples compare alike | 5 points | filings and price |

Within twice the tolerance is yellow, beyond it red (the course's stoplight). **Closeness** = (greens + half the yellows) / figures rated. Size (sales against the target's) is shown but not rated: the course calls size a poor proxy for performance. A peer rated below 50% is flagged **weak**; fewer than three figures to rate is "unrated" and weighted at 50%.

**Peers weighted by closeness.** "Weight public comparables based on how close you can get": each peer's implied prices count by its closeness (weighted median and quartiles; the lowest and highest come from peers with weight). `details.blend` is that value; `details.blend_equal` is the same with every peer equal, shown next to it. `"peer_weights": "equal"` in `comps.json` makes equal weights the value. `details.peer_average` gives the simple and weighted peer averages of each rated figure and the multiples against the target, as the course compares the comp average with the target.

**Typing figures.** Analysts' growth has no free point-in-time source, so it can be typed: `growth_5y`, `growth_past_5y` or `discount_rate` on a peer's entry (it applies in both sets) or under `"target"`; the peer picker has a 5-Yr Growth % column and a box for the target. Typed figures win, and each figure's source is in `figure_sources`. Tolerances can be changed with `"match": {"growth_5y": 0.03}`.

The site's "Similar companies" table ranks every published company by the same kind of closeness as a starting list.

**Share counts and missing prices.** Target and peer share counts come from the newest filed count (the 10-K/10-Q cover page, `shares_outstanding` in company detail), else the statements. If no peer has a price (the public site's showcase mode fetches none), comps raises `NoPeerPrices`, which the runner reports as a warning rather than a failure; type peer prices in `comps.json` to value against them.

## Synthesized firm (third set)

The course's synthesized firm: peers from both sets weighted (on the simplex, by projected gradient) so their weighted growth, discount rate, EBITDA margin and net debt / EV come as close to the target's as possible, each gap measured in its tolerance. `details.synthesized` holds the weights, the blend against the target with a light per figure, the fit, and the implied value at the blend. It is reconciled as `comps_synth`, shown on the football fields without weight. `"synthesized": false` in `comps.json` turns it off.

**EV/Sales vs EV/EBITDA** (`details.sales_vs_ebitda`): EV/Sales is EV/EBITDA × EBITDA margin, so when the target's margin differs from the peers' the two multiples disagree; the note says which way and by how much.
