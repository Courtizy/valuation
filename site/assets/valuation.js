import { $M } from "./company.js";
import { NA, NM, esc, estLabel, fin, label, millions, money, mult, num, pct, periodLabel, price, sentence, sourceLine, times, titleCase } from "./format.js";
import { dispatchPipeline, gh, readRepoJSON, setStatus, writeRepoJSON } from "./github.js";
import { levelBar, levelOptions, levelRows, sectorMe, sectorPicker, wireLevelBar, wireSectorPicker } from "./sector.js";
import { $, getJSON, state } from "./state.js";
import { acct, cellOf, finRow } from "./tables.js";

// ---------------------------------------------------------------- valuation

export const MODEL_NAMES = { dcf: "DCF (Standalone)", dcf_synergy: "DCF with Synergies", just_synergy: "Just Synergies",
  comps: "Public Comps", precedents: "Precedent Transactions", lbo: "LBO", ipo: "IPO" };

export const SCENARIOS = { p10: "Bear", p50: "Base", p90: "Bull" };
export const TRAIT_NAMES = { stage: "Stage", predictability: "Cash-Flow Predictability", asset_intensity: "Asset Intensity",
  capital_structure: "Capital Structure" };

export function signed(v) { return fin(v) ? `${v >= 0 ? "+" : "−"}${Math.abs(v * 100).toFixed(1)}%` : NA; }
export function upClass(v, band = 0.005) { return !fin(v) || Math.abs(v) < band ? "" : v > 0 ? "up" : "down"; }

