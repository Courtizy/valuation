import { barListChart, scatterChart } from "./charts.js";
import { NA, esc, fin, label, money, mult, pct, periodLabel, sentence, sourceLine, times, titleCase } from "./format.js";
import { dispatchPipeline, setStatus } from "./github.js";
import { selectCompany } from "./main.js";
import { $, getJSON, state, store } from "./state.js";
import { renderValuation, upClass } from "./valuation.js";

// ---------------------------------------------------------------- sector
// A sector screen (L1 sector.json) gives every member the same few figures from
// SEC frames. Company detail shows this company against the sector (benchmarks)
// and the sector itself (charts and a table); Valuation uses it to pick comps peers.

// [key, label, format, unit, polarity]: polarity +1 = higher is favourable (green above
// the median), -1 = higher is unfavourable (leverage), 0 = neither (capex intensity).
export const SEC_METRICS = [
  ["revenue_growth", "Revenue Growth (1Y)", pct, "pts", 1],
  ["revenue_cagr", "Revenue CAGR (3Y)", pct, "pts", 1],
  ["gross_margin", "Gross Margin", pct, "pts", 1],
  ["operating_margin", "Operating Margin", pct, "pts", 1],
  ["ebitda_margin", "EBITDA Margin", pct, "pts", 1],
  ["net_margin", "Net Margin", pct, "pts", 1],
  ["fcf_margin", "FCF Margin", pct, "pts", 1],
  ["capex_to_sales", "Capex / Sales", pct, "pts", 0],
  ["roa", "Return on Assets", pct, "pts", 1],
  ["roe", "Return on Equity", pct, "pts", 1],
  ["debt_to_ebitda", "Debt / EBITDA", mult, "x", -1],
  ["liabilities_to_assets", "Liabilities / Assets", pct, "pts", -1],
];

// ---- levels: the same screen re-cut at Sector / Industry Group / Industry -----------------
/** Q1 / median / Q3, inclusive method (matches Python's statistics.quantiles). */
export function quartiles(values) {
  const xs = values.filter(fin).sort((a, b) => a - b);
  if (!xs.length) return { q1: null, median: null, q3: null, n: 0 };
  const q = (p) => { const i = (xs.length - 1) * p, lo = Math.floor(i); return xs[lo] + (xs[Math.ceil(i)] - xs[lo]) * (i - lo); };
  return { q1: q(0.25), median: q(0.5), q3: q(0.75), n: xs.length };
}

/** This company's place in the taxonomy: its sector-screen row, else its published card. */
function myClass() {
  return sectorMe()?.classification || (state.companies?.companies || []).find((c) => c.ticker === state.company.ticker)?.classification || null;
}

function taxName(level, id) {
  const T = state.taxonomy;
  if (!T || !id) return id;
  for (const s of T.sectors) {
    if (level === "sector" && s.id === id) return s.name;
    for (const g of s.groups) {
      if (level === "group" && g.id === id) return g.name;
      for (const i of g.industries) if (level === "industry" && i.id === id) return i.name;
    }
  }
  return id;
}

/** Levels on offer for this screen: [{level, label, rows}], widest first. */
export function levelOptions() {
  const S = state.sector, c = myClass();
  if (!S) return [];
  const opts = [];
  if (S.kind !== "sector") opts.push({ level: "all", label: S.label, rows: S.companies });
  if (c) {
    for (const lv of ["sector", "group", "industry"]) {
      const rows = S.companies.filter((r) => r.classification?.[lv] === c[lv]);
      if (rows.length && !(lv === "sector" && S.kind !== "sector" && rows.length === S.companies.length && opts.length)) {
        opts.push({ level: lv, label: taxName(lv, c[lv]), rows });
      }
    }
  }
  if (!opts.length) opts.push({ level: "all", label: S.label, rows: S.companies });
  return opts;
}

/** Rows at the chosen level (state[key] = level name); falls back to the widest. */
export function levelRows(key = "secLevel") {
  const opts = levelOptions();
  return opts.find((o) => o.level === state[key]) || opts[0] || { level: "all", label: "", rows: [] };
}

