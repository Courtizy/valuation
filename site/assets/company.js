import { areaChart, groupedBarChart, lineChart, spreadChart } from "./charts.js";
import { NA, days, esc, estLabel, fin, label, millions, money, monthYear, num, pct, periodLabel, price, times, titleCase } from "./format.js";
import { renderSector } from "./sector.js";
import { $, state } from "./state.js";
import { acct, cellOf, finRow } from "./tables.js";

// ---------------------------------------------------------------- company

// Statement layout. sign -1 = shown as a deduction (reported as a positive cost).
// A "head" row is dropped when none of the rows under it has data.
export const STATEMENTS = [
  ["Income Statement", [
    { id: "revenue", label: "Revenue", kind: "key" },
    { id: "cost_of_goods_and_services_sold", label: "Cost of Revenue", indent: 1, sign: -1 },
    { id: "gross_profit", label: "Gross Profit", kind: "sub" },
    { head: "Operating Expenses", indent: 1 },
    { id: "research_and_development_expenses", label: "Research & Development", indent: 2, sign: -1 },
    { id: "selling_general_and_admin_expenses", label: "Selling, General & Administrative", indent: 2, sign: -1 },
    { id: "operating_income_loss", label: "Operating Income", kind: "sub" },
    { id: "interest_expense", label: "Interest Expense", indent: 1, sign: -1 },
    { id: "interest_income", label: "Interest Income", indent: 1 },
    { id: "pretax_income_loss", label: "Income Before Taxes", kind: "sub" },
    { id: "income_taxes", label: "Income Tax Expense", indent: 1, sign: -1 },
    { id: "net_income", label: "Net Income", kind: "grand" },
    { head: "Memo", indent: 0 },
    { id: "depreciation_amortization_cf", label: "Depreciation & Amortization", indent: 1, kind: "memo" },
    { id: "ebitda", label: "EBITDA", indent: 1, kind: "memo" },
  ]],
  ["Balance Sheet", [
    { head: "Assets", indent: 0 },
    { id: "cash_and_marketable_securities", label: "Cash & Marketable Securities", indent: 1 },
    { id: "trade_receivables", label: "Accounts Receivable", indent: 1 },
    { id: "inventories", label: "Inventories", indent: 1 },
    { id: "current_assets_total", label: "Total Current Assets", indent: 1, kind: "sub" },
    { id: "plant_property_equipment_net", label: "Property, Plant & Equipment, Net", indent: 1 },
    { id: "goodwill", label: "Goodwill", indent: 1 },
    { id: "assets", label: "Total Assets", kind: "grand" },
    { head: "Liabilities & Equity", indent: 0 },
    { id: "trade_payables", label: "Accounts Payable", indent: 1 },
    { id: "short_term_debt", label: "Short-Term Debt", indent: 1 },
    { id: "current_liabilities_total", label: "Total Current Liabilities", indent: 1, kind: "sub" },
    { id: "long_term_debt", label: "Long-Term Debt", indent: 1 },
    { id: "liabilities", label: "Total Liabilities", kind: "sub" },
    { id: "all_equity_balance", label: "Total Equity", indent: 1 },
    { id: "liabilities_and_equity", label: "Total Liabilities & Equity", kind: "grand" },
    { head: "Memo", indent: 0 },
    { id: "total_debt", label: "Total Debt", indent: 1, kind: "memo" },
    { id: "net_debt", label: "Net Debt", indent: 1, kind: "memo" },
  ]],
  ["Cash Flow", [
    { id: "operating_cash_flow", label: "Cash from Operations (CFO)", kind: "key" },
    { id: "capital_expenses", label: "Capital Expenditures", indent: 1, sign: -1 },
    { id: "free_cash_flow", label: "FCF (CFO − Capex)", kind: "sub" },
    { head: "Returned to Shareholders", indent: 1 },
    { id: "stock_repurchased", label: "Share Repurchases", indent: 2, sign: -1 },
    { id: "common_dividends_paid", label: "Dividends Paid", indent: 2, sign: -1 },
  ]],
  ["Per Share", [
    { id: "eps_diluted", label: "Diluted EPS ($)", digits: 2, scale: 1 },
    { id: "shares_fully_diluted_average", label: "Diluted Shares (M)", indent: 0 },
  ]],
];
export const DERIVED_METHODS = new Set(["q4_derived", "ytd_derived", "summed_4q_with_derived"]);

