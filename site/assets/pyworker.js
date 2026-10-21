// The valuation engine in a web worker: Pyodide (Python compiled to WebAssembly) runs the same
// package as the pipeline, from py/valuation.zip (built by scripts/export_site.py). Data requests
// go through the proxy (worker/ in the repo) because the SEC doesn't allow browser requests.
const PYODIDE_VERSION = "0.29.4";
importScripts(`https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/pyodide.js`);

let engine = null;

async function boot(say) {
  say("Loading Python (first run only, about 10 MB)…");
  const py = await loadPyodide({ indexURL: `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/` });
  say("Loading the valuation engine…");
  const res = await fetch(new URL("../py/valuation.zip", self.location.href), { cache: "no-cache" });
  if (!res.ok) throw new Error(`engine package: HTTP ${res.status}`);
  py.unpackArchive(await res.arrayBuffer(), "zip", { extractDir: "/home/pyodide/pkg" });
  py.runPython("import sys; sys.path.insert(0, '/home/pyodide/pkg/src')");
  return py.pyimport("valuation.L3_app.web");
}

// Python calls this synchronously; a worker may block on XHR, the page never does.
// Alpha Vantage and Finnhub (the visitor's own keys) are called directly, at most one request
// a second; everything else, Yahoo included (local runs only), goes through the proxy.
const DIRECT = ["https://www.alphavantage.co/", "https://finnhub.io/"];
let lastDirect = 0;
const fetchText = (proxy) => (url) => {
  const direct = DIRECT.some((d) => url.startsWith(d));
  if (direct) { while (Date.now() < lastDirect + 1100) { /* free keys allow about one request a second */ } lastDirect = Date.now(); }
  const x = new XMLHttpRequest();
  x.open("GET", direct ? url : `${proxy}?url=${encodeURIComponent(url)}`, false);
  x.send();
  const shown = url.replace(/(apikey|token)=[^&]*/g, "$1=***");
  if (x.status !== 200) throw new Error(`${x.status} from the proxy for ${shown}: ${(x.responseText || "").slice(0, 200)}`);
  return x.responseText;
};

self.onmessage = async (e) => {
  const { id, ticker, sector, asOf, models, proxy, saved, assumptions, avKey, finnhubKey, yahoo } = e.data;
  const say = (progress) => self.postMessage({ id, progress });
  try {
    engine ||= await boot(say);
    let out;
    if (sector) {
      say(`Screening ${sector} from SEC filings (a few minutes: every company's figures for four years)…`);
      out = engine.run_sector_json(sector, fetchText(proxy), asOf || null, JSON.stringify(saved || {}));
    } else {
      say(`Fetching SEC filings for ${ticker}${avKey || finnhubKey || yahoo ? " and prices" : ""} and building the models…`);
      out = engine.run_json(ticker, fetchText(proxy), asOf || null, models || "auto", JSON.stringify(saved || {}),
        JSON.stringify(assumptions || {}), avKey || "", finnhubKey || "", !!yahoo);
    }
    self.postMessage({ id, ok: true, out });
  } catch (err) {
    self.postMessage({ id, ok: false, error: String(err?.message || err).split("\n").filter(Boolean).slice(-1)[0] });
  }
};
