// Valuation site: reads the JSON the pipeline publishes to data/ and renders it.
// The only computation here is the projection what-if (projection.js, a tested
// port of core/projection.py). Everything else is display.

import { project, baseFromDetail, ProjectionError } from "./projection.js";
import { columnChart, lineChart, rangeChart } from "./charts.js";

const $ = (id) => document.getElementById(id);
const state = { index: null, concepts: {}, company: null, run: null, detail: null, comparison: null,
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
  setupProjectionForm();
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
  resetProjection();
  renderValuation();
  $("r-ticker").value = state.company.demo ? "" : state.company.ticker;
}

function renderEmptyEverywhere() {
  const msg = `<div class="card empty"><h2>No published results yet</h2>
    <p>Use <b>Run pipeline</b> to fetch a company, or run <code>python -m L3_app.demo</code> for a synthetic preview.</p></div>`;
  for (const id of ["panel-company", "panel-projection", "panel-valuation"]) $(id).innerHTML = msg;
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
    if (name === "projection" && state.detail) runProjection();
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
    if (state.detail) { renderCompany(); runProjection(); renderValuation(); }
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

const STATEMENT_ROWS = [
  ["Income statement", ["revenue", "cost_of_goods_and_services_sold", "gross_profit", "research_and_development_expenses",
    "selling_general_and_admin_expenses", "operating_income_loss", "depreciation_amortization_cf", "ebitda",
    "interest_expense", "interest_income", "pretax_income_loss", "income_taxes", "net_income"]],
  ["Balance sheet", ["cash_and_marketable_securities", "trade_receivables", "inventories", "current_assets_total",
    "plant_property_equipment_net", "goodwill", "assets", "trade_payables", "short_term_debt",
    "current_liabilities_total", "long_term_debt", "liabilities", "all_equity_balance", "net_debt"]],
  ["Cash flow", ["operating_cash_flow", "capital_expenses", "free_cash_flow", "stock_repurchased", "common_dividends_paid"]],
  ["Per share", ["eps_diluted", "shares_fully_diluted_average"]],
];
const TOTALS = new Set(["revenue", "gross_profit", "operating_income_loss", "net_income", "assets", "liabilities",
  "current_assets_total", "current_liabilities_total", "operating_cash_flow", "free_cash_flow"]);
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
  $("tiles").innerHTML = tiles.map((t) => `<div class="tile"><div class="label">${esc(t.label)}</div>
    <div class="value">${t.value}</div>${t.delta ? `<div class="delta ${t.dir >= 0 ? "up" : "down"}">${t.delta}</div>` : ""}</div>`).join("");
}

