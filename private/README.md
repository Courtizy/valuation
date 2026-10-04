# private/

Gitignored except this file. Personal-time inputs and outputs only; work data goes through
official channels, never a repo.

```
private/inputs.json            what app/run_private.py runs (tickers, models, as-of date)
private/assumptions/{TICKER}/  your own dcf.json / comps.json; falls back to configs/public/assumptions
private/data/                  pipeline outputs (real market prices allowed here)
private/site/                  a local copy of the site showing them: python -m http.server -d private/site
```
