// valuation (proxy): GET /?url=<https URL> for a short allowlist of public sources.
// - only the hosts and paths below; GET only; https only
// - only the Decision Models site (ALLOWED_ORIGINS) gets CORS headers
// - adds the contact User-Agent the SEC requires (secret SEC_USER_AGENT, else the SEC_CONTACT var)
// - caches responses at the edge, and spaces upstream SEC calls so one visitor can't
//   exceed the SEC's 10 requests a second from this Worker
// Market data: prices in the browser come from the visitor's own key (called directly, not
// through here). Yahoo is relayed only for localhost origins, i.e. the owner running the site
// on their own machine; for the public site's origin it is refused like any other host.

const ALLOW = [
  { host: "data.sec.gov", path: /^\/(api\/xbrl\/(companyfacts|companyconcept|frames)\/|submissions\/)/, ttl: 12 * 3600 },
  { host: "www.sec.gov", path: /^\/(files\/company_tickers\.json|cgi-bin\/browse-edgar)/, ttl: 24 * 3600 },
  { host: "fred.stlouisfed.org", path: /^\/graph\/fredgraph\.csv/, ttl: 6 * 3600 },
  { host: "pages.stern.nyu.edu", path: /^\/~adamodar\/New_Home_Page\/datafile\/(Betas|histimpl)\.html$/, ttl: 7 * 24 * 3600 },
  { host: "query1.finance.yahoo.com", path: /^\/(v8\/finance\/chart\/|ws\/fundamentals-timeseries\/)/, ttl: 15 * 60, localOnly: true },
];
const isLocal = (origin) => /^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(origin);
const BROWSER_UA = "Mozilla/5.0 (compatible; valuation-model/0.1)";
const SEC_HOSTS = new Set(["data.sec.gov", "www.sec.gov"]);
const MIN_GAP_MS = 150;            // per isolate: at most ~7 SEC requests a second
let lastSec = 0;

function cors(origin, env) {
  const allowed = (env.ALLOWED_ORIGINS || "").split(",").map((s) => s.trim());
  return allowed.includes(origin)
    ? { "Access-Control-Allow-Origin": origin, "Access-Control-Allow-Methods": "GET, OPTIONS", Vary: "Origin" }
    : null;
}

function fail(status, msg, headers = {}) {
  return new Response(JSON.stringify({ error: msg }), { status, headers: { "Content-Type": "application/json", ...headers } });
}

export default {
  async fetch(request, env, ctx) {
    const origin = request.headers.get("Origin") || "";
    const ch = cors(origin, env);
    if (!ch) return fail(403, "origin not allowed");
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: { ...ch, "Access-Control-Max-Age": "86400" } });
    if (request.method !== "GET") return fail(405, "GET only", ch);

    let target;
    try {
      target = new URL(new URL(request.url).searchParams.get("url") || "");
    } catch {
      return fail(400, "url parameter must be a full https URL", ch);
    }
    const rule = ALLOW.find((r) => r.host === target.hostname && r.path.test(target.pathname));
    if (target.protocol !== "https:" || !rule) return fail(403, "not an allowed source", ch);
    if (rule.localOnly && !isLocal(origin)) return fail(403, "Yahoo is relayed for local runs only", ch);
    const contact = env.SEC_USER_AGENT || env.SEC_CONTACT;
    if (SEC_HOSTS.has(target.hostname) && !contact) return fail(500, "no SEC contact: set SEC_CONTACT in wrangler.toml", ch);

    const cache = caches.default;
    const key = new Request(target.toString(), { method: "GET" });
    let res = await cache.match(key);
    if (!res) {
      if (SEC_HOSTS.has(target.hostname)) {
        const wait = lastSec + MIN_GAP_MS - Date.now();
        if (wait > 0) await new Promise((r) => setTimeout(r, wait));
        lastSec = Date.now();
      }
      const headers = { Accept: "application/json, text/html;q=0.9, text/csv;q=0.9, */*;q=0.5" };
      if (contact) headers["User-Agent"] = contact;   // the SEC requires it; FRED and NYU get the same polite contact
      if (rule.localOnly) headers["User-Agent"] = BROWSER_UA;
      const up = await fetch(target.toString(), { headers });
      res = new Response(up.body, up);
      res.headers.set("Cache-Control", `public, max-age=${rule.ttl}`);
      if (up.ok) ctx.waitUntil(cache.put(key, res.clone()));
    }
    const out = new Response(res.body, res);
    for (const [k, v] of Object.entries(ch)) out.headers.set(k, v);
    out.headers.delete("Set-Cookie");
    return out;
  },
};