export function periodsFor(view) {
  const all = state.detail.views[view] || [];
  return all.slice(-(view === "annual" ? 5 : 8));
}

export function renderCompany() {
  if (!state.detail || state.tab !== "company") return;
  renderTiles();
  renderRevenueChart();
  renderReturnsChart();
  renderMarginChart();
  renderCashChart();
  renderStatements();
  renderRatios();
  renderSector();
}

export function latestAnalysis() {
  const a = state.detail.analysis;
  return (a.ttm.length ? a.ttm : a.annual).at(-1);
}

/** Analysis periods carry "FY2024" / "TTM 2026-06-30" labels; show them as 2024 / LTM Jun 2026. */
export const analysisLabel = (a) => (a.label.startsWith("TTM") ? `LTM ${monthYear(a.end)}` : a.label.slice(-4));

// ---- projection: which estimate years are shown -------------------------------------
// Statements show Years 1–4, then Year 5 and Year 10 (indexes into the projected rows);
// charts plot every year. Years count from the base period: on a fiscal base Year 1 is
// the fiscal year in progress (FY+1E), which is also the DCF's undiscounted closing year.
export const SHOWN_YEARS = [1, 2, 3, 4, 5, 10];

// Projected years: the DCF's projection when a DCF has run (the numbers behind the
// valuation), otherwise the trend case calculated in L1 from history.
export const PROJ_MAP = { revenue: "revenue", cost_of_goods_and_services_sold: "cogs", gross_profit: "gross_profit",
  research_and_development_expenses: "rnd", selling_general_and_admin_expenses: "sga", operating_income_loss: "ebit",
  depreciation_amortization_cf: "depreciation", ebitda: "ebitda", pretax_income_loss: "ebt", income_taxes: "income_taxes",
  net_income: "net_income", capital_expenses: "capex" };

export function projection() {
  const d = state.dcf?.details;
  if (d?.statements?.length) {
    return { kind: "dcf", rows: d.statements.slice(0, 10), base: d.base_period, name: "DCF Case",
      note: `Estimates: DCF case from inputs/assumptions/${state.company.ticker}/dcf.json (Year 1 is the undiscounted closing year).` };
  }
  const p = state.detail.projection;
  if (!p?.years?.length) return null;
  const a = p.assumptions;
  return { kind: "trend", rows: p.years, base: p.base_period, name: "Trend Case",
    note: `Estimates: trend case from the filings, no inputs. Revenue growth starts at the ${pct(a.revenue_growth_start)} historical CAGR and fades to ${pct(a.terminal_growth)} by Year 10; costs, D&A and capex stay at base-year ratios; working capital ${pct(a.nwc_to_sales_change)} of new sales; tax ${pct(a.tax_rate)}. Run a DCF to replace it with your own case.` };
}

/** The projection base period's values (the last fiscal year on a fiscal base). */
function baseValues(proj) {
  const v = state.detail.views;
  const pool = proj.base?.kind === "fiscal" ? v.annual : v.ttm;
  return (pool.find((p) => p.end === proj.base.end) || pool.at(-1))?.values || {};
}

const cagr = (from, to, n) => (fin(from) && fin(to) && from > 0 && to > 0 ? (to / from) ** (1 / n) - 1 : null);

