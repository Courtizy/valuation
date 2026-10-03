// Valuation site: reads the JSON the pipeline publishes to data/ and renders it.
// No valuation math runs here: projections are calculated in Python (L1 trend
// case, or the DCF's projection) and only displayed.

import { columnChart, lineChart, rangeChart } from "./charts.js";

const $ = (id) => document.getElementById(id);
const state = { index: null, concepts: {}, company: null, run: null, detail: null, comparison: null, scn: "p50", companies: null,
                view: "annual", fw: "reformulated", tab: "company" };

// ---------------------------------------------------------------- storage

const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { v === null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch { /* ignore */ } },
};

// ---------------------------------------------------------------- formats

const fin = (v) => typeof v === "number" && Number.isFinite(v);
const NA = "–";
function money(v, axis = false) {
  if (!fin(v)) return NA;
  const a = Math.abs(v), s = v < 0 ? "−" : "";
  if (a >= 1e12) return `${s}$${(a / 1e12).toFixed(axis ? 1 : 2)}T`;
  if (a >= 1e9) return `${s}$${(a / 1e9).toFixed(axis ? 1 : 2)}B`;
  if (a >= 1e6) return `${s}$${(a / 1e6).toFixed(axis ? 0 : 1)}M`;
  if (a >= 1e3) return `${s}$${(a / 1e3).toFixed(0)}K`;
  return `${s}$${a.toFixed(0)}`;
}
const millions = (v) => (fin(v) ? (Math.abs(v) < 5e4 ? 0 : v / 1e6).toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 }).replace("-", "−") : NA);
const pct = (v, axis = false) => (fin(v) ? `${(v * 100).toFixed(axis ? 0 : 1)}%`.replace("-", "−") : NA);
const times = (v) => (fin(v) ? `${v.toFixed(2)}x`.replace("-", "−") : NA);
const days = (v) => (fin(v) ? `${v.toFixed(1)} d` : NA);
const num = (v) => (fin(v) ? v.toFixed(2).replace("-", "−") : NA);
const price = (v, axis = false) => (fin(v) ? `$${v.toFixed(axis ? 0 : 2)}` : NA);
const shortLabel = (p) => (p.fiscal_period === "FY" ? `FY${String(p.fiscal_year).slice(-2)}`
  : p.label.startsWith("TTM") ? p.end.slice(0, 7) : `${p.fiscal_period} FY${String(p.fiscal_year).slice(-2)}`);

function esc(s) { return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]); }
// ---- financial-table formatting ----------------------------------------------
// Statement look: indented components, costs as deductions in parentheses,
// shaded bands on subtotals and totals. Positives reserve the ")" width so digits line up.
function acct(v, { digits = 1, scale = 1e6 } = {}) {
  if (!fin(v)) return NA;
  const x = scale === 1e6 && Math.abs(v) < 5e4 ? 0 : v / scale;
  const body = Math.abs(x).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  const neg = x < 0 && body !== (0).toFixed(digits);
  return `<span class="${neg ? "an" : "ap"}">${neg ? `(${body})` : body}</span>`;
}
// One row of a financial table. kind: item | head | sub (shaded band) | grand (stronger accent band)
// | key (bold, no band) | memo (muted italic). cells: [{html, cls}]
function finRow(lbl, cells, { kind = "item", indent = 0, title = "" } = {}) {
  const cls = [kind !== "item" ? kind : "", indent ? `i${indent}` : ""].filter(Boolean).join(" ");
  return `<tr${cls ? ` class="${cls}"` : ""}><td${title ? ` title="${esc(title)}"` : ""}>${lbl}</td>${cells.map((c) =>
    `<td${c.cls ? ` class="${c.cls}"` : ""}>${c.html}</td>`).join("")}</tr>`;
}
const cellOf = (html, extra = "") => ({ html, cls: [html === NA ? "na" : "", extra].filter(Boolean).join(" ") });

function label(id) { return state.concepts[id]?.name || id.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase()); }

// ---------------------------------------------------------------- data

async function getJSON(path) {
  const r = await fetch(path, { cache: "no-cache" });
  if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
  return r.json();
}

function banner(msg) {
  const b = $("banner");
  b.hidden = !msg;
  b.textContent = msg || "";
}