/** Breadcrumb of levels; each crumb is a button with its company count. */
export function levelBar(key = "secLevel") {
  const opts = levelOptions(), cur = levelRows(key);
  if (opts.length < 2) return `<span class="muted small">${esc(cur.label)} · ${cur.rows.length} companies</span>`;
  return `<nav class="crumbs" aria-label="Comparison level" data-key="${key}">${opts.map((o, i) =>
    `${i ? '<span class="crumb-sep">›</span>' : ""}<button type="button" data-level="${o.level}" aria-pressed="${o.level === cur.level}">${esc(o.label)} <span class="crumb-n">${o.rows.length}</span></button>`).join("")}</nav>`;
}

export function wireLevelBar(root, rerender) {
  root.querySelectorAll(".crumbs button").forEach((b) => b.onclick = () => {
    state[b.closest(".crumbs").dataset.key] = b.dataset.level;
    rerender();
  });
}

/** The company's own figures from its filings (latest fiscal year), on the screen's definitions. */
function ownFigures() {
  const ann = state.detail.views.annual, v = ann.at(-1)?.values || {}, pv = ann.at(-2)?.values || {}, v3 = ann.at(-4)?.values;
  const div = (a, b) => (fin(a) && fin(b) && b !== 0 ? a / b : null);
  const debt = fin(v.total_debt) ? v.total_debt : (v.short_term_debt || 0) + (v.long_term_debt || 0);
  return {
    revenue_growth: div(v.revenue, pv.revenue) != null ? v.revenue / pv.revenue - 1 : null,
    revenue_cagr: v3 && fin(v3.revenue) && v3.revenue > 0 && fin(v.revenue) ? (v.revenue / v3.revenue) ** (1 / 3) - 1 : null,
    gross_margin: div(v.gross_profit, v.revenue), operating_margin: div(v.operating_income_loss, v.revenue),
    ebitda_margin: div(v.ebitda, v.revenue), net_margin: div(v.net_income, v.revenue),
    fcf_margin: div(v.free_cash_flow, v.revenue), capex_to_sales: div(v.capital_expenses, v.revenue),
    roa: div(v.net_income, v.assets), roe: fin(v.all_equity_balance) && v.all_equity_balance > 0 ? div(v.net_income, v.all_equity_balance) : null,
    debt_to_ebitda: fin(v.ebitda) && v.ebitda > 0 ? debt / v.ebitda : null,
    liabilities_to_assets: div(v.liabilities, v.assets),
    period: ann.at(-1),
  };
}

export function sectorsFor(ticker) { return (state.index.sectors || []).filter((x) => x.members.includes(ticker)); }

export async function loadSector() {
  const t = state.company.ticker, list = sectorsFor(t);
  const want = store.get(`sector:${t}`);
  state.sectorMeta = list.find((x) => x.id === want) || list[0] || null;
  state.sector = state.sectorMeta ? await getJSON(`data/${state.sectorMeta.path}`).catch(() => null) : null;
}

export function sectorMe() { return state.sector?.companies.find((c) => c.ticker === state.company.ticker) || null; }

export function sectorPicker() {
  const list = sectorsFor(state.company.ticker);
  if (list.length < 2) return `<span class="muted small">${esc(state.sectorMeta.label)}</span>`;
  return `<select class="sector-pick" aria-label="Sector">${list.map((x) =>
    `<option value="${esc(x.id)}"${x.id === state.sectorMeta.id ? " selected" : ""}>${esc(x.label)} (${x.count})</option>`).join("")}</select>`;
}

export function wireSectorPicker(root) {
  root.querySelectorAll(".sector-pick").forEach((sel) => sel.onchange = async () => {
    store.set(`sector:${state.company.ticker}`, sel.value);
    await loadSector();
    renderSector();
    if (state.tab === "valuation") renderValuation();
  });
}

/** The taxonomy entry for a SIC code, client-side (same map the pipeline uses). */
export function classifySic(sic) {
  for (const s of state.taxonomy?.sectors || []) for (const g of s.groups) for (const i of g.industries)
    if (i.sic.includes(String(sic).padStart(4, "0"))) return { sector: s, group: g, industry: i };
  return null;
}

