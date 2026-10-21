import { PROXY_URL } from "./config.js";
import { clearDevice, deviceIndex, runHere, saveAssumption, saveDevice } from "./device.js";
import { setStatus } from "./status.js";
import { esc } from "./format.js";
import { $, getJSON, state, store } from "./state.js";

let showDevice = null, route = null;    // injected by main.js (avoids a circular import)
export function setRunHooks(hooks) { ({ showDevice, route } = hooks); }

// ---- Run in this browser (anyone) -------------------------------------------------
const proxyUrl = () => ($("h-proxy").value.trim() || PROXY_URL).replace(/\/+$/, "");
const avKey = () => $("h-avkey").value.trim();
const finnhubKey = () => $("h-fhkey").value.trim();

/** What the site has published that a browser run can lean on: EDGAR's company lists by SIC code
 *  (the SEC refuses that page to the proxy, so sector screens read these), and for a company run
 *  the published sector screens that include it (to pick its comps peers without screening). */
async function published(ticker) {
  const sic = await getJSON("data/sic_members.json").then((d) => d.sic || {}).catch(() => ({}));
  if (!ticker) return { sic };
  const index = await getJSON("data/index.json").catch(() => ({}));
  const mine = (index.sectors || []).filter((x) => !x.demo && (x.members || []).includes(ticker));
  const screens = await Promise.all(mine.map((x) => fetch(`data/${x.path}`, { cache: "no-cache" }).then((r) => (r.ok ? r.text() : null)).catch(() => null)));
  return { sic, screens: screens.filter(Boolean) };
}

function renderSaved() {
  const list = deviceIndex()?.companies || [], sectors = deviceIndex()?.sectors || [];
  const what = [...list.map((c) => `<b>${esc(c.ticker)}</b> (${c.runs.length} run${c.runs.length > 1 ? "s" : ""})`),
    ...sectors.map((x) => `<b>${esc(x.label || x.id)}</b> screen`)];
  $("h-saved").innerHTML = what.length
    ? `Saved on this device: ${what.join(", ")}. <button type="button" class="linkish" id="h-clear">Clear</button>`
    : '<span class="muted">Nothing saved on this device yet.</span>';
  const clear = $("h-clear");
  if (clear) clear.onclick = async () => {
    if (!confirm("Remove every run, sector screen and peer list saved in this browser?")) return;
    await clearDevice(); renderSaved(); await showDevice?.(null);
  };
}

/** Run a company ({ticker, models}) or screen a sector ({sector}) in this browser, keep it on
 *  this device and open it. Progress and the outcome go to the status element. */
export async function runInBrowser(job, status) {
  const asOf = job.asOf || new Date().toISOString().slice(0, 10);
  if (!proxyUrl()) { setStatus(status, { ok: false, msg: "The data proxy isn't set up: add its URL on the Run page under Settings." }); return false; }
  status.className = "status"; status.textContent = "Starting…";
  try {
    const prices = job.sector ? {} : { avKey: avKey(), finnhubKey: finnhubKey(), yahoo: true };
    const out = await runHere({ ...job, asOf, proxy: proxyUrl(), ...prices, ...(await published(job.ticker)) },
      (msg) => { status.textContent = msg; });
    const failed = out.report.filter(([, st]) => st === "failed");
    const built = job.sector ? !failed.length : !!out.files[`${job.ticker}/${asOf}/company_detail.json`];
    if (!built) throw new Error(failed.map(([step, , msg]) => `${step}: ${msg}`).join("; ") || "nothing was built");
    await saveDevice(out.files);
    for (const [rel, text] of Object.entries(out.assumptions || {})) await saveAssumption(rel, JSON.parse(text));   // peers it picked
    renderSaved();
    const done = { ok: !failed.length, msg: failed.length
      ? `Done, with problems: ${failed.map(([step, , msg]) => `${step} (${msg})`).join("; ")}`
      : `Done. ${job.sector ? "The screen" : job.ticker} is saved on this device.` };
    setStatus(status, done);
    await showDevice?.(job.sector ? null : job.ticker);
    const again = status.id && document.getElementById(status.id);     // the page re-rendered: keep the outcome in view
    if (again && again !== status) setStatus(again, done);
    return true;
  } catch (err) {
    setStatus(status, { ok: false, msg: `Run failed: ${err.message}` });
    return false;
  }
}

export function setupHereForm() {
  $("h-proxy").value = store.get("proxy_url") || "";
  $("h-avkey").value = store.get("av_key") || "";
  $("h-fhkey").value = store.get("finnhub_key") || "";
  $("h-asof").value = new Date().toISOString().slice(0, 10);
  $("h-go").disabled = $("h-screen").disabled = false;   // off in the HTML until wired, so an early click can't submit the page
  renderSaved();
  const remember = () => {
    store.set("proxy_url", $("h-proxy").value.trim() || null);
    store.set("av_key", avKey() || null);
    store.set("finnhub_key", finnhubKey() || null);
  };
  $("h-proxy").onchange = $("h-avkey").onchange = $("h-fhkey").onchange = remember;
  const busy = async (btn, work) => { btn.disabled = true; try { await work(); } finally { btn.disabled = false; } };
  $("here-form").onsubmit = (e) => {
    e.preventDefault();
    remember();
    const ticker = $("h-ticker").value.trim().toUpperCase();
    if (!/^[A-Z][A-Z0-9.\-]{0,9}$/.test(ticker)) { setStatus($("h-status"), { ok: false, msg: "Enter a valid ticker." }); return; }
    busy($("h-go"), () => runInBrowser({ ticker, asOf: $("h-asof").value, models: "auto" }, $("h-status")));
  };
  $("h-screen").onclick = () => {
    remember();
    busy($("h-screen"), () => runInBrowser({ sector: `sector:${$("h-sector").value}`, asOf: $("h-asof").value }, $("h-status")));
  };
}

/** Fill the Sector list from the taxonomy (called once it has loaded). */
export function fillSectorList() {
  if (!state.taxonomy) return;
  const opts = state.taxonomy.sectors.map((x) => `<option value="${esc(x.id)}">${esc(x.name)}</option>`).join("");
  if ($("h-sector")) $("h-sector").innerHTML = opts;
}