async function init() {
  setupTheme();
  setupTabs();
  setupSegments();
  setupRunForm();
  try {
    [state.index, state.concepts] = await Promise.all([getJSON("data/index.json"), getJSON("data/concepts.json").catch(() => ({}))]);
  } catch (e) {
    banner(`Couldn't load data/index.json (${e.message}). Run the pipeline, or "python -m L3_app.publish", then reload.`);
    state.index = { companies: [] };
  }
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

async function selectCompany(ticker) {
  state.company = state.index.companies.find((c) => c.ticker === ticker);
  store.set("ticker", ticker);
  $("asof").innerHTML = state.company.runs.map((r) => `<option>${esc(r.as_of)}</option>`).join("");
  await selectRun(state.company.runs[0].as_of);
}

async function selectRun(asOf) {
  state.run = state.company.runs.find((r) => r.as_of === asOf);
  $("asof").value = asOf;
  banner("");
  try {
    state.detail = await getJSON(`data/${state.run.detail}`);
    state.comparison = state.run.comparison ? await getJSON(`data/${state.run.comparison}`) : null;
    state.comps = state.run.models?.includes("comps")
      ? await getJSON(`data/${state.company.ticker}/${state.run.as_of}/model_results/comps.json`).catch(() => null) : null;
    state.dcf = state.run.models?.includes("dcf")
      ? await getJSON(`data/${state.company.ticker}/${state.run.as_of}/model_results/dcf.json`).catch(() => null) : null;
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
  const msg = `<div class="card empty"><h2>No published results yet</h2>
    <p>Use <b>Run pipeline</b> to fetch a company, or run <code>python -m L3_app.demo</code> for a synthetic preview.</p></div>`;
  for (const id of ["panel-company", "panel-valuation"]) $(id).innerHTML = msg;
}

// ---------------------------------------------------------------- tabs, theme

function setupTabs() {
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
  wire("view-seg", "view", "view", () => { renderStatements(); renderRevenueChart(); });
  wire("ratio-seg", "fw", "fw", renderRatios);
}

// ---------------------------------------------------------------- company

// Statement layout. sign -1 = shown as a deduction (reported as a positive cost).
// A "head" row is dropped when none of the rows under it has data.
const STATEMENTS = [
  ["Income statement", [
    { id: "revenue", label: "Revenue", kind: "key" },
    { id: "cost_of_goods_and_services_sold", label: "Cost of revenue", indent: 1, sign: -1 },
    { id: "gross_profit", label: "Gross profit", kind: "sub" },
    { head: "Operating expenses", indent: 1 },
    { id: "research_and_development_expenses", label: "Research and development", indent: 2, sign: -1 },
    { id: "selling_general_and_admin_expenses", label: "Selling, general and administrative", indent: 2, sign: -1 },
    { id: "operating_income_loss", label: "Operating income", kind: "sub" },
    { id: "interest_expense", label: "Interest expense", indent: 1, sign: -1 },
    { id: "interest_income", label: "Interest income", indent: 1 },
    { id: "pretax_income_loss", label: "Income before taxes", kind: "sub" },
    { id: "income_taxes", label: "Income tax expense", indent: 1, sign: -1 },
    { id: "net_income", label: "Net income", kind: "grand" },
    { head: "Memo", indent: 0 },
    { id: "depreciation_amortization_cf", label: "Depreciation and amortization", indent: 1, kind: "memo" },
    { id: "ebitda", label: "EBITDA", indent: 1, kind: "memo" },
  ]],
  ["Balance sheet", [
    { head: "Assets", indent: 0 },
    { id: "cash_and_marketable_securities", label: "Cash and marketable securities", indent: 1 },
    { id: "trade_receivables", label: "Accounts receivable", indent: 1 },
    { id: "inventories", label: "Inventories", indent: 1 },
    { id: "current_assets_total", label: "Total current assets", indent: 1, kind: "sub" },
    { id: "plant_property_equipment_net", label: "Property, plant and equipment, net", indent: 1 },
    { id: "goodwill", label: "Goodwill", indent: 1 },
    { id: "assets", label: "Total assets", kind: "grand" },
    { head: "Liabilities and equity", indent: 0 },
    { id: "trade_payables", label: "Accounts payable", indent: 1 },
    { id: "short_term_debt", label: "Short-term debt", indent: 1 },
    { id: "current_liabilities_total", label: "Total current liabilities", indent: 1, kind: "sub" },
    { id: "long_term_debt", label: "Long-term debt", indent: 1 },
    { id: "liabilities", label: "Total liabilities", kind: "sub" },
    { id: "all_equity_balance", label: "Total equity", indent: 1 },
    { id: "liabilities_and_equity", label: "Total liabilities and equity", kind: "grand" },
    { head: "Memo", indent: 0 },
    { id: "total_debt", label: "Total debt", indent: 1, kind: "memo" },
    { id: "net_debt", label: "Net debt", indent: 1, kind: "memo" },
  ]],
  ["Cash flow", [
    { id: "operating_cash_flow", label: "Net cash from operating activities", kind: "key" },
    { id: "capital_expenses", label: "Capital expenditures", indent: 1, sign: -1 },
    { id: "free_cash_flow", label: "Free cash flow (CFO − capex)", kind: "sub" },
    { head: "Returned to shareholders", indent: 1 },
    { id: "stock_repurchased", label: "Share repurchases", indent: 2, sign: -1 },
    { id: "common_dividends_paid", label: "Dividends paid", indent: 2, sign: -1 },
  ]],
  ["Per share", [
    { id: "eps_diluted", label: "Diluted EPS ($)", digits: 2, scale: 1 },
    { id: "shares_fully_diluted_average", label: "Diluted shares (M)", indent: 0 },
  ]],
];
const DERIVED_METHODS = new Set(["q4_derived", "ytd_derived", "summed_4q_with_derived"]);

function periodsFor(view) {
  const all = state.detail.views[view] || [];
  return all.slice(-(view === "annual" ? 6 : 8));
}

function renderCompany() {
  if (!state.detail || state.tab !== "company") return;
  renderTiles();
  renderRevenueChart();
  renderReturnsChart();
  renderStatements();
  renderRatios();
}

function latestAnalysis() {
  const a = state.detail.analysis;
  return (a.ttm.length ? a.ttm : a.annual).at(-1);
}

function renderTiles() {
  const v = state.detail.views;
  const series = v.ttm.length ? v.ttm : v.annual;
  const cur = series.at(-1), prior = series.find((p) => Math.abs(new Date(cur.end) - new Date(p.end) - 365 * 864e5) < 20 * 864e5);
  const an = latestAnalysis();
  const val = cur?.values || {};
  const growth = prior && fin(prior.values.revenue) ? val.revenue / prior.values.revenue - 1 : null;
  const opm = fin(val.operating_income_loss) && val.revenue ? val.operating_income_loss / val.revenue : null;
  const rnoa = an?.ratios.reformulated.avg?.rnoa;
  const tiles = [
    { label: `Revenue · ${cur ? (cur.label.startsWith("TTM") ? "TTM" : cur.label) : ""}`, value: money(val.revenue),
      delta: fin(growth) ? `${growth >= 0 ? "▲" : "▼"} ${pct(Math.abs(growth))} vs a year earlier` : "", dir: growth },
    { label: "Operating margin", value: pct(opm) },
    { label: "RNOA (average NOA)", value: pct(rnoa) },
    { label: "Free cash flow (CFO − capex)", value: money(val.free_cash_flow) },
    { label: "Net debt", value: money(val.net_debt) },
  ];
  const proj = projection();
  if (proj && fin(val.revenue) && val.revenue > 0) {
    const last = proj.rows.at(-1).revenue, n = proj.rows.length;
    const cagr = (last / val.revenue) ** (1 / n) - 1;
    tiles.splice(1, 0, { label: `Projected revenue growth · ${n} yrs`, value: pct(cagr),
      delta: `${proj.kind === "dcf" ? "DCF case" : "trend case"} · ${money(last)} in year ${n}`, dir: 0, neutral: true });
  }
  $("tiles").innerHTML = tiles.map((t) => `<div class="tile"><div class="label">${esc(t.label)}</div>
    <div class="value">${t.value}</div>${t.delta ? `<div class="delta ${t.neutral ? "" : t.dir >= 0 ? "up" : "down"}">${t.delta}</div>` : ""}</div>`).join("");
}

function renderRevenueChart() {
  const view = state.view;
  const ps = (state.detail.views[view] || []).slice(view === "annual" ? -7 : -12);
  const proj = view === "annual" ? projection() : null;
  const est = proj ? proj.rows : [];
  $("rev-title").textContent = view === "ttm" ? "Revenue, trailing twelve months" : view === "quarterly" ? "Revenue by quarter" : "Revenue: reported and projected";
  $("rev-sub").textContent = ps.length ? `${ps[0].label} to ${est.length ? estLabel(proj.baseEnd, est.length) : ps.at(-1).label}${est.length ? ` · lighter bars = ${proj.kind === "dcf" ? "DCF case" : "trend case"}` : ""}` : "";
  columnChart($("rev-chart"), {
    categories: ps.map(shortLabel).concat(est.map((_, i) => estLabel(proj.baseEnd, i + 1))),
    values: ps.map((p) => p.values.revenue).concat(est.map((r) => r.revenue)),
    estimate: ps.map(() => false).concat(est.map(() => true)),
    format: money, label: "Revenue" });
}

function renderReturnsChart() {
  const an = state.detail.analysis.annual.filter((a) => a.ratios.reformulated.avg);
  const series = [
    { name: "RNOA", color: "var(--series-1)", values: an.map((a) => a.ratios.reformulated.avg.rnoa) },
    { name: "ROCE", color: "var(--series-2)", values: an.map((a) => a.ratios.reformulated.avg.roce) },
  ];
  $("ret-legend").innerHTML = series.map((s) => `<span><span class="key" style="background:${s.color}"></span>${s.name}</span>`).join("");
  lineChart($("ret-chart"), { categories: an.map((a) => `FY${a.label.slice(-2)}`), series, format: pct, label: "RNOA and ROCE" });
}

// Projected years: the DCF's projection when a DCF has run (the numbers behind
// the valuation), otherwise the trend case calculated in L1 from history.
const PROJ_MAP = { revenue: "revenue", cost_of_goods_and_services_sold: "cogs", gross_profit: "gross_profit",
  research_and_development_expenses: "rnd", selling_general_and_admin_expenses: "sga", operating_income_loss: "ebit",
  depreciation_amortization_cf: "depreciation", ebitda: "ebitda", pretax_income_loss: "ebt", income_taxes: "income_taxes",
  net_income: "net_income", capital_expenses: "capex" };

function projection() {
  const d = state.dcf?.details;
  if (d?.statements?.length) {
    return { kind: "dcf", rows: d.statements.slice(0, 5), baseEnd: d.base_period.end,
      note: `Estimates: DCF case (assumptions/${state.company.ticker}/dcf.json), first 5 of ${d.statements.length} projected years.` };
  }
  const p = state.detail.projection;
  if (!p?.years?.length) return null;
  const a = p.assumptions;
  return { kind: "trend", rows: p.years, baseEnd: p.base_period.end,
    note: `Estimates: trend case from the filings, no inputs. Revenue growth starts at the ${pct(a.revenue_growth_start)} historical CAGR and fades to ${pct(a.terminal_growth)}; costs, D&A and capex stay at base-period ratios; working capital ${pct(a.nwc_to_sales_change)} of new sales; tax ${pct(a.tax_rate)}. Run a DCF to replace it with your own case.` };
}

function estLabel(baseEnd, t) {
  const d = new Date(baseEnd + "T00:00:00Z");
  d.setUTCFullYear(d.getUTCFullYear() + t);
  return `${d.toLocaleString("en-US", { month: "short", timeZone: "UTC" })} ${String(d.getUTCFullYear()).slice(-2)}E`;
}

function priorFor(p, view) {
  const lag = view === "quarterly" || view === "ttm" ? 4 : 1;
  const all = state.detail.views[view];
  const idx = all.indexOf(p);
  return idx - lag >= 0 ? all[idx - lag].values : null;
}

const GROWTH_ROWS = [
  ["Revenue growth", (v, prev) => (prev?.revenue && fin(v.revenue) ? v.revenue / prev.revenue - 1 : null)],
  ["Gross margin", (v) => (v.revenue && fin(v.gross_profit) ? v.gross_profit / v.revenue : null)],
  ["EBITDA margin", (v) => (v.revenue && fin(v.ebitda) ? v.ebitda / v.revenue : null)],
  ["Operating margin", (v) => (v.revenue && fin(v.operating_income_loss) ? v.operating_income_loss / v.revenue : null)],
  ["Net margin", (v) => (v.revenue && fin(v.net_income) ? v.net_income / v.revenue : null)],
];

function renderStatements() {
  const view = state.view, ps = periodsFor(view);
  const t = $("stmt-table");
  if (!ps.length) { t.innerHTML = `<tbody><tr><td class="muted">No ${view} periods.</td></tr></tbody>`; return; }
  const proj = view === "annual" ? projection() : null;
  // the projection starts from the latest TTM; show it as the bridge column when it's newer than the last fiscal year
  const ttmBase = proj && state.detail.views.ttm.at(-1);
  const cols = ps.map((p) => ({ p, view })).concat(ttmBase && ttmBase.end > ps.at(-1).end ? [{ p: ttmBase, view: "ttm" }] : []);
  // projected rows in concept terms, so one renderer serves both
  const est = proj ? proj.rows.map((r) => Object.fromEntries(Object.entries(PROJ_MAP).map(([cid, k]) => [cid, r[k]]))) : [];
  const n = cols.length + est.length;
  let html = `<thead><tr><th scope="col">$ millions</th>${cols.map(({ p, view: vw }) => `<th scope="col" title="${esc(p.start)} to ${esc(p.end)}${vw !== view ? " · trailing twelve months, the projection's base" : ""}">${esc(vw !== view ? `TTM ${shortLabel(p)}` : shortLabel(p))}</th>`).join("")}
    ${est.map((_, i) => `<th scope="col" class="est" title="projected year ${i + 1}">${estLabel(proj.baseEnd, i + 1)}</th>`).join("")}</tr></thead><tbody>`;

  const section = (name) => `<tr class="group"><td colspan="${n + 1}">${esc(name)}</td></tr>`;
  html += section("Growth and margins");
  for (const [name, f] of GROWTH_ROWS) {
    const cells = cols.map(({ p, view: vw }) => cellOf(pct(f(p.values, priorFor(p, vw)))))
      .concat(est.map((e, i) => cellOf(pct(f(e, i ? est[i - 1] : cols.at(-1).p.values)), "est")));
    html += finRow(name, cells, { indent: 1, kind: name === "Revenue growth" ? "key" : "item" });
  }
  for (const [group, spec] of STATEMENTS) {
    const has = (r) => r.id && (cols.some(({ p }) => fin(p.values[r.id])) || est.some((e) => fin(e[r.id])));
    // keep heads only when a deeper row with data follows before the next row at the head's level
    const rows = spec.filter((r, i) => {
      if (!r.head) return has(r);
      for (const nx of spec.slice(i + 1)) { if (nx.head || (nx.indent || 0) <= r.indent) break; if (has(nx)) return true; }
      return false;
    });
    if (!rows.some((r) => r.id)) continue;
    html += section(group);
    for (const r of rows) {
      if (r.head) { html += finRow(esc(r.head), cols.concat(est).map(() => ({ html: "" })), { kind: "head", indent: r.indent }); continue; }
      const sg = r.sign || 1, o = { digits: r.digits ?? 1, scale: r.scale ?? 1e6 };
      const cells = cols.map(({ p }) => {
        const v = p.values[r.id], m = p.methods[r.id];
        const mark = DERIVED_METHODS.has(m) ? `<span class="mark" title="${esc(m.replace(/_/g, " "))}">d</span>` : "";
        return fin(v) ? { html: acct(sg * v, o) + mark } : cellOf(NA);
      }).concat(est.map((e) => (fin(e[r.id]) ? { html: acct(sg * e[r.id], o), cls: "est" } : cellOf(NA, "est"))));
      html += finRow(esc(r.label || label(r.id)), cells, { kind: r.kind, indent: r.indent, title: label(r.id) });
    }
    if (group === "Cash flow" && est.length) {
      html += finRow("Unlevered free cash flow (projected)", cols.map(() => cellOf(NA)).concat(
        proj.rows.map((x) => ({ html: acct(x.fcf), cls: "est" }))), { kind: "memo", indent: 1 });
    }
  }
  t.innerHTML = html + "</tbody>";
  $("stmt-note").textContent = proj ? proj.note : view === "annual" ? "" : "Estimates are shown in the Annual view.";
}

const $M = (v, o) => acct(v, o);   // $ millions, accounting style

const RATIO_ROWS = {
  reformulated: {
    note: "Operating vs financial split. NOPAT = net income + after-tax net interest. ROCE = RNOA + FLEV × (RNOA − NBC).",
    rows: [
      ["group", "Margins"],
      ["Operating margin (NOPM)", (a) => a.ratios.reformulated.nopm, pct, { kind: "key" }],
      ["Core NOPM", (a) => a.ratios.reformulated.core_nopm, pct],
      ["group", "Average balances"],
      ["NOA turnover (NOAT)", (a) => a.ratios.reformulated.avg?.noat, times],
      ["RNOA", (a) => a.ratios.reformulated.avg?.rnoa, pct, { kind: "key" }],
      ["ROCE", (a) => a.ratios.reformulated.avg?.roce, pct, { kind: "key" }],
      ["FLEV", (a) => a.ratios.reformulated.avg?.flev, num],
      ["NBC", (a) => a.ratios.reformulated.avg?.nbc, pct],
      ["Spread (RNOA − NBC)", (a) => a.ratios.reformulated.avg?.spread, pct],
      ["OLLEV", (a) => a.ratios.reformulated.avg?.ollev, num],
      ["ROOA", (a) => a.ratios.reformulated.avg?.rooa, pct],
      ["OLSPREAD", (a) => a.ratios.reformulated.avg?.olspread, pct],
      ["group", "Beginning balances"],
      ["NOAT", (a) => a.ratios.reformulated.beg?.noat, times],
      ["RNOA", (a) => a.ratios.reformulated.beg?.rnoa, pct],
      ["ROCE", (a) => a.ratios.reformulated.beg?.roce, pct],
      ["FLEV", (a) => a.ratios.reformulated.beg?.flev, num],
      ["group", "Balance sheet ($M)"],
      ["Net operating assets", (a) => a.reformulated_balance_sheet.noa, $M, {}],
      ["Net nonoperating obligations", (a) => a.reformulated_balance_sheet.nno, $M, { sign: -1 }],
      ["Common equity incl. NCI", (a) => a.reformulated_balance_sheet.cse_incl_nci, $M, { kind: "grand", indent: 0 }],
      ["group", "Free cash flow ($M)"],
      ["NOPAT", (a) => a.reformulated_income_statement.nopat, $M, {}],
      ["FCF = NOPAT − ΔNOA", (a) => a.ratios.reformulated.fcf, $M, { kind: "key" }],
    ],
  },
  managerial: {
    note: "Managerial balance sheet: cash + working-capital requirement + fixed assets = capital employed.",
    rows: [
      ["group", "Managerial balance sheet ($M)"],
      ["Cash", (a) => a.managerial_balance_sheet.cash, $M, {}],
      ["Working-capital requirement", (a) => a.managerial_balance_sheet.wcr, $M],
      ["Fixed assets", (a) => a.managerial_balance_sheet.fixed_assets, $M],
      ["Invested capital", (a) => a.managerial_balance_sheet.invested_capital, $M, { kind: "grand", indent: 0 }],
      ["group", "Liquidity and operating cycle"],
      ["Net long-term financing (NLF)", (a) => a.ratios.managerial.nlf, $M],
      ["Net short-term financing (NSF)", (a) => a.ratios.managerial.nsf, $M],
      ["Liquidity ratio (NLF / WCR)", (a) => a.ratios.managerial.liquidity_ratio, num],
      ["WCR / sales", (a) => a.ratios.managerial.wcr_to_sales, pct],
      ["Collection period", (a) => a.ratios.managerial.collection_period_days, days],
      ["Days inventory", (a) => a.ratios.managerial.days_inventory, days],
      ["Inventory turnover", (a) => a.ratios.managerial.inventory_turnover, times],
      ["Payment period", (a) => a.ratios.managerial.payment_period_days, days],
      ["Current ratio", (a) => a.ratios.managerial.current_ratio, num],
      ["Acid test", (a) => a.ratios.managerial.acid_test, num],
      ["group", "Free cash flow ($M)"],
      ["NOPLAT", (a) => a.fcf_managerial.noplat, $M, {}],
      ["Plus: depreciation", (a) => a.fcf_managerial.depreciation, $M],
      ["Less: capex (ΔFA + depreciation)", (a) => a.fcf_managerial.capex_from_balance_sheet, $M, { sign: -1 }],
      ["Less: increase in WCR", (a) => a.fcf_managerial.change_in_wcr, $M, { sign: -1 }],
      ["Free cash flow", (a) => a.fcf_managerial.fcf, $M, { kind: "grand", indent: 0 }],
    ],
  },
  traditional: {
    note: "Profit margin adds back after-tax interest expense. ROA = margin × turnover.",
    rows: [
      ["group", "Return on assets"],
      ["Profit margin", (a) => a.ratios.traditional.profit_margin, pct],
      ["× Asset turnover", (a) => a.ratios.traditional.asset_turnover, times],
      ["ROA", (a) => a.ratios.traditional.roa, pct, { kind: "sub", indent: 0 }],
      ["group", "Return on equity"],
      ["Leverage (assets / equity)", (a) => a.ratios.traditional.leverage, times],
      ["ROE", (a) => a.ratios.traditional.roe, pct, { kind: "key", indent: 0 }],
    ],
  },
  risk: {
    note: "Altman Z public needs a market price (not published on this site); the private-firm form uses book equity. Zones: Z < 1.2 distress, < 2.9 grey.",
    rows: [
      ["group", "Distress"],
      ["Altman Z (private form)", (a) => a.ratios.risk.altman_z.private, num, { kind: "key" }],
      ["Zone", (a) => a.ratios.risk.altman_z.private_zone, (z) => z || NA],
      ["Altman Z (public form)", (a) => a.ratios.risk.altman_z.public, num],
      ["group", "Credit metrics"],
      ["EBIT / interest", (a) => a.ratios.risk.credit.ebit_to_interest, times],
      ["Debt / EBITDA", (a) => a.ratios.risk.credit.debt_to_ebitda, times],
      ["FFO / debt", (a) => a.ratios.risk.credit.ffo_to_debt, pct],
      ["Return on capital", (a) => a.ratios.risk.credit.return_on_capital, pct],
      ["EBIT margin", (a) => a.ratios.risk.credit.ebit_margin, pct],
      ["Debt / book capital", (a) => a.ratios.risk.credit.debt_to_book_capital, pct],
      ["Capex / depreciation", (a) => a.ratios.risk.credit.capex_to_depreciation, times],
    ],
  },
  signals: {
    note: "Positive signals favor future earnings; negative ones flag possible quality issues. Year-over-year.",
    rows: [
      ["group", "Earnings signals"],
      ["Gross margin signal", (a) => a.ratios.signals.gross_margin_signal, pct],
      ["SG&A signal", (a) => a.ratios.signals.sga_signal, pct],
      ["R&D signal", (a) => a.ratios.signals.rnd_signal, pct],
      ["Receivables signal", (a) => a.ratios.signals.receivables_signal, pct],
      ["Inventory signal", (a) => a.ratios.signals.inventory_signal, pct],
      ["group", "Diagnostics"],
      ["CFO / operating income", (a) => a.ratios.signals.cfo_to_operating_income, num],
      ["CFO / average NOA", (a) => a.ratios.signals.cfo_to_avg_noa, pct],
      ["Accruals / Δsales", (a) => a.ratios.signals.accruals_to_sales_change, num],
      ["Sales / receivables", (a) => a.ratios.signals.sales_to_receivables, times],
      ["Depreciation / capex", (a) => a.ratios.signals.depreciation_to_capex, num],
    ],
  },
};

function renderRatios() {
  const an = state.detail.analysis;
  const cols = [...an.annual.slice(-5)];
  if (an.ttm.length && an.ttm.at(-1).end > (cols.at(-1)?.end || "")) cols.push(an.ttm.at(-1));
  const spec = RATIO_ROWS[state.fw];
  const head = cols.map((a) => `<th scope="col">${esc(a.label.startsWith("TTM") ? `TTM ${a.end.slice(0, 7)}` : a.label)}</th>`).join("");
  let html = `<thead><tr><th scope="col">${esc(state.fw[0].toUpperCase() + state.fw.slice(1))}</th>${head}</tr></thead><tbody>`;
  let inGroup = false;
  for (const [name, get, fmt, o = {}] of spec.rows) {
    if (name === "group") { inGroup = true; html += `<tr class="group"><td colspan="${cols.length + 1}">${esc(get)}</td></tr>`; continue; }
    const sg = o.sign || 1;
    html += finRow(esc(name), cols.map((a) => {
      let v; try { v = get(a); } catch { v = null; }
      return cellOf(fmt === $M ? (fin(v) ? acct(sg * v, {}) : NA) : fmt(v));
    }), { kind: o.kind || "item", indent: o.indent ?? (inGroup ? 1 : 0) });
  }
  $("ratio-table").innerHTML = html + "</tbody>";
  $("ratio-note").textContent = `${spec.note} Marginal tax rate ${pct(state.detail.classification.marginal_tax_rate)}.`;
}

// ---------------------------------------------------------------- valuation

const MODEL_NAMES = { dcf: "DCF (standalone)", dcf_synergy: "DCF with synergies", just_synergy: "Just synergies",
  comps: "Public comps", precedents: "Precedent transactions", lbo: "LBO", ipo: "IPO" };

const SCENARIOS = { p10: "Bear", p50: "Base", p90: "Bull" };
const TRAIT_NAMES = { stage: "Stage", predictability: "Cash-flow predictability", asset_intensity: "Asset intensity",
  capital_structure: "Capital structure" };

function signed(v) { return fin(v) ? `${v >= 0 ? "+" : "−"}${Math.abs(v * 100).toFixed(1)}%` : NA; }
function upClass(v, band = 0.005) { return !fin(v) || Math.abs(v) < band ? "" : v > 0 ? "up" : "down"; }

function renderValuation() {
  if (!state.detail || state.tab !== "valuation") return;
  const c = state.comparison, body = $("val-body");
  if (!c || !c.football_field?.length) {
    body.innerHTML = `<div class="card empty"><h2>No model results for this run</h2>
      <p>Run the pipeline through <b>Models and reconcile</b> (with an assumptions file for each model) and the valuation appears here.</p></div>`;
    renderProfileCard(body);
    renderSimilar(body);
    return;
  }
  state.scn = state.scn || "p50";
  body.innerHTML = `<div id="val-head"></div><div id="val-ff"></div><div id="val-profile"></div><div id="val-comps"></div><div id="val-dcf"></div>
    <div id="val-similar"></div><div id="val-diffs"></div>`;
  renderHeadline();
  renderField();
  renderProfileCard($("val-profile"));
  renderCompsCard();
  renderDcfCard();
  renderSimilar($("val-similar"));
  const diffs = c.assumption_differences || [];
  $("val-diffs").innerHTML = `<div class="card"><div class="card-head"><h2>Where models disagree on inputs</h2></div>${diffs.length
    ? `<div class="table-wrap"><table class="list"><thead><tr><th>Field</th>${Object.keys(diffs[0].values).map((m) => `<th>${esc(MODEL_NAMES[m] || m)}</th>`).join("")}</tr></thead><tbody>${
      diffs.map((d) => `<tr><td>${esc(d.field)}</td>${Object.values(d.values).map((v) => `<td>${esc(typeof v === "number" ? num(v) : JSON.stringify(v))}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`
    : `<p class="muted">Every shared assumption matches, so gaps between models come from method, not inputs.</p>`}
    ${c.warnings?.length ? `<h3 style="margin-top:12px">Warnings</h3><ul>${c.warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul>` : ""}</div>`;
}

function scenarioToggle() {
  return `<div class="seg" role="group" aria-label="Scenario">${Object.entries(SCENARIOS).map(([k, n]) =>
    `<button type="button" data-scn="${k}" aria-pressed="${state.scn === k}">${n}</button>`).join("")}</div>`;
}

function wireToggle(root) {
  root.querySelectorAll("[data-scn]").forEach((b) => { b.onclick = () => { state.scn = b.dataset.scn; renderHeadline(); renderField(); }; });
}

function renderHeadline() {
  const c = state.comparison, k = state.scn, blend = c.blend;
  const primary = (c.plan?.methods || []).filter((m) => m.weight > 0);
  const up = c.upside?.[k];
  $("val-head").innerHTML = `<div class="card">
    <div class="card-head"><h2>Value vs price</h2><span class="muted small">scenario set on the football field below</span></div>
    <div class="headline">
      <div><div class="label">Share price</div><div class="big num">${price(c.price)}</div>
        <div class="muted small">${c.price_source ? `from ${esc(c.price_source)}` : "no price yet: add one to the DCF assumptions"}</div></div>
      <div><div class="label">Blended value · ${SCENARIOS[k]}</div><div class="big num">${blend ? price(blend[k]) : NA}</div>
        <div class="muted small">${blend ? `bear ${price(blend.p10)} – bull ${price(blend.p90)}` : "no weighted method has run"}</div></div>
      <div><div class="label">Upside / downside</div><div class="big num ${upClass(up, 0.05)}">${signed(up)}</div>
        <div class="muted small">${!fin(up) ? "" : Math.abs(up) < 0.05 ? "within 5% of price: fairly valued" : up > 0 ? "undervalued on this blend" : "overvalued on this blend"}</div></div>
    </div>
    <p class="small" style="margin:12px 0 0">${primary.map((m) => `${m.role === "primary" ? "Primary" : "Cross-check"} <b>${esc(m.name)}</b> ${pct(m.weight, true)}`).join(" · ") || "No weighted methods yet"}.
      <span class="muted">${esc(c.plan?.summary || "")}</span></p>
  </div>`;
}

function renderField() {
  const c = state.comparison, k = state.scn, methods = (c.plan?.methods || []).filter((m) => m.value_per_share);
  const vals = methods.flatMap((m) => [m.value_per_share.p10, m.value_per_share.p90]).concat(fin(c.price) ? [c.price] : []);
  const vmin = Math.min(...vals), vmax = Math.max(...vals);
  const raw = (vmax - vmin) / 4 || 1, mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((st) => st >= raw);
  const lo = Math.floor(vmin * 0.97 / step) * step, hi = Math.ceil(vmax * 1.03 / step) * step;
  const x = (v) => `${((v - lo) / (hi - lo)) * 100}%`;
  const ticks = []; for (let t = lo; t <= hi + step / 2; t += step) ticks.push(t);
  const bar = (v, cls) => `<div class="ff-bar ${cls}">
      <span class="rng" style="left:${x(v.p10)};width:calc(${x(v.p90)} - ${x(v.p10)})"></span>
      <span class="tick" style="left:${x(v[k])}"></span>
</div>`;
  const row = (m) => {
    const v = m.value_per_share, u = fin(c.price) ? v[k] / c.price - 1 : null;
    return `<div class="ff-row ${m.weight > 0 ? "" : "ref"}">
      <div class="ff-name"><b>${esc(m.name)}</b><div class="muted small">${esc(m.role)}${m.weight > 0 ? ` · ${pct(m.weight, true)}` : ""}</div></div>
      ${bar(v, "")}
      <div class="ff-num">${price(v.p10)} – ${price(v.p90)}</div>
      <div class="ff-num"><b>${price(v[k])}</b></div>
      <div class="ff-num ${upClass(u)}">${signed(u)}</div>
      <div class="ff-why small muted" title="${esc(m.reason)}">${esc(m.reason)}</div></div>`;
  };
  const b = c.blend;
  $("val-ff").innerHTML = `<div class="card">
    <div class="card-head"><h2>Football field</h2><span class="muted small">Value per share: bar = bear to bull, tick = ${SCENARIOS[k].toLowerCase()}, line = share price</span>
      <div class="spacer">${scenarioToggle()}</div></div>
    <div class="ff">
      <div class="ff-row ff-head"><div></div>
        <div class="ff-axis">${ticks.map((t) => `<span style="left:${x(t)}">$${Math.abs(t - Math.round(t)) < 1e-9 ? Math.round(t) : t.toFixed(1)}</span>`).join("")}</div>
        <div class="ff-num">Bear – bull</div><div class="ff-num">${SCENARIOS[k]}</div><div class="ff-num">vs price</div><div class="ff-why small">Why this role</div></div>
      ${methods.map(row).join("")}
      ${b ? `<div class="ff-row total"><div class="ff-name"><b>Blended</b><div class="muted small">weights above</div></div>${bar(b, "blend")}
        <div class="ff-num">${price(b.p10)} – ${price(b.p90)}</div><div class="ff-num"><b>${price(b[k])}</b></div>
        <div class="ff-num ${upClass(c.upside?.[k])}">${signed(c.upside?.[k])}</div><div class="ff-why"></div></div>` : ""}
    </div>
    ${c.plan?.notes?.length ? `<p class="legend-note">${c.plan.notes.map(esc).join(" ")}</p>` : ""}
    <p class="legend-note">Weights: assumptions/${esc(state.company.ticker)}/reconcile.json can override them (<code>{"weights": {"dcf": 0.7, "comps": 0.3}}</code>) or switch to <code>"context": "acquisition"</code> for an offer-price view.</p>
  </div>`;
  wireToggle($("val-ff"));
  drawPriceLine(fin(c.price) ? (c.price - lo) / (hi - lo) : null, c.price);
}

// One price line running through every row of the football field, so each
// method's range reads against the same reference.
function drawPriceLine(frac, value) {
  const ff = document.querySelector("#val-ff .ff");
  if (!ff || frac === null) return;
  const place = () => {
    ff.querySelectorAll(".ff-price").forEach((n) => n.remove());
    const bars = ff.querySelectorAll(".ff-bar");
    if (!bars.length) return;
    const box = ff.getBoundingClientRect();
    const first = bars[0].getBoundingClientRect(), last = bars[bars.length - 1].getBoundingClientRect();
    const left = first.left - box.left + frac * first.width;
    const add = (top, bottom, label) => {
      const line = Object.assign(document.createElement("div"), { className: "ff-price" });
      line.style.cssText = `left:${left}px;top:${top}px;height:${bottom - top}px`;
      if (label) line.innerHTML = `<span>Price ${price(value)}</span>`;
      ff.appendChild(line);
    };
    // bars stacked in one column (desktop): one line through all rows;
    // bars on their own lines (phone): a segment through each bar, same x
    const stacked = [...bars].every((b) => Math.abs(b.getBoundingClientRect().left - first.left) < 1)
      && !window.matchMedia("(max-width: 900px)").matches;
    if (stacked) add(first.top - box.top - 8, last.bottom - box.top + 8, true);
    else bars.forEach((b, i) => { const r = b.getBoundingClientRect(); add(r.top - box.top - 4, r.bottom - box.top + 4, i === 0); });
  };
  place();
  if (ff._ro) ff._ro.disconnect();
  ff._ro = new ResizeObserver(place);
  ff._ro.observe(ff);
}

function renderProfileCard(root) {
  const p = state.detail.profile;
  if (!p?.traits) return;
  const m = (k, v) => {
    const fmt = { revenue_cagr: ["Revenue CAGR", pct], operating_margin: ["Operating margin", pct],
      fcf_positive_share: ["FCF positive in", (x) => pct(x, true) + " of years"], fcf_margin_stdev: ["FCF margin stdev", (x) => fin(x) ? `${(x * 100).toFixed(1)} pts` : NA],
      capex_to_sales: ["Capex / sales", pct], noa_turnover: ["NOA turnover", times], debt_to_ebitda: ["Debt / EBITDA", times],
      net_debt_to_equity: ["Net debt / equity", num], liabilities_to_assets: ["Liabilities / assets", pct] }[k];
    return fmt ? `${fmt[0]} ${fmt[1](v)}` : null;
  };
  const plan = state.comparison?.plan;
  const html = `<div class="card">
    <div class="card-head"><h2>Company profile</h2><span class="muted small">${esc(p.as_of_period || "")} and ${p.history_years} fiscal years · methods follow these traits, not the sector label</span></div>
    <div class="traits">${Object.entries(p.traits).map(([k, t]) => `<div class="trait">
      <div class="label">${TRAIT_NAMES[k] || k}</div><div class="tval">${esc(t.label[0].toUpperCase() + t.label.slice(1))}</div>
      <div class="small">${Object.entries(t.measures).map(([mk, mv]) => m(mk, mv)).filter(Boolean).join("; ")}</div>
      <div class="rule">Rule: ${esc(t.rule)}</div></div>`).join("")}</div>
    ${plan ? `<p style="margin:14px 0 0"><b>So:</b> ${esc(plan.summary)}</p>
      <ul class="small" style="margin:6px 0 0 18px; padding:0">${plan.methods.filter((x) => x.role !== "reference" || x.ran).map((x) =>
        `<li><b>${esc(x.name)}</b> (${esc(x.role)}${x.weight > 0 ? `, ${pct(x.weight, true)}` : ""}): ${esc(x.reason)}${x.ran ? "" : " <span class='muted'>(not run)</span>"}</li>`).join("")}</ul>` : ""}
  </div>`;
  if (root.id === "val-profile") root.innerHTML = html; else root.insertAdjacentHTML("beforeend", html);
}

// Similar companies: nearest by profile measures (z-scored), not by sector.
const SIM_KEYS = ["revenue_cagr", "operating_margin", "fcf_margin_stdev", "capex_to_sales", "noa_turnover", "debt_to_ebitda", "log_revenue"];

function similarity(all, me) {
  const vec = (c) => ({ ...c.vector, log_revenue: c.vector.revenue > 0 ? Math.log10(c.vector.revenue) : null });
  const vs = all.map(vec), mine = vec(me);
  const stats = Object.fromEntries(SIM_KEYS.map((k) => {
    const xs = vs.map((v) => v[k]).filter(fin);
    const mu = xs.reduce((a, b) => a + b, 0) / (xs.length || 1);
    const sd = Math.sqrt(xs.reduce((a, b) => a + (b - mu) ** 2, 0) / (xs.length || 1)) || 1;
    return [k, { mu, sd }];
  }));
  return all.map((c, i) => {
    let d = 0, n = 0;
    for (const k of SIM_KEYS) {
      if (fin(vs[i][k]) && fin(mine[k])) { d += ((vs[i][k] - mine[k]) / stats[k].sd) ** 2; n++; }
    }
    const traitsMatch = Object.keys(me.traits).filter((t) => c.traits[t] === me.traits[t]).length;
    return { c, score: n ? 1 / (1 + Math.sqrt(d / n)) : null, traitsMatch };
  });
}

async function renderSimilar(root) {
  let data;
  try { data = state.companies || (state.companies = await getJSON("data/companies.json")); } catch { return; }
  const all = data.companies || [];
  const me = all.find((c) => c.ticker === state.company.ticker);
  if (!me) return;
  const ranked = similarity(all, me).filter((r) => r.c.ticker !== me.ticker && r.c.demo === me.demo)
    .sort((a, b) => (b.score ?? -1) - (a.score ?? -1)).slice(0, 10);
  const med = (k, grp) => { const xs = ranked.map((r) => r.c[grp][k]).filter(fin).sort((a, b) => a - b);
    return xs.length ? (xs.length % 2 ? xs[(xs.length - 1) / 2] : (xs[xs.length / 2 - 1] + xs[xs.length / 2]) / 2) : null; };
  const cols = [["P/E", "multiples", "pe", times], ["EV/EBITDA", "multiples", "ev_ebitda", times], ["EV/Sales", "multiples", "ev_sales", times],
    ["P/B", "multiples", "pb", times], ["FCF yield", "multiples", "fcf_yield", pct], ["Rev. CAGR", "rates", "revenue_cagr", pct],
    ["Op. margin", "rates", "operating_margin", pct], ["RNOA", "rates", "rnoa", pct], ["Debt/EBITDA", "rates", "debt_to_ebitda", times],
    ["WACC", "rates", "wacc", pct]];
  const cells = (c) => cols.map(([, g, k, f]) => `<td class="${fin(c[g][k]) ? "" : "na"}">${f(c[g][k])}</td>`).join("");
  const html = `<div class="card">
    <div class="card-head"><h2>Similar companies</h2><span class="muted small">ranked by closeness of growth, margins, cash-flow stability, capital intensity, leverage and size, across every company published here</span></div>
    ${ranked.length ? "" : `<p class="muted">No other ${me.demo ? "demo " : ""}companies published yet. Run the pipeline for more tickers; they're ranked here by profile, not sector.</p>`}
    <div class="table-wrap"><table class="list">
      <thead><tr><th>Company</th><th>Similarity</th><th>Traits shared</th>${cols.map(([n]) => `<th>${n}</th>`).join("")}</tr></thead>
      <tbody>
        <tr class="key target"><td>${esc(me.ticker)} <span class="muted small">this company</span></td><td>–</td><td>–</td>${cells(me)}</tr>
        ${ranked.map((r) => `<tr><td>${esc(r.c.ticker)} <span class="muted small">${esc(r.c.name)}</span></td><td>${fin(r.score) ? pct(r.score, true) : NA}</td>
          <td title="${Object.entries(r.c.traits).map(([k, v]) => `${TRAIT_NAMES[k]}: ${v}`).join("\n")}">${r.traitsMatch} of 4</td>${cells(r.c)}</tr>`).join("")}
        ${ranked.length > 1 ? `<tr class="sub"><td>Peer median</td><td></td><td></td>${cols.map(([, g, k, f]) => `<td>${f(med(k, g))}</td>`).join("")}</tr>` : ""}
      </tbody></table></div>
    <p class="legend-note">Multiples need a share price, which currently comes from each company's DCF assumptions; "–" means no price yet. Hover "Traits shared" for each company's profile.</p>
  </div>`;
  if (root.id === "val-similar") root.innerHTML = html; else root.insertAdjacentHTML("beforeend", html);
}

function renderCompsCard() {
  const r = state.comps, d = r?.details;
  if (!d?.peers || !$("val-comps")) return;
  const mids = Object.keys(d.multiples);
  const mult = (k) => ({ ev_sales: "EV/Sales", ev_ebitda: "EV/EBITDA", pe: "P/E" })[k] || k;
  const row = (p, isTarget) => `<tr class="${isTarget ? "key target" : ""}${p.excluded ? " na" : ""}">
    <td>${esc(p.ticker || "")} <span class="muted small">${esc(isTarget ? "target" : p.source === "manual" ? "manual figures" : (p.name || ""))}</span></td>
    <td>${price(p.price)}</td><td>${millions(p.enterprise_value)}</td>
    <td>${times(p.multiples.ev_sales)}</td><td>${times(p.multiples.ev_ebitda)}</td><td>${times(p.multiples.pe)}</td>
    <td>${pct(p.ebitda_margin)}</td><td>${pct(p.revenue_growth)}</td>
    ${mids.map((m) => `<td>${isTarget ? "–" : price(d.multiples[m].implied[p.ticker])}</td>`).join("")}</tr>`;
  $("val-comps").innerHTML = `<div class="card">
    <div class="card-head"><h2>Public comps</h2><span class="muted small">${esc(d.range_method === "min_max" ? "range = lowest / median / highest implied price" : "range = Q1 / median / Q3 implied price")}</span></div>
    <div class="tiles">${mids.map((m) => { const x = d.multiples[m]; return `<div class="tile"><div class="label">${mult(m)} · weight ${pct(x.weight / mids.reduce((s, k) => s + d.multiples[k].weight, 0), true)}</div>
      <div class="value">${price(x.expected)}</div><div class="delta">${price(x.conservative)} – ${price(x.aggressive)} · peer avg ${times(x.peer_average)}</div></div>`; }).join("")}
      <div class="tile"><div class="label">Blended comps value</div><div class="value">${price(d.blend.expected)}</div>
      <div class="delta">${price(d.blend.conservative)} – ${price(d.blend.aggressive)}</div></div></div>
    <div class="table-wrap"><table class="list">
      <thead><tr><th>Company</th><th>Price</th><th>EV ($M)</th><th>EV/Sales</th><th>EV/EBITDA</th><th>P/E</th><th>EBITDA margin</th><th>Rev. CAGR</th>
        ${mids.map((m) => `<th>Implied (${mult(m)})</th>`).join("")}</tr></thead>
      <tbody>${row(d.target, true)}${d.peers.map((p) => row(p, false)).join("")}</tbody></table></div>
    ${r.notes?.length ? `<p class="legend-note">${r.notes.map(esc).join(" · ")}</p>` : ""}
  </div>`;
}

function bridgeRows(b) {
  const excess = b.cash * (1 - b.operating_cash_pct);
  const other = b.debt - excess - b.net_debt;   // e.g. long-term investments, when included
  const v = (x, o) => [cellOf(acct(x, o))];
  return [
    finRow("PV of free cash flow", v(b.pv_fcf), { indent: 1 }),
    finRow("PV of terminal value", v(b.pv_terminal_value), { indent: 1 }),
    finRow("Enterprise value", v(b.enterprise_value), { kind: "sub" }),
    finRow("Less: debt", v(-b.debt), { indent: 1 }),
    finRow(`Plus: cash beyond operating needs (${pct(1 - b.operating_cash_pct, true)} of ${millions(b.cash)})`, v(excess), { indent: 1 }),
    Math.abs(other) > 1 ? finRow("Plus: long-term investments", v(other), { indent: 1 }) : "",
    finRow("Equity value", v(b.equity_value), { kind: "sub" }),
    finRow("÷ Diluted shares (M)", v(b.shares), { indent: 1 }),
    finRow("Value per share", [cellOf(price(b.value_per_share))], { kind: "grand" }),
  ].join("");
}

function renderDcfCard() {
  const r = state.dcf, d = r?.details;
  if (!d?.bridge) return;
  const b = d.bridge, rt = d.rates, t = d.terminal, sc = d.scenarios;
  const card = document.createElement("div");
  card.className = "card";
  const tile = (l, v, sub = "") => `<div class="tile"><div class="label">${esc(l)}</div><div class="value">${v}</div>${sub ? `<div class="delta">${esc(sub)}</div>` : ""}</div>`;
  card.innerHTML = `
    <div class="card-head"><h2>DCF (standalone)</h2>
      <span class="muted small">${esc(d.mode === "implied" ? "Implied mode: growth solved to match the price" : "Forecast mode")} · base ${esc(d.base_period.label)}</span></div>
    <div class="tiles">
      ${tile("Value per share", price(b.value_per_share), `range ${price(sc.conservative)} – ${price(sc.aggressive)}`)}
      ${d.implied_growth != null ? tile("Implied near-term growth", pct(d.implied_growth), `price ${price(d.market_price)}`) : tile("Price (assumptions)", price(d.market_price))}
      ${tile("WACC", pct(rt.wacc), `terminal year ${pct(rt.wacc_terminal)}`)}
      ${tile("Terminal value share", pct(d.terminal_value_share), `terminal EV/EBITDA ${times(t.ev_to_ebitda)}`)}
    </div>
    <div class="grid-2">
      <div><h3>Bridge ($M)</h3><div class="table-wrap"><table><tbody>${bridgeRows(b)}</tbody></table></div></div>
      <div><h3>Discount rates</h3><div class="table-wrap"><table><tbody>
        <tr class="group"><td colspan="2">Cost of equity</td></tr>
        ${finRow("Beta: observed → unlevered → relevered", [cellOf(`${num(rt.beta_levered_observed)} → ${num(rt.beta_unlevered)} → ${num(rt.beta_relevered)}`)], { indent: 1 })}
        ${finRow("Target debt / equity", [cellOf(num(rt.target_debt_to_equity))], { indent: 1 })}
        ${finRow("Cost of equity", [cellOf(pct(rt.cost_of_equity))], { kind: "sub", indent: 1 })}
        <tr class="group"><td colspan="2">Cost of debt</td></tr>
        ${finRow(`Pre-tax cost of debt (${esc({ interest_over_debt: "interest ÷ debt", given: "given", fallback: "fallback yield" }[rt.cost_of_debt_method] || "given")})`, [cellOf(pct(rt.pre_tax_cost_of_debt))], { indent: 1 })}
        ${finRow("Weights: equity / debt", [cellOf(`${pct(rt.equity_weight)} / ${pct(rt.debt_weight)}`)], { indent: 1 })}
        ${finRow("WACC (pre-terminal)", [cellOf(pct(rt.wacc))], { kind: "grand" })}
        <tr class="group"><td colspan="2">Terminal year</td></tr>
        ${finRow("Risk-free rate", [cellOf(pct(rt.risk_free_terminal))], { indent: 1 })}
        ${finRow("Cost of equity", [cellOf(pct(rt.cost_of_equity_terminal))], { indent: 1 })}
        ${finRow("WACC (terminal year)", [cellOf(pct(rt.wacc_terminal))], { kind: "sub" })}
        ${finRow("Terminal growth", [cellOf(pct(t.growth))], { indent: 1, kind: "memo" })}
        ${finRow("Terminal ROIC", [cellOf(pct(t.roic))], { indent: 1, kind: "memo" })}
      </tbody></table></div></div>
    </div>
    <h3 style="margin-top:16px">Projection ($M)</h3>
    <div class="table-wrap"><table>
      <thead><tr><th>Year</th>${d.projection.map((y) => `<th>Y${y.year}</th>`).join("")}</tr></thead>
      <tbody>
        ${finRow("Revenue", d.projection.map((y) => cellOf(acct(y.revenue))), { kind: "key" })}
        ${finRow("EBITDA", d.projection.map((y) => cellOf(acct(y.ebitda))), { indent: 1 })}
        ${finRow("Capital expenditures", d.projection.map((y) => cellOf(acct(-y.capex))), { indent: 1 })}
        ${finRow("Increase in net working capital", d.projection.map((y) => cellOf(acct(-y.change_in_nwc))), { indent: 1 })}
        ${finRow("Unlevered free cash flow", d.projection.map((y) => cellOf(acct(y.fcf))), { kind: "sub" })}
        ${finRow("Present value", d.projection.map((y) => cellOf(acct(y.pv))), { kind: "memo", indent: 1 })}
      </tbody></table></div>
    <p class="legend-note">Free cash flow = EBITDA × (1 − t) + D&amp;A × t − capex − ΔNWC, so it isn't the simple sum of the lines above.</p>
    <p class="legend-note">Year 1 is the closing year (not discounted). Range: conservative and aggressive move near-term growth with WACC and terminal growth with terminal WACC, blended by the terminal value's share.${r.notes?.length ? " " + esc(r.notes.filter((n) => !n.startsWith("range =")).join(" ")) : ""}</p>`;
  ($("val-dcf") || $("val-body")).appendChild(card);
}

// ---------------------------------------------------------------- run pipeline

function repoGuess() {
  const h = location.hostname;
  if (h.endsWith(".github.io")) return { owner: h.split(".")[0], repo: location.pathname.split("/").filter(Boolean)[0] || `${h}` };
  return { owner: "", repo: "valuation" };
}

function setupRunForm() {
  const g = repoGuess();
  $("r-owner").value = store.get("gh_owner") || g.owner;
  $("r-repo").value = store.get("gh_repo") || g.repo;
  const tok = store.get("gh_token");
  if (tok) { $("r-token").value = tok; $("r-remember").checked = true; }
  $("r-asof").value = new Date().toISOString().slice(0, 10);
  const refresh = () => {
    const o = $("r-owner").value.trim(), r = $("r-repo").value.trim(), i = runInputs();
    $("r-actions-link").href = o && r ? `https://github.com/${encodeURIComponent(o)}/${encodeURIComponent(r)}/actions/workflows/pipeline.yml` : "https://github.com";
    $("r-cli").textContent = `gh workflow run pipeline.yml${o && r ? ` -R ${o}/${r}` : ""} \\\n  -f ticker=${i.ticker || "AAPL"} -f as_of=${i.as_of} -f stop_after=${i.stop_after} -f models=${i.models}`;
  };
  $("run-form").addEventListener("input", refresh);
  refresh();
  $("run-form").onsubmit = async (e) => {
    e.preventDefault();
    const status = $("r-status");
    const o = $("r-owner").value.trim(), r = $("r-repo").value.trim(), token = $("r-token").value.trim();
    const inputs = runInputs();
    store.set("gh_owner", o); store.set("gh_repo", r);
    store.set("gh_token", $("r-remember").checked && token ? token : null);
    if (!/^[A-Za-z][A-Za-z0-9.\-]{0,9}$/.test(inputs.ticker)) { status.className = "status err"; status.textContent = "Enter a valid ticker."; return; }
    if (!o || !r) { status.className = "status err"; status.textContent = "Fill in the owner and repository."; return; }
    if (!token) { status.className = "status"; status.textContent = "No token: use the Actions page link or the CLI command below."; return; }
    status.className = "status"; status.textContent = "Starting…";
    try {
      const res = await fetch(`https://api.github.com/repos/${encodeURIComponent(o)}/${encodeURIComponent(r)}/actions/workflows/pipeline.yml/dispatches`, {
        method: "POST",
        headers: { Accept: "application/vnd.github+json", Authorization: `Bearer ${token}`, "X-GitHub-Api-Version": "2022-11-28" },
        body: JSON.stringify({ ref: "main", inputs }),
      });
      if (res.status === 204) {
        status.className = "status ok";
        status.innerHTML = `Started. <a href="https://github.com/${esc(o)}/${esc(r)}/actions" target="_blank" rel="noopener">Follow it on GitHub</a>; reload this page when it finishes.`;
      } else {
        const msg = await res.json().catch(() => ({}));
        status.className = "status err";
        status.textContent = `GitHub said ${res.status}: ${msg.message || "request failed"}`;
      }
    } catch (err) {
      status.className = "status err"; status.textContent = `Request failed: ${err.message}`;
    }
  };
}

function runInputs() {
  const models = [...document.querySelectorAll("#r-models input:checked")].map((x) => x.value).join(",") || "dcf";
  return { ticker: $("r-ticker").value.trim().toUpperCase(), as_of: $("r-asof").value, models, stop_after: $("r-stop").value };
}

init();
