import { renderCashChart, renderCompany, renderMarginChart, renderRatios, renderReturnsChart, renderRevenueChart, renderStatements } from "./company.js";
import { esc } from "./format.js";
import { fillSectorList, setRunHooks, setupHereForm } from "./run.js";
import { loadSector } from "./sector.js";
import { deviceIndex, loadDevice } from "./device.js";
import { $, banner, device, getJSON, runRoot, state, store } from "./state.js";
import { renderValuation } from "./valuation.js";
import { setTourHooks, startTour } from "./tour.js";
import { renderMethod, renderOverview } from "./pages.js";

// Demo mode: the pre-loaded demo (site/demo/data, rebuilt on every deploy) instead of the real data.
// Chosen by ?demo=1 / ?demo=0, else the viewer's last choice, else demo when there's no real data yet.
async function chooseMode() {
  const q = new URLSearchParams(location.search).get("demo");
  if (q === "1" || q === "0") store.set("mode", q === "1" ? "demo" : "live");
  let mode = store.get("mode");
  if (!mode) {                          // first visit: real data if there is any, published or run on this device
    const live = await getJSON("data/index.json").catch(() => null);
    mode = live?.companies?.length || deviceIndex()?.companies?.length ? "live" : "demo";
  }
  state.demoMode = mode === "demo";
  state.root = state.demoMode ? "demo/data/" : "data/";
  const btn = $("demo-toggle");
  btn.setAttribute("aria-pressed", String(state.demoMode));
  btn.textContent = state.demoMode ? "Exit Demo" : "Demo";
  btn.onclick = () => {
    store.set("mode", state.demoMode ? "live" : "demo");
    const url = new URL(location.href);
    if (url.searchParams.has("demo")) { url.searchParams.delete("demo"); location.replace(url.toString()); }
    else location.reload();
  };
  $("mode-strip").hidden = !state.demoMode;
  $("tour-start").onclick = startTour;
  setTourHooks({ selectCompany, route });
  setRunHooks({ showDevice, route });
}

// Companies run in this browser are listed after the published ones, marked "on this device".
// Their key is "device:TICKER", so a ticker can be both published and run here. Sectors screened
// here come first, so a company shows its newest screen; their similarity cards join companies.json.
export const keyOf = (c) => (c.device ? `device:${c.ticker}` : c.ticker);
let published = null;                   // the site's own index and company cards, before device runs join

function mergeDevice() {
  const mine = state.demoMode ? null : deviceIndex();
  const { index, companies } = published;
  state.index = { ...index,
    companies: [...index.companies, ...(mine?.companies || []).map((c) => ({ ...c, device: true }))],
    sectors: [...(mine?.sectors || []).map((x) => ({ ...x, device: true })), ...(index.sectors || [])] };
  let cards = [];
  try { cards = mine ? JSON.parse(device.files["companies.json"] || "{}").companies || [] : []; } catch { /* none */ }
  const seen = new Set((companies.companies || []).map((c) => c.ticker));
  state.companies = { ...companies, companies: [...(companies.companies || []), ...cards.filter((c) => !seen.has(c.ticker))] };
}

function fillCompanies() {
  $("company").innerHTML = state.index.companies.map((c) =>
    `<option value="${esc(keyOf(c))}">${esc(c.ticker)} · ${esc(c.name)}${c.device ? " (on this device)" : c.demo && !/synthetic/i.test(c.name) ? " (demo)" : ""}</option>`).join("");
}

/** After a run in this browser: list it and open it. */
export async function showDevice(ticker) {
  // the Demo doesn't list device runs, and the "no results" card replaced the pages: start over in real data
  if (state.demoMode && !ticker) return;                  // Clear from the Demo: nothing listed to update
  if (state.demoMode || state.emptied) {
    store.set("mode", "live");
    if (ticker) store.set("ticker", `device:${ticker}`);
    const url = new URL(location.href);
    url.searchParams.delete("demo");                    // ?demo=1 would switch straight back
    url.hash = "#valuation";
    location.replace(url.toString());
    if (url.toString().split("#")[0] === location.href.split("#")[0]) location.reload();
    return;
  }
  mergeDevice();
  fillCompanies();
  if (!ticker) {                        // a sector screen, or Clear: redraw the company in view, if it's still listed
    const still = state.company && state.index.companies.find((c) => keyOf(c) === keyOf(state.company));
    const next = still || state.index.companies[0];
    if (!next) { renderEmptyEverywhere(); return; }
    $("company").value = keyOf(next);
    await selectCompany(keyOf(next));
    return;
  }
  $("company").value = `device:${ticker}`;
  await selectCompany(`device:${ticker}`);
  route("valuation");
}