export function renderValuation() {
  if (!state.detail || state.tab !== "valuation") return;
  const c = state.comparison, body = $("val-body");
  if (!c || !c.football_field?.length) {
    body.innerHTML = `<div class="card empty"><h2>No Model Results for This Run</h2>
      <p>Tick <b>DCF</b> under Models on the Run Pipeline tab and run this ticker. Without a <code>dcf.json</code> the DCF uses default assumptions from the data; Comps needs a <code>comps.json</code> with peers.</p></div>`;
    renderProfileCard(body);
    body.insertAdjacentHTML("beforeend", '<div id="val-peers"></div>');
    renderPeerPicker();
    renderSimilar(body);
    return;
  }
  state.scn = state.scn || "p50";
  body.innerHTML = `<div id="val-head"></div><div id="val-ff"></div><div id="val-profile"></div><div id="val-comps"></div><div id="val-peers"></div>
    <div id="val-dcf"></div><div id="val-similar"></div><div id="val-diffs"></div>`;
  renderHeadline();
  renderField();
  renderProfileCard($("val-profile"));
  renderCompsCard();
  renderPeerPicker();
  renderDcfCard();
  renderSimilar($("val-similar"));
  const diffs = c.assumption_differences || [];
  $("val-diffs").innerHTML = `<div class="card"><div class="card-head"><h2>Where Models Disagree on Inputs</h2></div>${diffs.length
    ? `<div class="table-wrap"><table class="list"><thead><tr><th>Field</th>${Object.keys(diffs[0].values).map((m) => `<th>${esc(MODEL_NAMES[m] || m)}</th>`).join("")}</tr></thead><tbody>${
      diffs.map((d) => `<tr><td>${esc(d.field)}</td>${Object.values(d.values).map((v) => `<td>${esc(typeof v === "number" ? num(v) : JSON.stringify(v))}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`
    : `<p class="muted">Every shared assumption matches, so gaps between models come from method, not inputs.</p>`}
    ${c.warnings?.length ? `<h3 style="margin-top:12px">Warnings</h3><ul>${c.warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul>` : ""}</div>`;
}

export function scenarioToggle() {
  return `<div class="seg" role="group" aria-label="Scenario">${Object.entries(SCENARIOS).map(([k, n]) =>
    `<button type="button" data-scn="${k}" aria-pressed="${state.scn === k}">${n}</button>`).join("")}</div>`;
}

export function wireToggle(root) {
  root.querySelectorAll("[data-scn]").forEach((b) => { b.onclick = () => { state.scn = b.dataset.scn; renderHeadline(); renderField(); }; });
}

export function renderHeadline() {
  const c = state.comparison, k = state.scn, blend = c.blend;
  const primary = (c.plan?.methods || []).filter((m) => m.weight > 0);
  const up = c.upside?.[k];
  $("val-head").innerHTML = `<div class="card">
    <div class="card-head"><h2>Value vs. Price</h2><span class="muted small">Scenario set on the football field below</span></div>
    <div class="headline">
      <div><div class="label">Share Price</div><div class="big num">${price(c.price)}</div>
        <div class="muted small">${c.price_source === "market data" ? marketLine(state.detail.market)
          : c.price_source ? `From ${esc(c.price_source.replace(/\bdcf\b/i, "DCF"))}` : showcase() ? SHOWCASE_NOTE : "No price yet: run the pipeline for market data"}</div></div>
      <div><div class="label">Blended Value · ${SCENARIOS[k]}</div><div class="big num">${blend ? price(blend[k]) : NA}</div>
        <div class="muted small">${blend ? `Bear ${price(blend.p10)} – Bull ${price(blend.p90)}` : "No weighted method has run"}</div></div>
      <div><div class="label">Upside / Downside</div><div class="big num ${upClass(up, 0.05)}">${signed(up)}</div>
        <div class="muted small">${!fin(up) ? (showcase() ? "Needs a market price" : "") : Math.abs(up) < 0.05 ? "Within 5% of price: fairly valued" : up > 0 ? "Undervalued on this blend" : "Overvalued on this blend"}</div></div>
    </div>
    <p class="small" style="margin:12px 0 0">${primary.map((m) => `${m.role === "primary" ? "Primary" : "Cross-Check"} <b>${esc(titleCase(m.name))}</b> ${pct(m.weight, true)}`).join(" · ") || "No weighted methods yet"}.
      <span class="muted">${esc(c.plan?.summary || "")}</span></p>
  </div>`;
}

export function renderField() {
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
      <div class="ff-name"><b>${esc(titleCase(m.name))}</b><div class="muted small">${esc(titleCase(m.role))}${m.weight > 0 ? ` · ${pct(m.weight, true)}` : ""}${m.illustrative ? " · Illustrative" : ""}</div></div>
      ${bar(v, "")}
      <div class="ff-num">${price(v.p10)} – ${price(v.p90)}</div>
      <div class="ff-num"><b>${price(v[k])}</b></div>
      <div class="ff-num ${upClass(u)}">${signed(u)}</div>
      ${m.reason ? `<div class="ff-reason">${esc(m.reason.charAt(0).toUpperCase() + m.reason.slice(1))}.</div>` : ""}</div>`;
  };
  const b = c.blend;
  $("val-ff").innerHTML = `<div class="card">
    <div class="card-head"><h2>Football Field</h2><span class="muted small">Value per share: bar = Bear to Bull, tick = ${SCENARIOS[k]}, line = share price</span>
      <div class="spacer">${scenarioToggle()}</div></div>
    <div class="ff">
      <div class="ff-row ff-head"><div></div>
        <div class="ff-axis">${ticks.map((t) => `<span style="left:${x(t)}">$${Math.abs(t - Math.round(t)) < 1e-9 ? Math.round(t) : t.toFixed(1)}</span>`).join("")}</div>
        <div class="ff-num">Bear – Bull</div><div class="ff-num">${SCENARIOS[k]}</div><div class="ff-num">vs. Price</div></div>
      ${methods.map(row).join("")}
      ${b ? `<div class="ff-row total"><div class="ff-name"><b>Blended</b><div class="muted small">Weights Above</div></div>${bar(b, "blend")}
        <div class="ff-num">${price(b.p10)} – ${price(b.p90)}</div><div class="ff-num"><b>${price(b[k])}</b></div>
        <div class="ff-num ${upClass(c.upside?.[k])}">${signed(c.upside?.[k])}</div></div>` : ""}
    </div>
    <p class="legend-note"><b>Bear / Bull by model:</b> DCF moves near-term growth and WACC by ±1 pt and terminal growth and terminal WACC by ±0.5 pt, weighted by the terminal value's share; Comps uses the peer range (Q1–Q3 with 4+ peers, else lowest–highest); the Blended row weights each model's Bear, Base and Bull.</p>
    ${c.plan?.notes?.length ? `<p class="legend-note">${c.plan.notes.map((n) => esc(sentence(n))).join(" ")}</p>` : ""}
    <p class="legend-note">Weights: inputs/assumptions/${esc(state.company.ticker)}/reconcile.json can override them (<code>{"weights": {"dcf": 0.7, "comps": 0.3}}</code>) or switch to <code>"context": "acquisition"</code> for an offer-price view.</p>
  </div>`;
  wireToggle($("val-ff"));
  drawPriceLine(fin(c.price) ? (c.price - lo) / (hi - lo) : null, c.price);
}

// One price line running through every row of the football field, so each
// method's range reads against the same reference.
export function drawPriceLine(frac, value) {
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

export function renderProfileCard(root) {
  const p = state.detail.profile;
  if (!p?.traits) return;
  const m = (k, v) => {
    const fmt = { revenue_cagr: ["Revenue CAGR", pct], operating_margin: ["Operating Margin", pct],
      fcf_positive_share: ["FCF Positive in", (x) => pct(x, true) + " of years"], fcf_margin_stdev: ["FCF Margin Std. Dev.", (x) => fin(x) ? `${(x * 100).toFixed(1)} pts` : NA],
      capex_to_sales: ["Capex / Sales", pct], noa_turnover: ["NOA Turnover", times], debt_to_ebitda: ["Debt / EBITDA", times],
      net_debt_to_equity: ["Net Debt / Equity", num], liabilities_to_assets: ["Liabilities / Assets", pct] }[k];
    return fmt ? `${fmt[0]} ${fmt[1](v)}` : null;
  };
  const plan = state.comparison?.plan;
  const html = `<div class="card">
    <div class="card-head"><h2>Company Profile</h2><span class="muted small">${esc(p.as_of_period || "")} and ${p.history_years} fiscal years · methods follow these traits, not the sector label</span></div>
    <div class="traits">${Object.entries(p.traits).map(([k, t]) => `<div class="trait">
      <div class="label">${TRAIT_NAMES[k] || k}</div><div class="tval">${esc(titleCase(t.label))}</div>
      <div class="small">${Object.entries(t.measures).map(([mk, mv]) => m(mk, mv)).filter(Boolean).join("; ")}</div>
      <div class="rule">Rule: ${esc(t.rule)}</div></div>`).join("")}</div>
    ${plan ? `<p style="margin:14px 0 0"><b>So:</b> ${esc(plan.summary)}</p>
      <ul class="small" style="margin:6px 0 0 18px; padding:0">${plan.methods.filter((x) => x.role !== "reference" || x.ran).map((x) =>
        `<li><b>${esc(titleCase(x.name))}</b> (${esc(x.role)}${x.weight > 0 ? `, ${pct(x.weight, true)}` : ""}): ${esc(x.reason)}${x.ran ? "" : " <span class='muted'>(not run)</span>"}</li>`).join("")}</ul>` : ""}
  </div>`;
  if (root.id === "val-profile") root.innerHTML = html; else root.insertAdjacentHTML("beforeend", html);
}

// Similar companies: nearest by profile measures (z-scored), not by sector.
/** Matches below this score are too far apart to be useful comparisons. */
export const MIN_SIMILARITY = 0.35;

/** Public showcase: real market prices aren't published (data terms); synthetic examples keep theirs. */
export const showcase = () => state.index?.market_data !== "real" && !state.company?.demo;
export const SHOWCASE_NOTE = "Market prices aren't published on this site; values are intrinsic only";

const SOURCE_NAMES = { yahoo: "Yahoo", alphavantage: "Alpha Vantage", synthetic: "Synthetic Example" };
/** "Close Oct 2, 2026 · Yahoo · Checked against Alpha Vantage": where the price came from and whether it was confirmed. */
export function marketLine(m) {
  if (!m?.price) return showcase() ? SHOWCASE_NOTE : "No market data";
  const d = m.price_date ? new Date(`${m.price_date}T12:00:00Z`).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : "";
  const src = SOURCE_NAMES[m.source] || m.source || "";
  const ck = m.check || {};
  const check = m.fallback ? `<span class="warn">Yahoo unavailable; backup source</span>`
    : ck.status === "ok" ? "Checked against Alpha Vantage"
    : ck.status === "mismatch" ? `<span class="warn">Alpha Vantage differs by ${pct(Math.abs(ck.diff_pct ?? 0))}${ck.price_date !== m.price_date ? ` (its close is ${esc(ck.price_date)})` : ""}</span>`
    : ck.status === "skipped" ? "Not cross-checked (no Alpha Vantage key)"
    : ck.status === "unavailable" ? "Alpha Vantage check unavailable" : "";
  return [`Close ${esc(d)}`, esc(src), check].filter(Boolean).join(" · ");
}

export async function renderSimilar(root) {
  let data;
  data = state.companies || { companies: [] };
  const all = data.companies || [];
  const me = all.find((c) => c.ticker === state.company.ticker);
  if (!me) return;
  // ranking computed at publish (L3_app/similar.py), the same one the peer picker uses
  const byTicker = new Map(all.map((c) => [c.ticker, c]));
  const candidates = (me.similar || []).map((r) => ({ c: byTicker.get(r.ticker), score: r.score, traitsMatch: r.traits_shared }))
    .filter((r) => r.c && r.c.demo === me.demo);
  const ranked = candidates.filter((r) => fin(r.score) && r.score >= MIN_SIMILARITY);
  const weak = candidates.length - ranked.length;
  const med = (k, grp) => { const xs = ranked.map((r) => (r.c[grp] || {})[k]).filter(fin).sort((a, b) => a - b);
    return xs.length ? (xs.length % 2 ? xs[(xs.length - 1) / 2] : (xs[xs.length / 2 - 1] + xs[xs.length / 2]) / 2) : null; };
  // market columns first; any column with no figure for any company shown is dropped
  // (on the public showcase that removes the price-based ones for real companies)
  const allCols = [["P/E", "multiples", "pe", mult], ["EV/EBITDA", "multiples", "ev_ebitda", mult], ["EV/Sales", "multiples", "ev_sales", mult],
    ["P/B", "multiples", "pb", mult], ["FCF Yield", "multiples", "fcf_yield", pct], ["Revenue", "vector", "revenue", money],
    ["Revenue CAGR", "rates", "revenue_cagr", pct], ["Op. Margin", "rates", "operating_margin", pct], ["RNOA", "rates", "rnoa", pct],
    ["Capex / Sales", "rates", "capex_to_sales", pct], ["Debt/EBITDA", "rates", "debt_to_ebitda", mult], ["WACC", "rates", "wacc", pct]];
  const cols = allCols.filter(([, g, k]) => [me, ...ranked.map((r) => r.c)].some((c) => fin((c[g] || {})[k])));
  const cells = (c) => cols.map(([, g, k, f]) => `<td class="${fin((c[g] || {})[k]) ? "" : "na"}">${f((c[g] || {})[k])}</td>`).join("");
  const html = `<div class="card">
    <div class="card-head"><h2>Similar Companies</h2><span class="muted small">ranked by closeness of growth, margins, cash-flow stability, capital intensity, leverage and size, across every company published here</span></div>
    ${ranked.length ? "" : candidates.length
      ? `<p class="muted">No published company is at least ${pct(MIN_SIMILARITY, true)} similar. Pick peers from the sector below, or build company detail for more of them.</p>`
      : `<p class="muted">No other ${me.demo ? "demo " : ""}companies published yet. Run the pipeline for more tickers; they're ranked here by profile, not sector.</p>`}
    <div class="table-wrap"><table class="list">
      <thead><tr><th>Company</th><th>Similarity</th><th>Traits Shared</th>${cols.map(([n]) => `<th>${n}</th>`).join("")}</tr></thead>
      <tbody>
        <tr class="key target"><td>${esc(me.ticker)} <span class="muted small">This Company</span></td><td>–</td><td>–</td>${cells(me)}</tr>
        ${ranked.map((r) => `<tr><td>${esc(r.c.ticker)} <span class="muted small">${esc(r.c.name)}</span></td><td>${fin(r.score) ? pct(r.score, true) : NA}</td>
          <td title="${Object.entries(r.c.traits).map(([k, v]) => `${TRAIT_NAMES[k]}: ${titleCase(v)}`).join("\n")}">${r.traitsMatch} of 4</td>${cells(r.c)}</tr>`).join("")}
        ${ranked.length > 1 ? `<tr class="sub"><td>Peer Median</td><td></td><td></td>${cols.map(([, g, k, f]) => `<td>${f(med(k, g))}</td>`).join("")}</tr>` : ""}
      </tbody></table></div>
    <p class="legend-note">${showcase() ? `${SHOWCASE_NOTE}, so price-based columns appear only where a price was entered in the assumptions. WACC is the DCF's rate where a DCF has run.`
      : `Prices from market data (Yahoo, checked against Alpha Vantage for valued companies and their peers); WACC is the DCF's rate where a DCF has run, else a market estimate (risk-free + beta × 5%). "–" = no market data yet: rerun that company.`} Hover "Traits Shared" for each company's profile.${weak ? ` ${weak} weaker match${weak > 1 ? "es" : ""} (below ${pct(MIN_SIMILARITY, true)}) hidden.` : ""}</p>
  </div>`;
  if (root.id === "val-similar") root.innerHTML = html; else root.insertAdjacentHTML("beforeend", html);
}

export function renderCompsCard() {
  const r = state.comps, d = r?.details;
  if (!d?.peers || !$("val-comps")) return;
  const mids = Object.keys(d.multiples);
  const multName = (k) => ({ ev_sales: "EV/Sales", ev_ebitda: "EV/EBITDA", pe: "P/E" })[k] || k;
  const totalW = mids.reduce((sum, k) => sum + d.multiples[k].weight, 0);
  const row = (p, isTarget) => `<tr class="${isTarget ? "key target" : ""}${p.excluded ? " na" : ""}">
    <td>${esc(p.ticker || "")} <span class="muted small">${esc(isTarget ? "Target" : p.source === "manual" ? "Manual Figures" : (p.name || ""))}</span></td>
    <td>${price(p.price)}</td><td>${millions(p.enterprise_value)}</td>
    <td>${mult(p.multiples.ev_sales)}</td><td>${mult(p.multiples.ev_ebitda)}</td><td>${mult(p.multiples.pe)}</td>
    <td>${pct(p.ebitda_margin)}</td><td>${pct(p.revenue_growth)}</td>
    ${mids.map((m) => `<td>${isTarget ? "–" : price(d.multiples[m].implied[p.ticker])}</td>`).join("")}</tr>`;
  // dot plot: each peer's implied price per multiple, the range band and the median tick, against the price
  const all = mids.flatMap((m) => Object.values(d.multiples[m].implied).filter(fin)).concat(fin(d.market_price) ? [d.market_price] : []);
  const lo = Math.min(...all) * 0.95, hi = Math.max(...all) * 1.05, x = (v) => `${((v - lo) / (hi - lo)) * 100}%`;
  const dots = mids.map((m) => {
    const x0 = d.multiples[m];
    return `<div class="dp-row"><div class="dp-name"><b>${multName(m)}</b><div class="muted small">Weight ${pct(x0.weight / totalW, true)} · Peer Median ${mult(x0.peer_median)}</div></div>
      <div class="dp-track"><span class="dp-band" style="left:${x(x0.conservative)};width:calc(${x(x0.aggressive)} - ${x(x0.conservative)})"></span>
        ${Object.entries(x0.implied).filter(([, v]) => fin(v)).map(([t, v]) => `<span class="dp-dot" style="left:${x(v)}" title="${esc(t)}: ${price(v)}"></span>`).join("")}
        <span class="dp-med" style="left:${x(x0.expected)}" title="median ${price(x0.expected)}"></span>
        ${fin(d.market_price) ? `<span class="dp-price" style="left:${x(d.market_price)}"></span>` : ""}</div>
      <div class="ff-num">${price(x0.conservative)} – ${price(x0.aggressive)}</div><div class="ff-num"><b>${price(x0.expected)}</b></div></div>`;
  }).join("");
  $("val-comps").innerHTML = `<div class="card">
    <div class="card-head"><h2>Public Comps</h2><span class="muted small">${esc(d.range_method === "min_max" ? "Range = lowest to highest implied price (fewer than 4 peers)" : "Range = Q1 to Q3 implied price")}</span></div>
    <div class="dp">
      <div class="dp-row dp-head"><div></div><div class="muted small">Dots = each peer's implied price · band = range · tick = median${fin(d.market_price) ? " · line = share price" : ""}</div>
        <div class="ff-num">Range</div><div class="ff-num">Median</div></div>
      ${dots}
      <div class="dp-row total"><div class="dp-name"><b>Blended Comps Value</b><div class="muted small">Weights above</div></div><div></div>
        <div class="ff-num">${price(d.blend.conservative)} – ${price(d.blend.aggressive)}</div><div class="ff-num"><b>${price(d.blend.expected)}</b></div></div>
    </div>
    <div class="table-wrap" style="margin-top:12px"><table class="list">
      <thead><tr><th>Company</th><th>Price</th><th>EV ($M)</th><th>EV/Sales</th><th>EV/EBITDA</th><th>P/E</th><th>EBITDA Margin</th><th>Revenue CAGR</th>
        ${mids.map((m) => `<th>Implied (${multName(m)})</th>`).join("")}</tr></thead>
      <tbody>${row(d.target, true)}${d.peers.map((p) => row(p, false)).join("")}</tbody></table></div>
    ${r.notes?.length ? `<p class="legend-note">${r.notes.map((n) => esc(sentence(n))).join(" · ")}</p>` : ""}
    ${sourceLine("peer prices from comps.json")}
  </div>`;
}

// ---- comps peer picker ------------------------------------------------------------
// Ranks the sector's companies by closeness on screen figures (z-scores of growth,
// margins, cash-flow stability, capex intensity, leverage and size) plus shared
// traits. Saving writes the ticked tickers (and any prices typed) into
// inputs/assumptions/{TICKER}/comps.json through the GitHub API. Peers the picker doesn't
// show (entered by hand with "sec": false, or outside this sector) are kept.
export function renderPeerPicker() {
  const root = $("val-peers");
  if (!root) return;
  const me = sectorMe();
  if (!state.sector || !me) {
    root.innerHTML = `<div class="card"><div class="card-head"><h2>Pick Comps Peers from a Sector</h2></div>
      <p class="muted">Screen ${esc(state.company.ticker)}'s sector first (Company detail → Versus its sector); its companies then show here, ranked by similarity, to tick as comps peers.</p></div>`;
    return;
  }
  const current = new Map((state.comps?.details?.peers || []).map((p) => [p.ticker, p]));
  // ranking computed at publish (L3_app/similar.py); a company without a published card falls back to revenue order
  const card = (state.companies?.companies || []).find((c) => c.ticker === state.company.ticker);
  // start at the company's industry when it has enough members to pick from, else widen
  if (state.peerLevel === undefined) {
    const opts = levelOptions();
    state.peerLevel = ([...opts].reverse().find((o) => o.rows.length >= 6) || opts[0])?.level;
  }
  const rows = new Map(levelRows("peerLevel").rows.map((c) => [c.ticker, c]));
  const ranked = (card?.peers?.[state.sectorMeta.id] || [...rows.values()].filter((c) => c.ticker !== me.ticker)
    .map((c) => ({ ticker: c.ticker, score: null, traits_shared: Object.keys(me.traits).filter((k) => c.traits[k] === me.traits[k]).length })))
    .filter((r) => rows.has(r.ticker)).map((r) => ({ c: rows.get(r.ticker), score: r.score, traits: r.traits_shared }));
  const inView = ranked.filter((r) => current.has(r.c.ticker));
  const ticked = new Set((inView.length ? inView : ranked.slice(0, 6)).map((r) => r.c.ticker));
  const demo = state.company.demo || state.sector.demo;
  root.innerHTML = `<div class="card"><div class="card-head"><h2>Comps Peers from ${esc(state.sector.label)}</h2>
      ${sectorPicker()}<span class="muted small" id="pp-count"></span></div>
    ${levelBar("peerLevel")}
    <p class="muted small">Ranked by closeness on growth, margins, cash-flow stability, capex intensity, leverage and size, plus shared traits.
      ${inView.length ? "Ticked = the peers in the current comps run." : "The six closest are ticked to start."}
      A peer needs a share price until a market-data source is added; type one here or in comps.json.</p>
    <div class="table-wrap"><table class="list" id="pp-table"><thead><tr><th>Use</th><th>Company</th><th>Similarity</th><th>Traits Shared</th>
      <th>Revenue</th><th>3Y CAGR</th><th>Op. Margin</th><th>Debt/EBITDA</th><th>Price</th></tr></thead><tbody>
      ${ranked.map((r) => { const c = r.c, cur = current.get(c.ticker); return `<tr>
        <td><input type="checkbox" value="${esc(c.ticker)}" ${ticked.has(c.ticker) ? "checked" : ""} aria-label="Use ${esc(c.ticker)}"></td>
        <td><b>${esc(c.ticker)}</b> <span class="muted small">${esc(c.name || "")}</span></td>
        <td>${fin(r.score) ? pct(r.score, true) : NA}</td><td title="${Object.entries(c.traits).map(([k, x]) => `${TRAIT_NAMES[k] || k}: ${titleCase(x)}`).join("\n")}">${r.traits} of 4</td>
        <td>${money(c.revenue)}</td><td>${pct(c.revenue_cagr)}</td><td>${pct(c.operating_margin)}</td><td>${mult(c.debt_to_ebitda)}</td>
        <td><input type="number" class="pp-price" data-t="${esc(c.ticker)}" min="0" step="0.01" placeholder="Market" value="${cur?.price ?? ""}" aria-label="${esc(c.ticker)} price"></td></tr>`; }).join("")}
    </tbody></table></div>
    <div class="actions">
      <button type="button" class="primary" id="pp-save" ${demo ? "disabled" : ""}>Save Peers</button>
      <button type="button" id="pp-run" ${demo ? "disabled" : ""}>Run Comps</button>
      <span class="status" role="status" id="pp-status">${demo ? "Demo data: saving is off." : ""}</span>
    </div>
    <p class="legend-note">Writes <code>inputs/assumptions/${esc(state.company.ticker)}/comps.json</code> in your repo with the token from the Run Pipeline tab
      (it needs Contents: read and write). Run Comps fetches each peer's price from market data; type a price only to override it.
      Peers not listed here (entered by hand, or from outside this sector) are kept.</p></div>`;
  wireSectorPicker(root);
  wireLevelBar(root, renderPeerPicker);
  const count = () => { $("pp-count").textContent = `${root.querySelectorAll("#pp-table input[type=checkbox]:checked").length} ticked`; };
  root.querySelectorAll("#pp-table input[type=checkbox]").forEach((x) => x.onchange = count);
  count();
  $("pp-save").onclick = () => savePeers();
  $("pp-run").onclick = () => runComps();
}

export async function savePeers() {
  const st = $("pp-status"), t = state.company.ticker, path = `inputs/assumptions/${t}/comps.json`;
  const picks = [...document.querySelectorAll("#pp-table input[type=checkbox]:checked")].map((x) => x.value);
  const prices = Object.fromEntries([...document.querySelectorAll(".pp-price")].filter((x) => x.value !== "").map((x) => [x.dataset.t, Number(x.value)]));
  if (!picks.length) { setStatus(st, { ok: false, msg: "Tick at least one peer." }); return; }
  if (!gh().token) { setStatus(st, { ok: false, noToken: true, msg: "Add a token on the Run Pipeline tab (Contents: read and write) to save from here." }); return; }
  st.className = "status"; st.textContent = "Saving…";
  // keep what this picker didn't show: hand-entered peers and peers outside the level in view
  const shown = new Set([...document.querySelectorAll("#pp-table input[type=checkbox]")].map((x) => x.value.toUpperCase()));
  const merge = (doc) => {
    const d = doc || { multiples: ["ev_ebitda", "ev_sales"], range: "auto", peers: [] };
    const old = new Map((d.peers || []).map((e) => (typeof e === "string" ? [e.toUpperCase(), { ticker: e.toUpperCase() }] : [String(e.ticker || "").toUpperCase(), e])));
    const kept = [...old.values()].filter((e) => e.sec === false || !shown.has(String(e.ticker || "").toUpperCase()));
    d.peers = [...kept, ...picks.map((p) => {
      const e = { ...(old.get(p) || { ticker: p }) };
      if (prices[p] != null) e.price = prices[p];
      return e;
    })];
    d.sources = { ...(d.sources || {}), peers: `picked from ${state.sector.label} (screened ${state.sectorMeta.as_of}) on ${new Date().toISOString().slice(0, 10)}` };
    return d;
  };
  try {
    // read, merge, write; if the file changed in between (409), read the new version and merge again once
    for (let attempt = 0; ; attempt++) {
      const { sha, doc } = await readRepoJSON(path);
      try { await writeRepoJSON(path, merge(doc), sha, `assumptions: ${t} comps peers from ${state.sector.label}`); break; }
      catch (err) { if (err.status !== 409 || attempt) throw err; }
    }
    setStatus(st, { ok: true, msg: `Saved ${picks.length} peers to ${path}. Run Comps to value against them.` });
  } catch (err) { setStatus(st, { ok: false, msg: err.message }); }
}

/** Run comps (and the DCF, if it has run) on the peers saved in comps.json. */
export async function runComps() {
  const st = $("pp-status"), t = state.company.ticker;
  st.className = "status"; st.textContent = "Starting…";
  try {
    const models = [...new Set([...(state.run.models || []).filter((m) => m === "dcf" || m === "comps"), "comps"])];
    setStatus(st, await dispatchPipeline({ ticker: t, as_of: new Date().toISOString().slice(0, 10), models: models.join(","), stop_after: "L2" }));
  } catch (err) { setStatus(st, { ok: false, msg: err.message }); }
}

export function bridgeRows(b) {
  const excess = b.cash * (1 - b.operating_cash_pct);
  const other = b.debt - excess - b.net_debt;   // e.g. long-term investments, when included
  const v = (x, o) => [cellOf(acct(x, o))];
  return [
    finRow("PV of Free Cash Flow", v(b.pv_fcf), { indent: 1 }),
    finRow("PV of Terminal Value", v(b.pv_terminal_value), { indent: 1 }),
    finRow("Enterprise Value", v(b.enterprise_value), { kind: "sub" }),
    finRow("Less: Debt", v(-b.debt), { indent: 1 }),
    finRow(`Plus: Cash Beyond Operating Needs (${pct(1 - b.operating_cash_pct, true)} of ${millions(b.cash)})`, v(excess), { indent: 1 }),
    Math.abs(other) > 1 ? finRow("Plus: Long-Term Investments", v(other), { indent: 1 }) : "",
    finRow("Equity Value", v(b.equity_value), { kind: "sub" }),
    finRow("÷ Diluted Shares (M)", v(b.shares), { indent: 1 }),
    finRow("Value per Share", [cellOf(price(b.value_per_share))], { kind: "grand" }),
  ].join("");
}

// Years 1–4, Year 5, Year 10 and the terminal year, on fiscal-year headers (Year 1 = closing year).
function dcfProjectionTable(d) {
  const P = d.projection, n = P.length;
  const idx = [...new Set([1, 2, 3, 4, 5, 10, n].filter((y) => y <= n))];
  const head = idx.map((y) => `<th class="${y === 5 || y === 10 || y === n ? "milestone" : ""}">${estLabel(d.base_period, y)}<span class="th-sub">${y === n ? "Terminal" : y === 5 || y === 10 ? `Year ${y}` : y === 1 ? "Closing" : ""}</span></th>`).join("");
  const row = (name, f, o) => finRow(name, idx.map((y) => cellOf(acct(f(P[y - 1])))), o);
  return `<div class="table-wrap"><table>
      <thead><tr><th>$ Millions</th>${head}</tr></thead>
      <tbody>
        ${row("Revenue", (y) => y.revenue, { kind: "key" })}
        ${row("EBITDA", (y) => y.ebitda, { indent: 1 })}
        ${row("Capital Expenditures", (y) => -y.capex, { indent: 1 })}
        ${row("Increase in Net Working Capital", (y) => -y.change_in_nwc, { indent: 1 })}
        ${row("Unlevered FCF", (y) => y.fcf, { kind: "sub" })}
        ${row("Present Value", (y) => y.pv, { kind: "memo", indent: 1 })}
      </tbody></table></div>`;
}

// WACC (rows) × terminal growth (columns); the base cell outlined, cells shaded by value vs base.
function sensitivityTable(d, base) {
  const g = d.sensitivity;
  if (!g?.values?.length) return '<p class="muted small">Rerun the DCF to add the sensitivity grid.</p>';
  const flat = g.values.flat().filter(fin), lo = Math.min(...flat), hi = Math.max(...flat);
  const tone = (v) => (!fin(v) ? "" : v >= base ? `background-color: color-mix(in srgb, var(--good) ${Math.round(28 * (v - base) / ((hi - base) || 1))}%, var(--surface))`
    : `background-color: color-mix(in srgb, var(--critical) ${Math.round(28 * (base - v) / ((base - lo) || 1))}%, var(--surface))`);
  return `<div class="table-wrap"><table class="sens">
      <thead><tr><th>WACC ↓ · Terminal Growth →</th>${g.terminal_growth.map((t) => `<th>${pct(t)}</th>`).join("")}</tr></thead>
      <tbody>${g.values.map((row, i) => `<tr><td>${pct(g.wacc[i])} <span class="muted small">(terminal ${pct(g.wacc_terminal[i])})</span></td>${row.map((v, j) =>
        `<td class="${i === 2 && j === 2 ? "base" : ""}" style="${tone(v)}">${fin(v) ? price(v) : NM}</td>`).join("")}</tr>`).join("")}</tbody></table></div>
    <p class="legend-note">WACC shifts move the pre-terminal and terminal rates together. Outlined cell = base case; green above it, red below.</p>`;
}

export function renderDcfCard() {
  const r = state.dcf, d = r?.details;
  if (!d?.bridge) return;
  const b = d.bridge, rt = d.rates, t = d.terminal, sc = d.scenarios;
  const card = document.createElement("div");
  card.className = "card";
  const tile = (l, v, sub = "") => `<div class="tile"><div class="label">${esc(l)}</div><div class="value">${v}</div>${sub ? `<div class="delta">${esc(sub)}</div>` : ""}</div>`;
  card.innerHTML = `
    <div class="card-head"><h2>DCF (Standalone)</h2>
      <span class="muted small">${esc(d.mode === "implied" ? "Implied Mode: growth solved to match the price" : "Forecast Mode")} · Base ${esc(d.base_period.kind === "fiscal" ? String(d.base_period.fiscal_year) : d.base_period.label)}${d.default_case
        ? ` · <span class="tile-tag" title="No inputs/assumptions/${esc(state.company.ticker)}/dcf.json: growth from the company's history, rates from the data. Add a dcf.json to set your own.">Default Assumptions</span>` : ""}</span></div>
    <div class="tiles">
      ${tile("Value per Share", price(b.value_per_share), `Bear ${price(sc.conservative)} – Bull ${price(sc.aggressive)}`)}
      ${d.implied_growth != null ? tile("Implied Near-Term Growth", pct(d.implied_growth), `At price ${price(d.market_price)}`) : tile("Share Price", price(d.market_price), state.detail.market?.price === d.market_price ? marketLine(state.detail.market).replace(/<[^>]+>/g, "") : "From the DCF assumptions")}
      ${tile("WACC", pct(rt.wacc), `Terminal year ${pct(rt.wacc_terminal)}`)}
      ${tile("Terminal Value Share", pct(d.terminal_value_share), `Terminal EV/EBITDA ${mult(t.ev_to_ebitda)}`)}
    </div>
    <div class="grid-2">
      <div><h3>EV to Equity Bridge ($M)</h3><div class="table-wrap"><table><tbody>${bridgeRows(b)}</tbody></table></div></div>
      <div><h3>Discount Rates</h3><div class="table-wrap"><table><tbody>
        <tr class="group"><td colspan="2">Cost of Equity</td></tr>
        ${finRow("Beta: Observed → Unlevered → Relevered", [cellOf(`${num(rt.beta_levered_observed)} → ${num(rt.beta_unlevered)} → ${num(rt.beta_relevered)}`)], { indent: 1 })}
        ${finRow("Target Debt / Equity", [cellOf(num(rt.target_debt_to_equity))], { indent: 1 })}
        ${finRow("Cost of Equity", [cellOf(pct(rt.cost_of_equity))], { kind: "sub", indent: 1 })}
        <tr class="group"><td colspan="2">Cost of Debt</td></tr>
        ${finRow(`Pre-Tax Cost of Debt (${esc({ interest_over_debt: "interest ÷ debt", given: "given", fallback: "fallback yield" }[rt.cost_of_debt_method] || "given")})`, [cellOf(pct(rt.pre_tax_cost_of_debt))], { indent: 1 })}
        ${finRow("Weights: Equity / Debt", [cellOf(`${pct(rt.equity_weight)} / ${pct(rt.debt_weight)}`)], { indent: 1 })}
        ${finRow("WACC (Pre-Terminal)", [cellOf(pct(rt.wacc))], { kind: "grand" })}
        <tr class="group"><td colspan="2">Terminal Year</td></tr>
        ${finRow("Risk-Free Rate", [cellOf(pct(rt.risk_free_terminal))], { indent: 1 })}
        ${finRow("Cost of Equity", [cellOf(pct(rt.cost_of_equity_terminal))], { indent: 1 })}
        ${finRow("WACC (Terminal Year)", [cellOf(pct(rt.wacc_terminal))], { kind: "sub" })}
        ${finRow("Terminal Growth", [cellOf(pct(t.growth))], { indent: 1, kind: "memo" })}
        ${finRow("Terminal ROIC", [cellOf(pct(t.roic))], { indent: 1, kind: "memo" })}
      </tbody></table></div></div>
    </div>
    <h3 style="margin-top:16px">Projection ($M)</h3>
    ${dcfProjectionTable(d)}
    <h3 style="margin-top:16px">Sensitivity: Value per Share</h3>
    ${sensitivityTable(d, b.value_per_share)}
    <p class="legend-note">Free cash flow = EBITDA × (1 − t) + D&amp;A × t − capex − ΔNWC, so it isn't the simple sum of the lines above.</p>
    <p class="legend-note">Year 1 is the closing year (not discounted). Range: conservative and aggressive move near-term growth with WACC and terminal growth with terminal WACC, blended by the terminal value's share.${r.notes?.length ? " " + esc(r.notes.filter((n) => !n.startsWith("range =")).join(" ")) : ""}</p>`;
  ($("val-dcf") || $("val-body")).appendChild(card);
}