export function renderTiles() {
  const v = state.detail.views;
  const series = v.ttm.length ? v.ttm : v.annual;
  const cur = series.at(-1), prior = series.find((p) => Math.abs(new Date(cur.end) - new Date(p.end) - 365 * 864e5) < 20 * 864e5);
  const an = latestAnalysis();
  const val = cur?.values || {};
  const tag = periodLabel(cur);
  const growth = prior && fin(prior.values.revenue) ? val.revenue / prior.values.revenue - 1 : null;
  const opm = fin(val.operating_income_loss) && val.revenue ? val.operating_income_loss / val.revenue : null;
  const tiles = [
    { label: "Revenue", tag, value: money(val.revenue),
      delta: fin(growth) ? `${growth >= 0 ? "▲" : "▼"} ${pct(Math.abs(growth))} Year over Year` : "", dir: growth },
    { label: "Operating Margin", tag, value: pct(opm) },
    { label: "RNOA", tag, value: pct(an?.ratios.reformulated.avg?.rnoa), delta: "On average net operating assets", neutral: true },
    { label: "FCF (CFO − Capex)", tag, value: money(val.free_cash_flow) },
    { label: "Net Debt", tag, value: money(val.net_debt) },
  ];
  const proj = projection();
  if (proj) {
    const b = baseValues(proj).revenue, r = proj.rows;
    const c5 = cagr(b, r.at(4)?.revenue, 5), c10 = r.length >= 10 ? cagr(b, r.at(9).revenue, 10) : null;
    tiles.splice(1, 0, { label: "Revenue CAGR", tag: "5Y / 10Y", value: `${pct(c5)} / ${pct(c10)}`,
      delta: `${proj.name} · ${money(r.at(Math.min(9, r.length - 1)).revenue)} in ${estLabel(proj.base, Math.min(10, r.length))}`, neutral: true });
  }
  $("tiles").innerHTML = tiles.map((t) => `<div class="tile"><div class="label">${esc(t.label)}${t.tag ? `<span class="tile-tag">${esc(t.tag)}</span>` : ""}</div>
    <div class="value">${t.value}</div>${t.delta ? `<div class="delta ${t.neutral ? "" : t.dir >= 0 ? "up" : "down"}">${esc(t.delta)}</div>` : ""}</div>`).join("");
}

// Revenue: area for reported years, dashed line for all ten projected years, and a
// Bear–Bull band = projected growth ± the DCF's growth step (1 pt for the trend case).
export function renderRevenueChart() {
  const view = state.view;
  const ps = chartPeriods(view);
  const proj = view === "annual" ? projection() : null;
  const est = proj ? proj.rows : [];
  const step = (proj?.kind === "dcf" && state.dcf?.details?.scenarios?.steps?.growth) || 0.01;
  const growth = ps.map((p) => { const pr = priorFor(p, view); return pr?.revenue && fin(p.values.revenue) ? p.values.revenue / pr.revenue - 1 : null; });
  const low = ps.map(() => null), high = ps.map(() => null);
  let prev = proj ? baseValues(proj).revenue : null, l = prev, h = prev;
  for (const r of est) {
    const g = prev ? r.revenue / prev - 1 : null;
    growth.push(g); l *= 1 + g - step; h *= 1 + g + step; low.push(l); high.push(h); prev = r.revenue;
  }
  const cats = ps.map(periodLabel).concat(est.map((_, i) => estLabel(proj.base, i + 1)));
  $("rev-title").textContent = view === "ttm" ? "Revenue, Last Twelve Months" : view === "quarterly" ? "Revenue by Quarter" : "Revenue";
  $("rev-sub").textContent = cats.length ? `${cats[0]} to ${cats.at(-1)}${est.length ? ` · dashed = ${proj.name}, band = growth ±${(step * 100).toFixed(0)} pt` : ""}` : "";
  areaChart($("rev-chart"), {
    categories: cats,
    values: ps.map((p) => p.values.revenue).concat(est.map((r) => r.revenue)),
    estimate: ps.map(() => false).concat(est.map(() => true)),
    low, high, growth, format: money, pctFormat: (x) => pct(x), label: "Revenue", bandLabel: "Bear – Bull" });
}

// RNOA and ROCE with the gap shaded: ROCE − RNOA = FLEV × (RNOA − NBC), the financing
// effect. Green where leverage adds to shareholder returns, red where it subtracts.
// WACC (from the DCF, when one has run) is the reference RNOA has to beat.
// Annual: fiscal-year returns. Quarterly and LTM: rolling twelve-month returns at each quarter end
// (a single quarter's return isn't comparable), labeled by quarter or by LTM end month.
export function renderReturnsChart() {
  const view = state.view, rolling = view !== "annual";
  const an = (rolling ? state.detail.analysis.ttm.slice(-12) : state.detail.analysis.annual).filter((a) => a.ratios.reformulated.avg);
  const qByEnd = new Map((state.detail.views.quarterly || []).map((p) => [p.end, p]));
  const lab = (x) => (view === "quarterly" && qByEnd.has(x.end) ? periodLabel(qByEnd.get(x.end)) : analysisLabel(x));
  $("ret-sub").textContent = rolling ? "Average Balances, Rolling LTM" : "Average Balances, Annual";
  const a = { name: "RNOA", color: "var(--series-1)", values: an.map((x) => x.ratios.reformulated.avg.rnoa) };
  const b = { name: "ROCE", color: "var(--series-2)", values: an.map((x) => x.ratios.reformulated.avg.roce) };
  const wacc = state.dcf?.details?.rates?.wacc;
  $("ret-legend").innerHTML = [a, b].map((x) => `<span><span class="key" style="background:${x.color}"></span>${x.name}</span>`).join("")
    + (fin(wacc) ? `<span><span class="key" style="background:var(--ink-2)"></span>WACC (DCF)</span>` : "")
    + `<span><span class="swatch pos"></span>Leverage Adds</span><span><span class="swatch neg"></span>Leverage Subtracts</span>`;
  spreadChart($("ret-chart"), { categories: an.map(lab), a, b, format: pct, label: "RNOA and ROCE with the financing spread",
    ref: fin(wacc) ? { value: wacc, label: "WACC" } : null, spreadLabel: "Financing effect (ROCE − RNOA)" });
}