async function init() {
  await loadDevice();
  await chooseMode();
  setupTheme();
  setupTabs();
  setupSegments();
  setupCollapsibles();
  setupHereForm();
  try {
    [state.index, state.concepts, state.companies, state.taxonomy] = await Promise.all([getJSON(`${state.root}index.json`),
      getJSON(`${state.root}concepts.json`).catch(() => ({})), getJSON(`${state.root}companies.json`).catch(() => ({ companies: [] })),
      getJSON(`${state.root}taxonomy.json`).catch(() => null)]);
  } catch (e) {
    banner(`Couldn't load ${state.root}index.json (${e.message}). Run the pipeline, or "python scripts/export_site.py", then reload.`);
    state.index = { companies: [] };
  }
  published = { index: state.index, companies: state.companies || { companies: [] } };
  mergeDevice();
  for (const [k, f] of [["taxonomy", "taxonomy.json"], ["concepts", "concepts.json"]]) {   // no published data yet
    if ((!state[k] || !Object.keys(state[k]).length) && device.files[f]) try { state[k] = JSON.parse(device.files[f]); } catch { /* keep */ }
  }
  fillSectorList();
  $("footer-market").textContent = state.index.market_data === "real" ? "Market prices: Yahoo, checked against Alpha Vantage."
    : state.index.market_data === "demo" ? "Demo: synthetic companies and synthetic market data, run through the real pipeline."
      : "Market prices aren't published here (data terms); the Demo uses synthetic market figures.";
  $("generated").textContent = state.index.generated_at ? `Data index updated ${state.index.generated_at.replace("T", " ").replace("+00:00", " UTC")}.` : "";
  const sel = $("company");
  fillCompanies();
  sel.onchange = () => selectCompany(sel.value);
  $("asof").onchange = () => selectRun($("asof").value);
  if (!state.index.companies.length) {
    renderEmptyEverywhere();
    return;
  }
  const remembered = store.get(state.demoMode ? "ticker:demo" : "ticker");
  const first = state.index.companies.find((c) => keyOf(c) === remembered) || state.index.companies[0];
  sel.value = keyOf(first);
  await selectCompany(keyOf(first));
}

export async function selectCompany(key) {
  state.secLevel = state.peerLevel = undefined;   // each company starts at its default comparison level
  state.company = state.index.companies.find((c) => keyOf(c) === key);
  if (!state.company) { renderEmptyEverywhere(); return; }
  store.set(state.demoMode ? "ticker:demo" : "ticker", key);
  $("asof").innerHTML = state.company.runs.map((r) => `<option>${esc(r.as_of)}</option>`).join("");
  await selectRun(state.company.runs[0].as_of);
}

export async function selectRun(asOf) {
  state.run = state.company.runs.find((r) => r.as_of === asOf);
  $("asof").value = asOf;
  banner("");
  try {
    // one round trip: every file this run needs, fetched together
    const root = runRoot(), base = `${root}${state.company.ticker}/${state.run.as_of}/model_results`;
    const opt = (cond, path) => (cond ? getJSON(path).catch(() => null) : Promise.resolve(null));
    [state.detail, state.comparison, state.comps, state.dcf] = await Promise.all([
      getJSON(`${root}${state.run.detail}`),
      opt(state.run.comparison, `${root}${state.run.comparison}`),
      opt(state.run.models?.includes("comps"), `${base}/comps.json`),
      opt(state.run.models?.includes("dcf"), `${base}/dcf.json`),
      loadSector(),
    ]);
  } catch (e) {
    banner(`Couldn't load results for ${state.company.ticker} as of ${asOf}: ${e.message}`);
    return;
  }
  const demo = state.company.demo || state.detail.demo;
  $("demo-badge").hidden = !demo;
  if (demo && !state.demoMode) banner("This company is synthetic demo data, made up to preview the pages. Run the pipeline for a real ticker.");
  else if (state.detail.warnings?.length) banner(`Build warnings: ${state.detail.warnings.join("; ")}`);
  renderCompany();
  renderValuation();
  renderOverview();
  $("h-ticker").value = state.company.demo || state.company.device ? $("h-ticker").value : state.company.ticker;
}

function renderEmptyEverywhere() {
  state.emptied = true;
  state.detail = state.company = null;             // nothing left to draw into
  const msg = `<div class="card empty"><h2>No Published Results Yet</h2>
    <p>Use <b>Run ▸</b> to fetch a company, or press <b>Demo</b> at the top to explore every feature on synthetic companies.</p></div>`;
  for (const id of ["panel-company", "panel-valuation"]) $(id).innerHTML = msg;
  renderOverview();
}

// ---------------------------------------------------------------- tabs, theme

// Pages: Overview · Results · Method, plus the owner's Run page. Results holds two views,
// Valuation (default) and Company Detail. The hash names the page or view: #overview, #valuation,
// #company, #method, #run (#results opens the last view used).
const PAGES = { overview: "overview", results: "results", valuation: "results", company: "results", method: "method", run: "run" };