function renderRevenueChart() {
  const view = state.view;
  const ps = (state.detail.views[view] || []).slice(-12);
  $("rev-title").textContent = view === "ttm" ? "Revenue, trailing twelve months" : view === "quarterly" ? "Revenue by quarter" : "Revenue by fiscal year";
  $("rev-sub").textContent = ps.length ? `${ps[0].label} to ${ps.at(-1).label}` : "";
  columnChart($("rev-chart"), { categories: ps.map(shortLabel), values: ps.map((p) => p.values.revenue), format: money, label: "Revenue" });
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

function renderStatements() {
  const ps = periodsFor(state.view);
  const t = $("stmt-table");
  if (!ps.length) { t.innerHTML = `<tbody><tr><td class="muted">No ${state.view} periods.</td></tr></tbody>`; return; }
  let html = `<thead><tr><th scope="col">$ millions</th>${ps.map((p) => `<th scope="col" title="${esc(p.start)} to ${esc(p.end)}">${esc(shortLabel(p))}</th>`).join("")}</tr></thead><tbody>`;
  for (const [group, ids] of STATEMENT_ROWS) {
    const rows = ids.filter((id) => ps.some((p) => fin(p.values[id])));
    if (!rows.length) continue;
    html += `<tr class="group"><td colspan="${ps.length + 1}">${group}</td></tr>`;
    for (const id of rows) {
      const perShare = id === "eps_diluted", shares = id.startsWith("shares");
      html += `<tr class="${TOTALS.has(id) ? "total" : ""}"><td>${esc(label(id))}${perShare ? " ($)" : shares ? " (M shares)" : ""}</td>`;
      for (const p of ps) {
        const v = p.values[id], m = p.methods[id];
        const txt = perShare ? num(v) : shares ? millions(v) : millions(v);
        const mark = DERIVED_METHODS.has(m) ? `<span class="mark" title="${esc(m.replace(/_/g, " "))}">d</span>` : "";
        html += `<td class="${fin(v) ? "" : "na"}">${txt}${mark}</td>`;
      }
      html += "</tr>";
    }
  }
  t.innerHTML = html + "</tbody>";
}

const RATIO_ROWS = {
  reformulated: {
    note: "Operating vs financial split. NOPAT = net income + after-tax net interest. ROCE = RNOA + FLEV × (RNOA − NBC).",
    rows: [
      ["Operating margin (NOPM)", (a) => a.ratios.reformulated.nopm, pct],
      ["Core NOPM", (a) => a.ratios.reformulated.core_nopm, pct],
      ["group", "Average balances"],
      ["NOA turnover (NOAT)", (a) => a.ratios.reformulated.avg?.noat, times],
      ["RNOA", (a) => a.ratios.reformulated.avg?.rnoa, pct],
      ["ROCE", (a) => a.ratios.reformulated.avg?.roce, pct],
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
      ["Net operating assets", (a) => a.reformulated_balance_sheet.noa, millions],
      ["Net nonoperating obligations", (a) => a.reformulated_balance_sheet.nno, millions],
      ["Common equity incl. NCI", (a) => a.reformulated_balance_sheet.cse_incl_nci, millions],
      ["NOPAT", (a) => a.reformulated_income_statement.nopat, millions],
      ["FCF = NOPAT − ΔNOA", (a) => a.ratios.reformulated.fcf, millions],
    ],
  },
  managerial: {
    note: "Managerial balance sheet: cash + working-capital requirement + fixed assets = capital employed.",
    rows: [
      ["group", "Managerial balance sheet ($M)"],
      ["Cash", (a) => a.managerial_balance_sheet.cash, millions],
      ["Working-capital requirement", (a) => a.managerial_balance_sheet.wcr, millions],
      ["Fixed assets", (a) => a.managerial_balance_sheet.fixed_assets, millions],
      ["Invested capital", (a) => a.managerial_balance_sheet.invested_capital, millions],
      ["group", "Liquidity and operating cycle"],
      ["Net long-term financing (NLF)", (a) => a.ratios.managerial.nlf, millions],
      ["Net short-term financing (NSF)", (a) => a.ratios.managerial.nsf, millions],
      ["Liquidity ratio (NLF / WCR)", (a) => a.ratios.managerial.liquidity_ratio, num],
      ["WCR / sales", (a) => a.ratios.managerial.wcr_to_sales, pct],
      ["Collection period", (a) => a.ratios.managerial.collection_period_days, days],
      ["Days inventory", (a) => a.ratios.managerial.days_inventory, days],
      ["Inventory turnover", (a) => a.ratios.managerial.inventory_turnover, times],
      ["Payment period", (a) => a.ratios.managerial.payment_period_days, days],
      ["Current ratio", (a) => a.ratios.managerial.current_ratio, num],
      ["Acid test", (a) => a.ratios.managerial.acid_test, num],
      ["group", "Free cash flow ($M)"],
      ["NOPLAT", (a) => a.fcf_managerial.noplat, millions],
      ["Capex (ΔFA + depreciation)", (a) => a.fcf_managerial.capex_from_balance_sheet, millions],
      ["ΔWCR", (a) => a.fcf_managerial.change_in_wcr, millions],
      ["FCF", (a) => a.fcf_managerial.fcf, millions],
    ],
  },
  traditional: {
    note: "Profit margin adds back after-tax interest expense. ROA = margin × turnover.",
    rows: [
      ["Profit margin", (a) => a.ratios.traditional.profit_margin, pct],
      ["Asset turnover", (a) => a.ratios.traditional.asset_turnover, times],
      ["ROA", (a) => a.ratios.traditional.roa, pct],
      ["Leverage (assets / equity)", (a) => a.ratios.traditional.leverage, times],
      ["ROE", (a) => a.ratios.traditional.roe, pct],
    ],
  },
  risk: {
    note: "Altman Z public needs a market price (not published on this site); the private-firm form uses book equity. Zones: Z < 1.2 distress, < 2.9 grey.",
    rows: [
      ["Altman Z (private form)", (a) => a.ratios.risk.altman_z.private, num],
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
  for (const [name, get, fmt] of spec.rows) {
    if (name === "group") { html += `<tr class="group"><td colspan="${cols.length + 1}">${esc(get)}</td></tr>`; continue; }
    html += `<tr><td>${esc(name)}</td>${cols.map((a) => {
      let v; try { v = get(a); } catch { v = null; }
      const txt = fmt(v);
      return `<td class="${txt === NA ? "na" : ""}">${txt}</td>`;
    }).join("")}</tr>`;
  }
  $("ratio-table").innerHTML = html + "</tbody>";
  $("ratio-note").textContent = `${spec.note} Marginal tax rate ${pct(state.detail.classification.marginal_tax_rate)}.`;
}

// ---------------------------------------------------------------- projection

const F = { years: "p-years", g0: "p-g0", gt: "p-gt", fade: "p-fade", cogs: "p-cogs", sga: "p-sga", rnd: "p-rnd",
  other: "p-other", dep: "p-dep", capex: "p-capex", nwc: "p-nwc", tax: "p-tax", plug: "p-plug", rate: "p-rate",
  payout: "p-payout", cida: "p-cida", base: "p-base" };

function setupProjectionForm() {
  $("proj-form").addEventListener("input", () => runProjection());
  $("proj-form").addEventListener("change", (e) => { if (e.target.id === F.base) { fillDefaults(); } runProjection(); });
  $("proj-reset").onclick = () => { fillDefaults(); runProjection(); };
  $("proj-download").onclick = downloadDrivers;
}

function basePeriods() {
  const v = state.detail.views;
  const out = [];
  if (v.ttm.length) out.push({ key: `ttm:${v.ttm.length - 1}`, label: `TTM to ${v.ttm.at(-1).end}`, p: v.ttm.at(-1), series: v.ttm });
  v.annual.slice().reverse().forEach((p, i) => out.push({ key: `annual:${v.annual.length - 1 - i}`, label: p.label, p, series: v.annual }));
  return out;
}

function resetProjection() {
  const opts = basePeriods();
  $(F.base).innerHTML = opts.map((o) => `<option value="${o.key}">${esc(o.label)}</option>`).join("");
  fillDefaults();
  runProjection();
}

function currentBase() {
  return basePeriods().find((o) => o.key === $(F.base).value) || basePeriods()[0];
}

const r1 = (x) => Math.round(x * 1000) / 10;   // ratio -> percent with one decimal
const clamp = (x, lo, hi) => Math.max(lo, Math.min(hi, x));

function fillDefaults() {
  const sel = currentBase();
  if (!sel) return;
  const v = sel.p.values, b = baseFromDetail(v);
  const prior = sel.series.find((p) => Math.abs(new Date(sel.p.end) - new Date(p.end) - 365 * 864e5) < 20 * 864e5);
  const g = prior?.values.revenue ? v.revenue / prior.values.revenue - 1 : 0.05;
  const rev = b.revenue || 1;
  const da = (b.depreciation || 0) + (b.amortization || 0);
  const tax = fin(v.income_taxes) && fin(v.pretax_income_loss) && v.pretax_income_loss > 0 ? v.income_taxes / v.pretax_income_loss : 0.21;
  const debt = (b.short_term_debt || 0) + (b.long_term_debt || 0);
  const rate = debt > 0 && fin(v.interest_expense) ? v.interest_expense / debt : 0.05;
  let nwc = 0.1;
  if (prior) {
    const bp = baseFromDetail(prior.values);
    const wcr = (x) => x.receivables + x.inventory + x.other_current_assets - x.payables - x.accrued;
    const dS = b.revenue - bp.revenue;
    if (dS) nwc = clamp((wcr(b) - wcr(bp)) / dS, -0.5, 0.5);
  }
  const set = (k, x) => { $(F[k]).value = x; };
  set("years", 5); set("g0", r1(clamp(g, -0.5, 1))); set("gt", 3); set("fade", 5);
  set("cogs", r1((b.cogs || 0) / rev)); set("sga", r1((b.sga || 0) / rev)); set("rnd", r1((b.rnd || 0) / rev));
  set("other", r1((b.other_opex || 0) / rev)); set("dep", r1(da / rev));
  set("capex", r1(fin(b.capex) ? b.capex / rev : da / rev)); set("nwc", r1(nwc));
  set("tax", r1(clamp(tax, 0, 0.6))); set("rate", r1(clamp(rate, 0, 0.3))); set("payout", 0);
  $(F.plug).value = "cash"; $(F.cida).checked = true;
  $("proj-base-note").textContent = `Base: ${sel.label}. Defaults are the base period's own ratios.`;
}

function readDrivers() {
  const n = (k) => { const x = parseFloat($(F[k]).value); return Number.isFinite(x) ? x : 0; };
  const p = (k) => n(k) / 100;
  const years = clamp(Math.round(n("years")) || 5, 1, 20);
  const drivers = {
    revenue: { method: "fade", g0: p("g0"), g_terminal: p("gt"), fade_years: Math.max(1, Math.round(n("fade"))) },
    cogs: { method: "pct_of_sales", value: p("cogs") },
    sga: { method: "pct_of_sales", value: p("sga") },
    rnd: { method: "pct_of_sales", value: p("rnd") },
    other_opex: { method: "pct_of_sales", value: p("other") },
    depreciation: { method: "pct_of_sales", value: p("dep") },
    amortization: { method: "values", values: [0] },
    capex: { method: "pct_of_sales", value: p("capex") },
    nwc: { method: "incremental", ratio: p("nwc") },
    tax_rate: p("tax"),
    interest: { method: "rate_on_debt", rate: p("rate"), basis: "beginning" },
    dividends: { payout: p("payout") },
    costs_include_da: $(F.cida).checked,
    plug: $(F.plug).value,
  };
  return { years, drivers };
}

function projectionBase() {
  const b = baseFromDetail(currentBase().p.values);
  // the form has one D&A line; fold amortization into depreciation
  b.depreciation = (b.depreciation || 0) + (b.amortization || 0);
  b.amortization = 0;
  return b;
}

function runProjection() {
  if (!state.detail || state.tab !== "projection") return;
  const sel = currentBase();
  if (!sel) return;
  const { years, drivers } = readDrivers();
  let out;
  try {
    out = project(projectionBase(), drivers, years);
  } catch (e) {
    $("proj-checks").textContent = e instanceof ProjectionError ? e.message : String(e);
    return;
  }
  const ys = out.years, last = ys.at(-1);
  const cagr = (last.revenue / out.base.revenue) ** (1 / ys.length) - 1;
  const cumFcf = ys.reduce((s, y) => s + y.free_cash_flow.fcf, 0);
  $("proj-tiles").innerHTML = [
    ["Revenue, final year", money(last.revenue), `${pct(cagr)} a year`],
    ["EBIT margin, final year", pct(last.ebit / last.revenue), ""],
    [`Cumulative FCF, ${ys.length} years`, money(cumFcf), ""],
    ["Statements balance", ys.every((y) => Math.abs(y.balance_check) < 1 && y.cash_flow.ties) ? "Yes" : "No", "invested capital = capital employed; cash flow ties"],
  ].map(([l, v, d]) => `<div class="tile"><div class="label">${esc(l)}</div><div class="value">${v}</div>${d ? `<div class="delta">${esc(d)}</div>` : ""}</div>`).join("");
  const cats = ys.map((y) => `Y${y.year}`);
  columnChart($("proj-chart"), { categories: cats, values: ys.map((y) => y.free_cash_flow.fcf), format: money, label: "Free cash flow" });

  const base = out.base;
  const rows = [
    ["group", "Income statement"],
    ["Revenue", (y) => y.revenue, base.revenue, true],
    ["Growth", (y, p) => y.revenue / p.revenue - 1, null, false, pct],
    ["COGS", (y) => y.cogs, base.cogs], ["SG&A", (y) => y.sga, base.sga], ["R&D", (y) => y.rnd, base.rnd],
    ["Other operating", (y) => y.other_opex, base.other_opex],
    ["EBITDA", (y) => y.ebitda, null, true], ["D&A", (y) => y.depreciation, base.depreciation],
    ["EBIT", (y) => y.ebit, null, true], ["Interest, net", (y) => y.interest_expense - y.interest_income, null],
    ["Taxes", (y) => y.income_taxes, base.income_taxes], ["Net income", (y) => y.net_income, base.net_income, true],
    ["group", "Managerial balance sheet"],
    ["Cash", (y) => y.cash, base.cash], ["Working-capital requirement", (y) => y.wcr, base.wcr],
    ["Fixed assets", (y) => y.fixed_assets, base.fixed_assets],
    ["Debt incl. revolver", (y) => y.short_term_debt + y.long_term_debt + y.revolver, base.short_term_debt + base.long_term_debt],
    ["Equity", (y) => y.equity, base.equity, true],
    ["group", "Cash flow"],
    ["Operating", (y) => y.cash_flow.cfo], ["Investing", (y) => y.cash_flow.cfi], ["Financing", (y) => y.cash_flow.cff],
    ["group", "Free cash flow"],
    ["NOPAT", (y) => y.free_cash_flow.nopat], ["Capex", (y) => y.capex], ["ΔNWC", (y) => y.free_cash_flow.change_in_nwc],
    ["Unlevered FCF", (y) => y.free_cash_flow.fcf, null, true],
  ];
  let html = `<thead><tr><th scope="col">$ millions</th><th scope="col">Base</th>${cats.map((c) => `<th scope="col">${c}</th>`).join("")}</tr></thead><tbody>`;
  for (const [name, get, b0, total, fmt = millions] of rows) {
    if (name === "group") { html += `<tr class="group"><td colspan="${ys.length + 2}">${esc(get)}</td></tr>`; continue; }
    html += `<tr class="${total ? "total" : ""}"><td>${esc(name)}</td><td class="${fin(b0) ? "" : "na"}">${fin(b0) ? fmt(b0) : NA}</td>`;
    ys.forEach((y, i) => { html += `<td>${fmt(get(y, i ? ys[i - 1] : base))}</td>`; });
    html += "</tr>";
  }
  $("proj-table").innerHTML = html + "</tbody>";
  const ok = ys.every((y) => Math.abs(y.balance_check) < 1 && y.cash_flow.ties);
  $("proj-checks").innerHTML = ok ? `<span class="ok-pill">✓ Balances and cash flow tie every year</span>` : `<span class="bad-pill">✕ Check failed</span>`;
}

function downloadDrivers() {
  const { years, drivers } = readDrivers();
  const body = { ticker: state.company?.ticker, as_of: state.run?.as_of, base_period: currentBase()?.label, years, drivers };
  const blob = new Blob([JSON.stringify(body, null, 2)], { type: "application/json" });
  const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: `${state.company?.ticker || "drivers"}_projection.json` });
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

// ---------------------------------------------------------------- valuation

const MODEL_NAMES = { dcf: "DCF (standalone)", dcf_synergy: "DCF with synergies", just_synergy: "Just synergies",
  comps: "Public comps", precedents: "Precedent transactions", lbo: "LBO", ipo: "IPO" };

function renderValuation() {
  if (!state.detail || state.tab !== "valuation") return;
  const c = state.comparison, body = $("val-body");
  if (!c || !c.football_field?.length) {
    body.innerHTML = `<div class="card empty"><h2>No model results for this run</h2>
      <p>The valuation models (L2) aren't built yet. Once they are, run the pipeline through <b>Models and reconcile</b> and the football field appears here.</p></div>`;
    return;
  }
  const rows = c.football_field.map((r) => ({ label: MODEL_NAMES[r.model] || r.model, lo: r.p10, mid: r.p50, hi: r.p90 }));
  const mkt = state.detail.market?.price ?? state.dcf?.details?.market_price;
  body.innerHTML = `
    <div class="card"><div class="card-head"><h2>Football field</h2><span class="muted small">Value per share, low to high, best estimate marked</span></div>
      <div id="ff-chart"></div></div>
    <div class="grid-2">
      <div class="card"><div class="card-head"><h2>Ranges</h2></div><div class="table-wrap"><table id="ff-table"></table></div></div>
      <div class="card"><div class="card-head"><h2>Where models disagree on inputs</h2></div><div id="ff-diffs"></div></div>
    </div>
    ${c.warnings?.length ? `<div class="card"><h2>Warnings</h2><ul>${c.warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul></div>` : ""}`;
  rangeChart($("ff-chart"), { rows, format: price, label: "Football field",
    reference: fin(mkt) ? { value: mkt, label: "Price" } : null });
  renderDcfCard();
  $("ff-table").innerHTML = `<thead><tr><th>Model</th><th>P10</th><th>P50</th><th>P90</th><th>Mean</th></tr></thead><tbody>${
    c.football_field.map((r) => `<tr><td>${esc(MODEL_NAMES[r.model] || r.model)}</td><td>${price(r.p10)}</td><td>${price(r.p50)}</td><td>${price(r.p90)}</td><td>${price(r.mean)}</td></tr>`).join("")}</tbody>`;
  const diffs = c.assumption_differences || [];
  $("ff-diffs").innerHTML = diffs.length
    ? `<div class="table-wrap"><table><thead><tr><th>Field</th>${Object.keys(diffs[0].values).map((m) => `<th>${esc(m)}</th>`).join("")}</tr></thead><tbody>${
      diffs.map((d) => `<tr><td>${esc(d.field)}</td>${Object.values(d.values).map((v) => `<td>${esc(JSON.stringify(v))}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`
    : `<p class="muted">Every shared assumption matches, so gaps between models come from method, not inputs.</p>`;
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
      <div><h3>Bridge ($M)</h3><div class="table-wrap"><table><tbody>
        <tr><td>PV of free cash flow</td><td>${millions(b.pv_fcf)}</td></tr>
        <tr><td>PV of terminal value</td><td>${millions(b.pv_terminal_value)}</td></tr>
        <tr class="total"><td>Enterprise value</td><td>${millions(b.enterprise_value)}</td></tr>
        <tr><td>Debt</td><td>${millions(b.debt)}</td></tr>
        <tr><td>Cash beyond operating needs (${pct(1 - b.operating_cash_pct, true)} of ${millions(b.cash)})</td><td>${millions(b.cash * (1 - b.operating_cash_pct))}</td></tr>
        <tr><td>Net debt</td><td>${millions(b.net_debt)}</td></tr>
        <tr class="total"><td>Equity value</td><td>${millions(b.equity_value)}</td></tr>
        <tr><td>Diluted shares (M)</td><td>${millions(b.shares)}</td></tr>
        <tr class="total"><td>Value per share</td><td>${price(b.value_per_share)}</td></tr>
      </tbody></table></div></div>
      <div><h3>Discount rates</h3><div class="table-wrap"><table><tbody>
        <tr><td>Beta observed → unlevered → relevered</td><td>${num(rt.beta_levered_observed)} → ${num(rt.beta_unlevered)} → ${num(rt.beta_relevered)}</td></tr>
        <tr><td>Target debt / equity</td><td>${num(rt.target_debt_to_equity)}</td></tr>
        <tr><td>Cost of equity</td><td>${pct(rt.cost_of_equity)}</td></tr>
        <tr class="total"><td>WACC (pre-terminal)</td><td>${pct(rt.wacc)}</td></tr>
        <tr><td>Terminal risk-free rate</td><td>${pct(rt.risk_free_terminal)}</td></tr>
        <tr><td>Terminal cost of equity</td><td>${pct(rt.cost_of_equity_terminal)}</td></tr>
        <tr class="total"><td>WACC (terminal year)</td><td>${pct(rt.wacc_terminal)}</td></tr>
        <tr><td>Terminal growth</td><td>${pct(t.growth)}</td></tr>
        <tr><td>Terminal ROIC</td><td>${pct(t.roic)}</td></tr>
      </tbody></table></div></div>
    </div>
    <h3 style="margin-top:16px">Projection ($M)</h3>
    <div class="table-wrap"><table>
      <thead><tr><th>Year</th>${d.projection.map((y) => `<th>Y${y.year}</th>`).join("")}</tr></thead>
      <tbody>
        ${[["Revenue", "revenue"], ["EBITDA", "ebitda"], ["Capex", "capex"], ["ΔNWC", "change_in_nwc"], ["Free cash flow", "fcf"], ["Present value", "pv"]]
          .map(([l, k]) => `<tr class="${k === "fcf" ? "total" : ""}"><td>${l}</td>${d.projection.map((y) => `<td>${millions(y[k])}</td>`).join("")}</tr>`).join("")}
      </tbody></table></div>
    <p class="legend-note">Year 1 is the closing year (not discounted). Range: conservative and aggressive move near-term growth with WACC and terminal growth with terminal WACC, blended by the terminal value's share.${r.notes?.length ? " " + esc(r.notes.filter((n) => !n.startsWith("range =")).join(" ")) : ""}</p>`;
  $("val-body").insertBefore(card, $("val-body").children[1] || null);
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