// Margins over the periods in view; in the Annual view, every projected year too (dashed).
export function renderMarginChart() {
  const view = state.view, ann = chartPeriods(view), proj = view === "annual" ? projection() : null;
  const est = proj ? proj.rows : [];
  const m = (num, den) => (fin(num) && den ? num / den : null);
  const cats = ann.map(periodLabel).concat(est.map((_, i) => estLabel(proj.base, i + 1)));
  const series = [
    ["Gross Margin", "var(--series-1)", (v) => m(v.gross_profit, v.revenue), (r) => m(r.gross_profit, r.revenue)],
    ["EBITDA Margin", "var(--series-2)", (v) => m(v.ebitda, v.revenue), (r) => m(r.ebitda, r.revenue)],
    ["Operating Margin", "var(--series-3)", (v) => m(v.operating_income_loss, v.revenue), (r) => m(r.ebit, r.revenue)],
  ].map(([name, color, fa, fe]) => ({ name, color, values: ann.map((p) => fa(p.values)).concat(est.map(fe)) }));
  $("mar-legend").innerHTML = series.map((x) => `<span><span class="key" style="background:${x.color}"></span>${x.name}</span>`).join("");
  $("mar-sub").textContent = cats.length ? `${cats[0]} to ${cats.at(-1)}${est.length ? ` · dashed = ${proj.name}` : ""}` : "";
  lineChart($("mar-chart"), { categories: cats, series, format: pct, label: "Margins, reported and projected", splitAt: ann.length });
}

// Net income against FCF (CFO − Capex): cash conversion = FCF / net income.
export function renderCashChart() {
  const ann = chartPeriods(state.view);
  const ni = ann.map((p) => p.values.net_income), fcf = ann.map((p) => p.values.free_cash_flow);
  const series = [{ name: "Net Income", color: "var(--series-1)", values: ni }, { name: "FCF (CFO − Capex)", color: "var(--series-3)", values: fcf }];
  $("cash-legend").innerHTML = series.map((x) => `<span><span class="key" style="background:${x.color}"></span>${x.name}</span>`).join("");
  groupedBarChart($("cash-chart"), { categories: ann.map(periodLabel), series, format: money, label: "Net income and free cash flow",
    tipExtra: (i) => ({ label: "Cash Conversion", value: fin(ni[i]) && ni[i] > 0 && fin(fcf[i]) ? pct(fcf[i] / ni[i]) : NA }) });
}

/** Reported periods a chart shows: six fiscal years, or the last twelve quarters / LTM points. */
export function chartPeriods(view) {
  return (state.detail.views[view] || []).slice(view === "annual" ? -6 : -12);
}

export function priorFor(p, view) {
  const lag = view === "quarterly" || view === "ttm" ? 4 : 1;
  const all = state.detail.views[view];
  const idx = all.indexOf(p);
  return idx - lag >= 0 ? all[idx - lag].values : null;
}

export const GROWTH_ROWS = [
  ["Revenue Growth", (v, prev) => (prev?.revenue && fin(v.revenue) ? v.revenue / prev.revenue - 1 : null)],
  ["Gross Margin", (v) => (v.revenue && fin(v.gross_profit) ? v.gross_profit / v.revenue : null)],
  ["EBITDA Margin", (v) => (v.revenue && fin(v.ebitda) ? v.ebitda / v.revenue : null)],
  ["Operating Margin", (v) => (v.revenue && fin(v.operating_income_loss) ? v.operating_income_loss / v.revenue : null)],
  ["Net Margin", (v) => (v.revenue && fin(v.net_income) ? v.net_income / v.revenue : null)],
];