export function screenButtons() {
  const e = state.detail.entity || {}, t = state.company.ticker, c = e.sic ? classifySic(e.sic) : null;
  const what = c ? c.sector.name : "Its Sector";
  const path = c ? `<p class="muted small">${esc(t)} files under SIC ${esc(e.sic)}: ${esc(c.sector.name)} › ${esc(c.group.name)} › ${esc(c.industry.name)}.</p>` : "";
  return `${path}<div class="actions"><button type="button" class="primary" data-screen="${c ? `sector:${esc(c.sector.id)}` : `sic-of:${esc(t)}`}">Screen ${esc(what)}</button>
    <a href="#run" data-goto-run>Other Sector Options</a><span class="status" role="status"></span></div>`;
}

export function wireScreenButtons(root) {
  root.querySelectorAll("[data-screen]").forEach((b) => b.onclick = async () => {
    const st = root.querySelector(".status");
    st.className = "status"; st.textContent = "Starting…";
    try { setStatus(st, await dispatchPipeline({ sector: b.dataset.screen, as_of: new Date().toISOString().slice(0, 10) })); }
    catch (err) { setStatus(st, { ok: false, msg: err.message }); }
  });
  root.querySelectorAll("[data-goto-run]").forEach((a) => a.onclick = (ev) => {
    ev.preventDefault();
    document.querySelector('#r-mode [data-mode="sector"]').click();
    document.querySelector('.tab[data-tab="run"]').click();
  });
}

/** The merged Sector section: one picker and one level switch drive Relative Performance and the sector view. */
export function renderSector() {
  const pick = $("sector-pick-slot"), lv = $("sector-levels");
  if (!pick || !lv) return;
  const ready = !!(state.sector && sectorMe());
  pick.innerHTML = ready ? sectorPicker() : "";
  lv.innerHTML = ready ? levelBar("secLevel") : "";
  if (ready) { wireSectorPicker(pick); wireLevelBar(lv, renderSector); }
  renderBenchmarks();
  renderSectorCard();
}

export function renderBenchmarks() {
  const card = $("bench-card");
  if (!card) return;
  const me = sectorMe();
  if (!state.sector || !me) {
    card.innerHTML = `<h3>Relative Performance</h3>
      <p class="muted">No sector screen includes ${esc(state.company.ticker)} yet. Screening its sector pulls a few figures for every company
      in it from SEC data, so each ratio here can be read against the sector's quartiles.</p>${state.company.demo ? "" : screenButtons()}`;
    wireScreenButtons(card);
    return;
  }
  const lv = levelRows("secLevel"), rows = lv.rows, own = ownFigures();
  const body = SEC_METRICS.map(([k, name, f, unit, pol]) => {
    const b = quartiles(rows.map((c) => c[k])), v = fin(own[k]) ? own[k] : me[k];
    if (!fin(b.median)) return "";
    const xs = rows.map((c) => c[k]).concat(fin(v) ? [v] : []).filter(fin), lo = Math.min(...xs), hi = Math.max(...xs), span = hi - lo || 1;
    const at = (x) => `${(((Math.min(Math.max(x, lo), hi) - lo) / span) * 100).toFixed(1)}%`;
    const d = fin(v) ? v - b.median : null;
    const dTxt = !fin(d) ? NA : unit === "pts" ? (Math.abs(d) < 0.0005 ? "0.0 pts" : `${d >= 0 ? "+" : "−"}${Math.abs(d * 100).toFixed(1)} pts`)
      : (Math.abs(d) < 0.05 ? "0.0x" : `${d >= 0 ? "+" : "−"}${Math.abs(d).toFixed(1)}x`);
    const tiny = !fin(d) || (unit === "pts" ? Math.abs(d) < 0.0005 : Math.abs(d) < 0.05);
    const tone = tiny || !pol ? "" : d * pol > 0 ? "up" : "down";
    return `<tr><td>${esc(name)}</td><td>${f(b.q1)}</td><td>${f(b.median)}</td><td>${f(b.q3)}</td><td class="strong">${f(v)}</td>
      <td class="${tone}">${dTxt}</td>
      <td class="posbar-cell"><div class="posbar" title="range ${f(lo)} to ${f(hi)}">
        <span class="rng" style="left:${at(b.q1)};width:calc(${at(b.q3)} - ${at(b.q1)})"></span><span class="med" style="left:${at(b.median)}"></span>
        ${fin(v) ? `<span class="me" style="left:${at(v)}"></span>` : ""}</div></td></tr>`;
  }).join("");
  card.innerHTML = `<h3>Relative Performance</h3>
    <div class="table-wrap"><table class="list bench"><thead><tr><th>Metric</th><th>Q1</th><th>Median</th><th>Q3</th>
      <th>${esc(state.company.ticker)} <span class="th-sub">${esc(own.period ? periodLabel(own.period) : "")}</span></th><th>vs. Median</th><th class="posbar-cell">Position <span class="muted small">bar = Q1–Q3 · line = median · dot = ${esc(state.company.ticker)}</span></th></tr></thead>
      <tbody>${body}</tbody></table></div>
    <p class="legend-note">${rows.length} companies (${esc(lv.label)}) · calendar ${state.sector.year} · screened ${esc(state.sectorMeta.as_of)}.
      ${esc(state.company.ticker)}'s figures come from its own filings; the sector's from SEC frames by calendar year. Green and red mark favourable and unfavourable gaps; capex intensity is neither.</p>
`;
}

