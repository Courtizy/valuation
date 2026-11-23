# Apple: its own growth case, and what the price implies

*Built from Apple's 10-K XBRL (FY2026 10-K filed 2026-11-03, FY2023 10-K filed 2023-11-03) and the site's market data on 2026-11-23. Analysis of method, not investment advice.*

**The question.** What growth can Apple's own filed history support, and how far is that from the growth its share price implies?

## Answer

| | Value |
|---|---:|
| Revenue growth, year 1 (FY2027), Apple's own case | **6.1%**, fading to 3% |
| Growth the $352 price implies in year 1, on a straight fade to 3% | **21.3%** |
| DCF value per share, 9.5% WACC | **$185.62** (simulated range $130–$287) |
| Blended value (DCF 60%, comps 40%) | $228.32, 35% below the price |

1. **The case is built line by line.** iPhone, Services, Mac, iPad and Wearables each grow at their own five-year CAGR (FY2021–FY2026) and fade to 3% over ten years. Services compounds fastest (12.5%), so its share of sales rises from 25.7% to 34.8%. Services costs 23.8% of its sales against 60.7% for products, so total cost of sales falls from 51.2% to 47.9% of sales.
2. **The price needs about three and a half times that growth.** At today's rates, the $352 price is reached only with 21% year-1 growth. Apple has grown that fast in one year of the last five: FY2021, at 33%.
3. **The comparison with similar companies is the weak link.** The comps peers picked on size and margin are Dell, NetApp, Seagate, Western Digital, Fortinet and Palo Alto Networks. Their median five-year growth is 4.7%, close to Apple's own case. But their EV/EBITDA averages 47x, against the 12.5x the DCF implies at exit, because two security software firms sit in the set. As the course warns, companies alike in size and margin aren't necessarily alike in what drives value.

## Inputs

| Line | FY2021 sales | FY2026 sales | Five-year CAGR |
|---|---:|---:|---:|
| iPhone | $192.0B | $254.1B | 5.8% |
| Services | $68.4B | $123.3B | 12.5% |
| Mac | $35.2B | $37.9B | 1.5% |
| iPad | $31.9B | $27.9B | −2.6% |
| Wearables, Home and Accessories | $38.4B | $35.6B | −1.5% |
| **Total** | **$365.8B** | **$478.8B** | **5.5%** |

All figures come from [`inputs.json`](inputs.json), with the accession of each one. The script checks that the five lines add up to total sales in every year. FY2021 and FY2026 were both strong iPhone years (5G, then FY2026's +21%), so the iPhone CAGR runs peak to peak.

## Reproduce and challenge it

```bash
python studies/apple-fy2027/case.py --check   # prints the case, writes results.json, checks AAPL's dcf.json
pytest tests/test_study_apple.py
```

To refreeze the inputs from EDGAR: `SEC_USER_AGENT="Name email" python studies/apple-fy2027/build_inputs.py`.

## Limits

- **Margins.** Each line keeps its FY2026 cost ratio. Operating expenses keep their share of sales.
- **History.** Five years of history is short. Moving the start or end year by one changes the iPhone CAGR by a point or more.
- **Peers.** The similar-companies check uses the comps peers as picked. A peer set chosen on the value drivers (growth, margin, return on capital, risk) is the next step.