// Annual view: up to five reported fiscal years, an LTM reference column when it is
// newer than the last fiscal year, then Years 1–4, Year 5 and Year 10 (shaded).
export function renderStatements() {
  const view = state.view, ps = periodsFor(view);
  const t = $("stmt-table");
  if (!ps.length) { t.innerHTML = `<tbody><tr><td class="muted">No ${view} periods.</td></tr></tbody>`; return; }
  const proj = view === "annual" ? projection() : null;
  const ltm = view === "annual" ? state.detail.views.ttm.at(-1) : null;
  const cols = ps.map((p) => ({ p, view })).concat(ltm && ltm.end > ps.at(-1).end ? [{ p: ltm, view: "ttm", ref: true }] : []);
  // every projected year in concept terms (growth needs the year before), then the shown subset
  const all = proj ? proj.rows.map((r) => Object.fromEntries(Object.entries(PROJ_MAP).map(([cid, k]) => [cid, r[k]]))) : [];
  const shown = proj ? SHOWN_YEARS.filter((y) => y <= all.length) : [];
  const est = shown.map((y) => ({ y, e: all[y - 1], prev: y > 1 ? all[y - 2] : baseValues(proj), fcf: proj.rows[y - 1].fcf }));
  const n = cols.length + est.length;
  const yearTag = (y) => (y === 5 || y === 10 ? `<span class="th-sub">Year ${y}</span>` : "");
  let html = `<thead><tr><th scope="col">$ Millions</th>${cols.map(({ p, ref }) =>
      `<th scope="col" class="${ref ? "ref" : ""}" title="${esc(p.start)} to ${esc(p.end)}${ref ? " · latest twelve months, for reference" : ""}">${esc(periodLabel(p))}</th>`).join("")}
    ${est.map(({ y }) => `<th scope="col" class="est${y === 5 || y === 10 ? " milestone" : ""}" title="projected Year ${y}">${estLabel(proj.base, y)}${yearTag(y)}</th>`).join("")}</tr></thead><tbody>`;

  const section = (name) => `<tr class="group"><td colspan="${n + 1}">${esc(name)}</td></tr>`;
  html += section("Growth & Margins");
  for (const [name, f] of GROWTH_ROWS) {
    const cells = cols.map(({ p, view: vw, ref }) => cellOf(pct(f(p.values, priorFor(p, vw))), ref ? "ref" : ""))
      .concat(est.map(({ e, prev }) => cellOf(pct(f(e, prev)), "est")));
    html += finRow(name, cells, { indent: 1, kind: name === "Revenue Growth" ? "key" : "item" });
  }
  for (const [group, spec] of STATEMENTS) {
    const has = (r) => r.id && (cols.some(({ p }) => fin(p.values[r.id])) || est.some(({ e }) => fin(e[r.id])));
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
      const cells = cols.map(({ p, ref }) => {
        const v = p.values[r.id], m = p.methods[r.id];
        const mark = m === "yahoo_backup" ? `<span class="mark" title="not in the filings: filled from Yahoo fundamentals">y</span>`
          : DERIVED_METHODS.has(m) ? `<span class="mark" title="${esc(m.replace(/_/g, " "))}">d</span>` : "";
        return fin(v) ? { html: acct(sg * v, o) + mark, cls: ref ? "ref" : "" } : cellOf(NA, ref ? "ref" : "");
      }).concat(est.map(({ e }) => (fin(e[r.id]) ? { html: acct(sg * e[r.id], o), cls: "est" } : cellOf(NA, "est"))));
      html += finRow(esc(r.label || label(r.id)), cells, { kind: r.kind, indent: r.indent, title: label(r.id) });
    }
    if (group === "Cash Flow" && est.length) {
      html += finRow("Unlevered FCF (Projected)", cols.map(({ ref }) => cellOf(NA, ref ? "ref" : "")).concat(
        est.map(({ fcf }) => ({ html: acct(fcf), cls: "est" }))), { kind: "memo", indent: 1 });
    }
  }
  t.innerHTML = html + "</tbody>";
  $("stmt-full").innerHTML = state.run.full ? `This page shows the latest periods. <a href="data/${esc(state.run.full)}" download>Download the full history (JSON)</a>.` : "";
  $("stmt-note").textContent = proj ? `${proj.note} Years 6–9 are in the chart above and the DCF table.` : view === "annual" ? "" : "Estimates are shown in the Annual view.";
}