export const SEC_COLS = [
  ["ticker", "Company"], ["revenue", "Revenue"], ["revenue_growth", "Growth"], ["revenue_cagr", "3Y CAGR"],
  ["gross_margin", "Gross Margin"], ["operating_margin", "Op. Margin"], ["fcf_margin", "FCF Margin"], ["roe", "ROE"],
  ["debt_to_ebitda", "Debt/EBITDA"], ["industry", "Industry"], ["stage", "Stage"], ["detail", "Detail"],
];

export function inIndex(t) { return state.index.companies.some((c) => c.ticker === t); }

export function renderSectorCard() {
  const card = $("sector-card");
  if (!card) return;
  if (!state.sector || !sectorMe()) { card.hidden = true; return; }
  card.hidden = false;
  const S = state.sector, me = state.company.ticker, demo = !!S.demo;
  const lv = levelRows("secLevel"), rows = lv.rows;
  const medX = quartiles(rows.map((c) => c.revenue_cagr)).median, medY = quartiles(rows.map((c) => c.operating_margin)).median;
  card.innerHTML = `<h3>Companies</h3>
    <div class="grid-2">
      <div><h4>Growth & Profitability</h4><div id="sec-scatter"></div></div>
      <div><h4>Revenue, Latest Year</h4><div id="sec-bars"></div></div>
    </div>
    <div class="sector-action" id="sec-action" hidden></div>
    <div class="table-wrap" style="margin-top:12px"><table class="list sortable" id="sec-table"></table></div>
    <p class="legend-note">Click a column to sort; click a company to open it. Dashed lines on the chart are the medians; dot size is revenue. ${S.notes.map((n) => esc(sentence(n))).join(" · ")}</p>
    ${sourceLine(`SEC XBRL frames, calendar ${S.year}`)}`;
  const open = (t) => sectorOpen(t);
  scatterChart($("sec-scatter"), {
    points: rows.map((c) => ({ x: c.revenue_cagr, y: c.operating_margin, label: c.ticker, sub: c.name, highlight: c.ticker === me, t: c.ticker, size: c.revenue })),
    refX: medX, refY: medY,
    xFormat: (v, ax) => pct(v, ax), yFormat: (v, ax) => pct(v, ax), xLabel: "Revenue CAGR, 3Y", yLabel: "Operating Margin",
    onClick: (p) => open(p.t) });
  const top = rows.slice(0, 15);
  if (!top.some((c) => c.ticker === me) && sectorMe()) top.push(sectorMe());
  barListChart($("sec-bars"), { items: top.map((c) => ({ label: c.ticker, title: c.name, value: c.revenue, highlight: c.ticker === me, t: c.ticker })),
    format: money, onClick: (it) => open(it.t) });
  drawSectorTable(demo, rows);
}

