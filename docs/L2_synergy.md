# L2 Synergy Models (acquisition)

*Status: built. Two models, `dcf_synergy` and `just_synergy`, live in `L2_models/dcf/synergy.py` (they reuse the standalone DCF's inputs). The math is in `_core/synergy.py`. Inputs come from `company_detail.json`, `dcf.json` (or the default case) and `configs/public/assumptions/{TICKER}/deal.json` (on the site, the deal saved on the device).*

## Inputs (`deal.json`)

| Field | Course cell | Meaning |
|---|---|---|
| `pre_announcement_price` | Inputs_Results B9 | default: the market price |
| `offer_price` | Summary C29 | the actual or initial offer, for comparison |
| `relative_power` | Summary C35 | 0 = buyer holds the bargaining power, 1 = target |
| `synergies.annual_cost` | F17 | $ per year once fully realized |
| `synergies.revenue_pct_of_cost` | F18 | revenue synergies as a share of cost synergies |
| `synergies.one_time_cost` | F19 | default 2 × (cost + revenue synergies) |
| `synergies.years_to_full` | F20 | |
| `synergies.cost_forever` | F15 | share of cost synergies that lasts past the terminal year |
| `synergies.revenue_growth_add` | F13 | whole firm: added to revenue growth from year 1 |
| `synergies.cost_realized` | F14 | whole firm: share of the cost cut achieved |
| `synergies.cost_pct` | O4 / O5 | whole firm: cut to COGS and SG&A; default annual_cost / base-year (COGS + SG&A) |
| `weights` | Summary F | per method; see the summary below |

Template: `configs/public/assumptions/_template/deal.json`.

## Just synergies

Year 0 is the closing year (undiscounted); year t is discounted at (1 + WACC)^t.

    cost_t      = 0 in year 0; S·t/N while phasing in; S·(1+g)^(t−N) once full; 0 after the terminal year T
    revenue_t   = cost_t · r
    one-time_t  = C/N in years 0 … N−1
    after tax   = (cost + revenue − one-time) · (1 − tax)
    terminal    = (cost_T · f + revenue_T) · (1 − tax) · (1 + g_T) / (WACC_T − g_T)

Value per share = pre-announcement price + Σ PV / shares. The range moves the annual synergies by ±25%; sensitivity grids are annual synergies × lasting share and annual synergies × terminal year.

## Whole firm with synergies

The standalone projection with synergies in its drivers: revenue growth + `revenue_growth_add` from year 1, and COGS and SG&A ratios multiplied by (1 + adj), where adj = +s in year 0 (integration), −s·t/N while phasing in, −s until the terminal year and −s·f in it (s = cost_pct × realized). Valued exactly like the standalone DCF. The range moves realized ±25 points and revenue growth ±0.5 points, as the course's sensitivity table does.

## Summary (`L2_models/reconcile/deal.py`, `comparison.json` → `deal`)

Each method gives conservative / best guess / aggressive per share (DCF: course scenarios; synergy models: the ranges above; prior deals: five rows from [L2_precedents.md](L2_precedents.md); comps and others: p10 / p50 / p90; the 52-week low, pre-announcement price and high). The weights are the course template's defaults.

| Side | Default weights |
|---|---|
| Standalone | comps 20%, prior deals' pre-announcement EV/Sales 10% and EV/EBITDA 10%, DCF 40%, 52-week range 20% |
| Offer | prior deals' transaction EV/Sales 2%, EV/EBITDA 2% and premium paid 30%, whole firm with synergies 33%, just synergies 33%, LBO 0% |

A method with no value passes its weight to the rest. Standalone range = weighted values. Offer range: conservative = weighted conservative values; aggressive = weighted aggressive values except the synergy methods at their best guess; best guess = conservative + (aggressive − conservative) × relative power. Premiums are against the pre-announcement price; "share of synergies" is how much of the gap between that price and the top of the offer range a price pays to the target.

## Parity (local workbooks)

`tests/test_course_parity.py`: Just Syn year-by-year PVs, total, per share and max premium; Firm DCF Syn revenue, EBITDA, FCF, EV and price per share; the Summary sheet's standalone and offer ranges, premium and synergy share, fed the sheet's own rows. Passing on the TSYS (v73) and Tower (v80) workbooks. v73's standalone best guess is the midpoint of the range; v80 weights the best guesses, which is what the model does.

## Not yet

The LBO. Its row shows in the summary with no value until then.