export function route(name) {
  if (!PAGES[name]) name = "overview";
  if (name === "results") name = store.get("rv") || "valuation";
  const page = PAGES[name];
  state.tab = page === "results" ? name : page;
  for (const t of document.querySelectorAll(".tab")) {
    const on = t.dataset.tab === page;
    t.setAttribute("aria-selected", on);
    t.tabIndex = on ? 0 : -1;
  }
  for (const id of ["overview", "results", "method", "run"]) $(`panel-${id}`).hidden = id !== page;
  $("run-link").classList.toggle("active", page === "run");
  if (page === "results") {
    store.set("rv", name);
    $("panel-valuation").hidden = name !== "valuation";
    $("panel-company").hidden = name !== "company";
    for (const b of $("results-view").querySelectorAll("button")) b.setAttribute("aria-pressed", b.dataset.rv === name);
  }
  if (location.hash !== `#${name}`) history.replaceState(null, "", `#${name}`);
  // charts measure their container, so draw after the panel is visible
  if (name === "overview") renderOverview();
  if (name === "method") renderMethod();
  if (name === "company" && state.detail) renderCompany();
  if (name === "valuation" && state.detail) renderValuation();
}

export function setupTabs() {
  const tabs = [...document.querySelectorAll(".tab")];
  tabs.forEach((t, i) => {
    t.onclick = () => route(t.dataset.tab);
    t.onkeydown = (e) => {
      const d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
      if (d) { const n = tabs[(i + d + tabs.length) % tabs.length]; n.focus(); route(n.dataset.tab); }
    };
  });
  $("results-view").onclick = (e) => { const b = e.target.closest("button"); if (b) route(b.dataset.rv); };
  document.addEventListener("click", (e) => {     // in-page links such as "See results" and "How it works"
    const a = e.target.closest('a[href^="#"]');
    if (a && PAGES[a.getAttribute("href").slice(1)]) { e.preventDefault(); route(a.getAttribute("href").slice(1)); window.scrollTo(0, 0); }
  });
  const fromHash = () => route(location.hash.slice(1));
  window.addEventListener("hashchange", fromHash);
  fromHash();
}

function setupTheme() {
  const btn = $("theme");
  const apply = (t) => {
    if (t === "light" || t === "dark") document.documentElement.dataset.theme = t;
    else delete document.documentElement.dataset.theme;
    btn.textContent = `Theme: ${t || "auto"}`;
  };
  apply(store.get("theme"));
  btn.onclick = () => {
    const order = [null, "light", "dark"];
    const next = order[(order.indexOf(store.get("theme")) + 1) % 3];
    store.set("theme", next);
    apply(next);
    if (state.detail) { renderCompany(); renderValuation(); renderOverview(); }
  };
}

// Collapsible sections: the heading toggles the body. First visit: Statements open, Ratios and
// Sector closed; after that each viewer's choice is remembered in this browser.
const COLLAPSE_DEFAULT = { statements: true, ratios: false, sector: false };

function setupCollapsibles() {
  document.querySelectorAll(".card[data-collapse]").forEach((card) => {
    const key = card.dataset.collapse, h = card.querySelector(".card-head h2"), body = card.querySelector(".card-body");
    const id = `sec-body-${key}`;
    body.id = id;
    h.innerHTML = `<button type="button" class="collapse-btn" aria-controls="${id}"><span class="chev" aria-hidden="true"></span>${esc(h.textContent)}</button>`;
    const btn = h.firstChild;
    const set = (open, save) => {
      card.classList.toggle("collapsed", !open);
      btn.setAttribute("aria-expanded", String(open));
      body.hidden = !open;
      if (save) store.set(`open:${key}`, open ? "1" : "0");
    };
    const saved = store.get(`open:${key}`);
    set(saved === null ? COLLAPSE_DEFAULT[key] ?? true : saved === "1", false);
    btn.onclick = () => set(card.classList.contains("collapsed"), true);
  });
}

function setupSegments() {
  const wire = (id, key, attr, render) => {
    const seg = $(id);
    seg.onclick = (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      state[key] = b.dataset[attr];
      for (const x of seg.querySelectorAll("button")) x.setAttribute("aria-pressed", x === b);
      render();
    };
  };
  wire("view-seg", "view", "view", () => { renderStatements(); renderRevenueChart(); renderReturnsChart(); renderMarginChart(); renderCashChart(); });
  wire("ratio-seg", "fw", "fw", renderRatios);
  wire("stmt-seg", "stmt", "stmt", renderStatements);
  // $K / $M / $B for every table, remembered in this browser
  const u = store.get("units");
  if (["K", "M", "B"].includes(u)) {
    state.units = u;
    for (const x of $("units-seg").querySelectorAll("button")) x.setAttribute("aria-pressed", x.dataset.units === u);
  }
  wire("units-seg", "units", "units", () => { store.set("units", state.units); if (state.detail) { renderCompany(); renderValuation(); } });
}

init();