export function drawSectorTable(demo, levelRowsIn) {
  const S = state.sector, me = state.company.ticker, { key, dir } = state.secSort;
  const val = (c) => (key === "stage" ? c.traits.stage : key === "industry" ? taxName("industry", c.classification?.industry) || "" : key === "detail" ? (inIndex(c.ticker) ? 0 : 1) : c[key]);
  const rows = [...(levelRowsIn || levelRows("secLevel").rows)].sort((a, b) => {
    const x = val(a), y = val(b);
    if (x == null) return 1; if (y == null) return -1;
    return (x > y ? 1 : x < y ? -1 : 0) * dir;
  });
  const t = $("sec-table");
  t.innerHTML = `<thead><tr>${SEC_COLS.map(([k, n]) => `<th data-k="${k}" class="${k === key ? "sorted" : ""}" aria-sort="${k === key ? (dir > 0 ? "ascending" : "descending") : "none"}">${n}${k === key ? (dir > 0 ? " ▲" : " ▼") : ""}</th>`).join("")}</tr></thead>
    <tbody>${rows.map((c) => {
      const has = inIndex(c.ticker), synth = demo && !has;
      return `<tr data-t="${esc(c.ticker)}" class="${c.ticker === me ? "target" : ""} link">
      <td><b>${esc(c.ticker)}</b> <span class="muted small">${esc(c.name || "")}</span>${c.stale ? ` <span class="pill" title="hasn't reported ${S.year} yet">${c.calendar_year}</span>` : ""}</td>
      <td>${money(c.revenue)}</td><td class="${upClass(c.revenue_growth)}">${pct(c.revenue_growth)}</td><td>${pct(c.revenue_cagr)}</td>
      <td>${pct(c.gross_margin)}</td><td>${pct(c.operating_margin)}</td><td>${pct(c.fcf_margin)}</td><td>${pct(c.roe)}</td>
      <td>${mult(c.debt_to_ebitda)}</td><td class="muted small">${esc(taxName("industry", c.classification?.industry) || "–")}</td><td><span class="pill">${esc(titleCase(c.traits.stage))}</span></td>
      <td>${c.ticker === me ? '<span class="muted small">This Company</span>' : has ? '<span class="pill ok">Open</span>' : synth ? '<span class="muted small">Synthetic</span>' : '<span class="pill">Build</span>'}</td></tr>`;
    }).join("")}</tbody>`;
  t.querySelectorAll("th").forEach((th) => th.onclick = () => {
    const k = th.dataset.k;
    state.secSort = { key: k, dir: state.secSort.key === k ? -state.secSort.dir : (k === "ticker" || k === "stage" ? 1 : -1) };
    drawSectorTable(demo);
  });
  t.querySelectorAll("tbody tr").forEach((tr) => tr.onclick = () => sectorOpen(tr.dataset.t));
}

// Open a sector company: switch to it when its detail is published; otherwise
// offer to build it (a Pipeline run through company details).
export async function sectorOpen(ticker) {
  if (ticker === state.company.ticker) return;
  if (inIndex(ticker)) {
    $("company").value = ticker;
    await selectCompany(ticker);
    window.scrollTo({ top: 0, behavior: "smooth" });
    return;
  }
  const box = $("sec-action");
  const c = state.sector.companies.find((x) => x.ticker === ticker);
  box.hidden = false;
  if (state.sector.demo) {
    box.innerHTML = `<p class="muted"><b>${esc(ticker)}</b> is a synthetic peer in the demo sector; it has no filings to build.</p>`;
    return;
  }
  box.innerHTML = `<p><b>${esc(ticker)}</b> · ${esc(c?.name || "")} has no company detail yet. Building it fetches its filings and
    publishes statements, ratios and a profile here (a few minutes).</p>
    <div class="actions"><button type="button" class="primary" id="sec-build">Build Company Detail for ${esc(ticker)}</button>
    <span class="status" role="status"></span></div>`;
  box.scrollIntoView({ behavior: "smooth", block: "nearest" });
  $("sec-build").onclick = async () => {
    const st = box.querySelector(".status");
    st.className = "status"; st.textContent = "Starting…";
    try {
      setStatus(st, await dispatchPipeline({ ticker, as_of: new Date().toISOString().slice(0, 10), models: "dcf", stop_after: "L1" }));
    } catch (err) { setStatus(st, { ok: false, msg: err.message }); }
  };
}
