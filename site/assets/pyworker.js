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
const fetchText = (proxy) => (url) => {
  const x = new XMLHttpRequest();
  x.open("GET", `${proxy}?url=${encodeURIComponent(url)}`, false);
  x.send();
  if (x.status !== 200) throw new Error(`${x.status} from the proxy for ${url}: ${(x.responseText || "").slice(0, 200)}`);
  return x.responseText;
};

self.onmessage = async (e) => {
  const { id, ticker, asOf, models, proxy, saved } = e.data;
  const say = (progress) => self.postMessage({ id, progress });
  try {
    engine ||= await boot(say);
    say(`Fetching SEC filings for ${ticker} and building the models…`);
    const out = engine.run_json(ticker, fetchText(proxy), asOf || null, models || "dcf", JSON.stringify(saved || {}));
    self.postMessage({ id, ok: true, out });
  } catch (err) {
    self.postMessage({ id, ok: false, error: String(err?.message || err).split("\n").filter(Boolean).slice(-1)[0] });
  }
};
