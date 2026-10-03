import { renderCashChart, renderCompany, renderMarginChart, renderRatios, renderReturnsChart, renderRevenueChart, renderStatements } from "./company.js";
import { esc } from "./format.js";
import { fillSectorList, setupRunForm } from "./run.js";
import { loadSector } from "./sector.js";
import { $, banner, getJSON, state, store } from "./state.js";
import { renderValuation } from "./valuation.js";

async function init() {
  setupTheme();
  setupTabs();
  setupSegments();
  setupCollapsibles();
  setupRunForm();
  try {
    [state.index, state.concepts, state.companies, state.taxonomy] = await Promise.all([getJSON("data/index.json"),
      getJSON("data/concepts.json").catch(() => ({})), getJSON("data/companies.json").catch(() => ({ companies: [] })),
      getJSON("data/taxonomy.json").catch(() => null)]);
  } catch (e) {
    banner(`Couldn't load data/index.json (${e.message}). Run the pipeline, or "python -m L3_app.publish", then reload.`);
    state.index = { companies: [] };
  }
  fillSectorList();
  $("footer-market").textContent = state.index.market_data === "real" ? "Market prices: Yahoo, checked against Alpha Vantage."
    : "Market prices aren't published here; the example companies use synthetic market figures.";
  $("generated").textContent = state.index.generated_at ? `Data index updated ${state.index.generated_at.replace("T", " ").replace("+00:00", " UTC")}.` : "";
  const sel = $("company");
  sel.innerHTML = state.index.companies.map((c) =>
    `<option value="${esc(c.ticker)}">${esc(c.ticker)} · ${esc(c.name)}${c.demo && !/synthetic/i.test(c.name) ? " (demo)" : ""}</option>`).join("");
  sel.onchange = () => selectCompany(sel.value);
  $("asof").onchange = () => selectRun($("asof").value);
  if (!state.index.companies.length) {
    renderEmptyEverywhere();
    return;
  }
  const remembered = store.get("ticker");
  const first = state.index.companies.find((c) => c.ticker === remembered) || state.index.companies[0];
  sel.value = first.ticker;
  await selectCompany(first.ticker);
}

export async function selectCompany(ticker) {
  state.secLevel = state.peerLevel = undefined;   // each company starts at its default comparison level
  state.company = state.index.companies.find((c) => c.ticker === ticker);
  store.set("ticker", ticker);
  $("asof").innerHTML = state.company.runs.map((r) => `<option>${esc(r.as_of)}</option>`).join("");
  await selectRun(state.company.runs[0].as_of);
}

export async function selectRun(asOf) {
  state.run = state.company.runs.find((r) => r.as_of === asOf);
  $("asof").value = asOf;
  banner("");
  try {
    // one round trip: every file this run needs, fetched together
    const base = `data/${state.company.ticker}/${state.run.as_of}/model_results`;
    const opt = (cond, path) => (cond ? getJSON(path).catch(() => null) : Promise.resolve(null));
    [state.detail, state.comparison, state.comps, state.dcf] = await Promise.all([
      getJSON(`data/${state.run.detail}`),
      opt(state.run.comparison, `data/${state.run.comparison}`),
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
  if (demo) banner("This company is synthetic demo data, made up to preview the pages. Run the pipeline for a real ticker.");
  else if (state.detail.warnings?.length) banner(`Build warnings: ${state.detail.warnings.join("; ")}`);
  renderCompany();
  renderValuation();
  $("r-ticker").value = state.company.demo ? "" : state.company.ticker;
}

function renderEmptyEverywhere() {
  const msg = `<div class="card empty"><h2>No Published Results Yet</h2>
    <p>Use <b>Run Pipeline</b> to fetch a company, or run <code>python -m L3_app.demo</code> for a synthetic preview.</p></div>`;
  for (const id of ["panel-company", "panel-valuation"]) $(id).innerHTML = msg;
}

// ---------------------------------------------------------------- tabs, theme

export function setupTabs() {
  const tabs = [...document.querySelectorAll(".tab")];
  const show = (name) => {
    state.tab = name;
    for (const t of tabs) {
      const on = t.dataset.tab === name;
      t.setAttribute("aria-selected", on);
      t.tabIndex = on ? 0 : -1;
      $(`panel-${t.dataset.tab}`).hidden = !on;
    }
    if (location.hash !== `#${name}`) history.replaceState(null, "", `#${name}`);
    // charts measure their container, so draw after the panel is visible
    if (name === "company" && state.detail) renderCompany();
    if (name === "valuation" && state.detail) renderValuation();
  };
  tabs.forEach((t, i) => {
    t.onclick = () => show(t.dataset.tab);
    t.onkeydown = (e) => {
      const d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
      if (d) { const n = tabs[(i + d + tabs.length) % tabs.length]; n.focus(); show(n.dataset.tab); }
    };
  });
  const fromHash = () => {
    const h = location.hash.slice(1);
    show(tabs.some((t) => t.dataset.tab === h) ? h : "company");
  };
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
    if (state.detail) { renderCompany(); renderValuation(); }
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
}

init();