export const $M = (v, o) => acct(v, o);   // $ millions, accounting style

export const RATIO_ROWS = {
  reformulated: {
    note: "Operating vs financial split. NOPAT = net income + after-tax net interest. ROCE = RNOA + FLEV × (RNOA − NBC).",
    rows: [
      ["group", "Margins"],
      ["Operating Margin (NOPM)", (a) => a.ratios.reformulated.nopm, pct, { kind: "key" }],
      ["Core NOPM", (a) => a.ratios.reformulated.core_nopm, pct],
      ["group", "Average Balances"],
      ["NOA Turnover (NOAT)", (a) => a.ratios.reformulated.avg?.noat, times],
      ["RNOA", (a) => a.ratios.reformulated.avg?.rnoa, pct, { kind: "key" }],
      ["ROCE", (a) => a.ratios.reformulated.avg?.roce, pct, { kind: "key" }],
      ["FLEV", (a) => a.ratios.reformulated.avg?.flev, num],
      ["NBC", (a) => a.ratios.reformulated.avg?.nbc, pct],
      ["Spread (RNOA − NBC)", (a) => a.ratios.reformulated.avg?.spread, pct],
      ["OLLEV", (a) => a.ratios.reformulated.avg?.ollev, num],
      ["ROOA", (a) => a.ratios.reformulated.avg?.rooa, pct],
      ["OLSPREAD", (a) => a.ratios.reformulated.avg?.olspread, pct],
      ["group", "Beginning Balances"],
      ["NOAT", (a) => a.ratios.reformulated.beg?.noat, times],
      ["RNOA", (a) => a.ratios.reformulated.beg?.rnoa, pct],
      ["ROCE", (a) => a.ratios.reformulated.beg?.roce, pct],
      ["FLEV", (a) => a.ratios.reformulated.beg?.flev, num],
      ["group", "Balance Sheet ($M)"],
      ["Net Operating Assets", (a) => a.reformulated_balance_sheet.noa, $M, {}],
      ["Net Nonoperating Obligations", (a) => a.reformulated_balance_sheet.nno, $M, { sign: -1 }],
      ["Common Equity incl. NCI", (a) => a.reformulated_balance_sheet.cse_incl_nci, $M, { kind: "grand", indent: 0 }],
      ["group", "Free Cash Flow ($M)"],
      ["NOPAT", (a) => a.reformulated_income_statement.nopat, $M, {}],
      ["FCF to Firm (NOPAT − ΔNOA)", (a) => a.ratios.reformulated.fcf, $M, { kind: "key" }],
    ],
  },
  managerial: {
    note: "Managerial balance sheet: cash + working-capital requirement + fixed assets = capital employed.",
    rows: [
      ["group", "Managerial Balance Sheet ($M)"],
      ["Cash", (a) => a.managerial_balance_sheet.cash, $M, {}],
      ["Working-Capital Requirement (WCR)", (a) => a.managerial_balance_sheet.wcr, $M],
      ["Fixed Assets", (a) => a.managerial_balance_sheet.fixed_assets, $M],
      ["Invested Capital", (a) => a.managerial_balance_sheet.invested_capital, $M, { kind: "grand", indent: 0 }],
      ["group", "Liquidity & Operating Cycle"],
      ["Net Long-Term Financing (NLF)", (a) => a.ratios.managerial.nlf, $M],
      ["Net Short-Term Financing (NSF)", (a) => a.ratios.managerial.nsf, $M],
      ["Liquidity Ratio (NLF / WCR)", (a) => a.ratios.managerial.liquidity_ratio, num],
      ["WCR / Sales", (a) => a.ratios.managerial.wcr_to_sales, pct],
      ["Collection Period", (a) => a.ratios.managerial.collection_period_days, days],
      ["Days Inventory", (a) => a.ratios.managerial.days_inventory, days],
      ["Inventory Turnover", (a) => a.ratios.managerial.inventory_turnover, times],
      ["Payment Period", (a) => a.ratios.managerial.payment_period_days, days],
      ["Current Ratio", (a) => a.ratios.managerial.current_ratio, num],
      ["Acid Test", (a) => a.ratios.managerial.acid_test, num],
      ["group", "Free Cash Flow ($M)"],
      ["NOPLAT", (a) => a.fcf_managerial.noplat, $M, {}],
      ["Plus: Depreciation", (a) => a.fcf_managerial.depreciation, $M],
      ["Less: Capex (ΔFA + Depreciation)", (a) => a.fcf_managerial.capex_from_balance_sheet, $M, { sign: -1 }],
      ["Less: Increase in WCR", (a) => a.fcf_managerial.change_in_wcr, $M, { sign: -1 }],
      ["Managerial FCF", (a) => a.fcf_managerial.fcf, $M, { kind: "grand", indent: 0 }],
    ],
  },
  traditional: {
    note: "Profit margin adds back after-tax interest expense. ROA = margin × turnover.",
    rows: [
      ["group", "Return on Assets"],
      ["Profit Margin", (a) => a.ratios.traditional.profit_margin, pct],
      ["× Asset Turnover", (a) => a.ratios.traditional.asset_turnover, times],
      ["ROA", (a) => a.ratios.traditional.roa, pct, { kind: "sub", indent: 0 }],
      ["group", "Return on Equity"],
      ["Leverage (Assets / Equity)", (a) => a.ratios.traditional.leverage, times],
      ["ROE", (a) => a.ratios.traditional.roe, pct, { kind: "key", indent: 0 }],
    ],
  },
  risk: {
    note: "Altman Z public needs a market price (not published on this site); the private-firm form uses book equity. Zones: Z < 1.2 distress, < 2.9 grey.",
    rows: [
      ["group", "Distress"],
      ["Altman Z (Private Form)", (a) => a.ratios.risk.altman_z.private, num, { kind: "key" }],
      ["Zone", (a) => a.ratios.risk.altman_z.private_zone, (z) => (z ? titleCase(z) : NA)],
      ["Altman Z (Public Form)", (a) => a.ratios.risk.altman_z.public, num],
      ["group", "Credit Metrics"],
      ["EBIT / Interest", (a) => a.ratios.risk.credit.ebit_to_interest, times],
      ["Debt / EBITDA", (a) => a.ratios.risk.credit.debt_to_ebitda, times],
      ["FFO / Debt", (a) => a.ratios.risk.credit.ffo_to_debt, pct],
      ["Return on Capital", (a) => a.ratios.risk.credit.return_on_capital, pct],
      ["EBIT Margin", (a) => a.ratios.risk.credit.ebit_margin, pct],
      ["Debt / Book Capital", (a) => a.ratios.risk.credit.debt_to_book_capital, pct],
      ["Capex / Depreciation", (a) => a.ratios.risk.credit.capex_to_depreciation, times],
    ],
  },
  signals: {
    note: "Positive signals favor future earnings; negative ones flag possible quality issues. Year-over-year.",
    rows: [
      ["group", "Earnings Signals"],
      ["Gross Margin Signal", (a) => a.ratios.signals.gross_margin_signal, pct],
      ["SG&A Signal", (a) => a.ratios.signals.sga_signal, pct],
      ["R&D Signal", (a) => a.ratios.signals.rnd_signal, pct],
      ["Receivables Signal", (a) => a.ratios.signals.receivables_signal, pct],
      ["Inventory Signal", (a) => a.ratios.signals.inventory_signal, pct],
      ["group", "Diagnostics"],
      ["CFO / Operating Income", (a) => a.ratios.signals.cfo_to_operating_income, num],
      ["CFO / Average NOA", (a) => a.ratios.signals.cfo_to_avg_noa, pct],
      ["Accruals / ΔSales", (a) => a.ratios.signals.accruals_to_sales_change, num],
      ["Sales / Receivables", (a) => a.ratios.signals.sales_to_receivables, times],
      ["Depreciation / Capex", (a) => a.ratios.signals.depreciation_to_capex, num],
    ],
  },
};

export function renderRatios() {
  const an = state.detail.analysis;
  const cols = [...an.annual.slice(-5)];
  if (an.ttm.length && an.ttm.at(-1).end > (cols.at(-1)?.end || "")) cols.push(an.ttm.at(-1));
  const spec = RATIO_ROWS[state.fw];
  const head = cols.map((a) => `<th scope="col">${esc(analysisLabel(a))}</th>`).join("");
  let html = `<thead><tr><th scope="col">${esc(titleCase(state.fw))}</th>${head}</tr></thead><tbody>`;
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
  $("ratio-note").textContent = `${spec.note} Marginal tax rate ${pct(state.detail.classification.marginal_tax_rate)}. Source: SEC filings via XBRL.`;
}
