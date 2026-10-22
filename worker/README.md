# valuation (Cloudflare Worker proxy)

The in-browser Run reads SEC filings, FRED and Damodaran's tables through this Worker. Browsers can't
call the SEC directly: it sends no CORS headers and requires a contact User-Agent.

- **Allowlist only:** `data.sec.gov` (companyfacts, frames, submissions), `www.sec.gov` (ticker list,
  EDGAR company browse), `fred.stlouisfed.org` (fredgraph.csv) and Damodaran's two pages. Anything else gets 403.
- **Only the site may call it from a browser:** CORS headers are sent only to `ALLOWED_ORIGINS` (`wrangler.toml`). A script can fake an Origin, so the allowlist and the edge cache are what actually bound it: it can only ever fetch these public pages.
- **Polite to the SEC:** adds the contact User-Agent (`SEC_CONTACT` in `wrangler.toml`, or a `SEC_USER_AGENT` secret if set), caches responses at the edge (12 h for filings), and
  spaces SEC calls per isolate.
- **Market data.** Yahoo (`query1.finance.yahoo.com` chart and fundamentals, and `query2` quoteSummary for `modules=earningsTrend` only: analysts' five-year growth, which needs Yahoo's session cookie and crumb, fetched by the Worker and kept for an hour) is relayed for the site, with a browser User-Agent. Alpha Vantage and Finnhub, with the visitor's own key, are called directly by their browser, not through here.
- **EDGAR's company lists by SIC** (`www.sec.gov/cgi-bin/browse-edgar`) stay on the allowlist, but the SEC answers the Worker with "Access Denied"; the site reads the lists the weekly Refresh publishes instead (`site/data/sic_members.json`).

## Set up (once)

1. Cloudflare dashboard → **Workers & Pages → Create → Import a repository** → `Courtizy/valuation`.
2. **Root directory:** `worker`. Build command: leave blank. Deploy command: `npx wrangler deploy`.
3. The SEC contact is `SEC_CONTACT` in `wrangler.toml`, so it deploys with the code. To keep it out of
   the repo instead, add a **Secret** `SEC_USER_AGENT` under the Worker's Settings → Variables and Secrets; it wins.
4. The Worker URL (`https://valuation.jason-courtoy.workers.dev`) is `PROXY_URL` in
   `site/assets/config.js`. A visitor can paste another under **Data Proxy** on the Run page.

Every push to `main` that changes `worker/` redeploys it.

## Check it

```bash
curl -H "Origin: https://courtizy.github.io" \
  "https://valuation.jason-courtoy.workers.dev/?url=https://data.sec.gov/submissions/CIK0000320193.json" | head -c 200
```

Free plan: 100,000 requests a day. One company is about three SEC requests, and repeat views come from the edge cache.
