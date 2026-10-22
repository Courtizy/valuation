import { NA, esc, estLabel, fin, mult, num, pct, price, sentence, times, unit, unitShort } from "./format.js";
import { deviceAssumptions, saveAssumption } from "./device.js";
import { setStatus } from "./status.js";
import { runInBrowser } from "./run.js";
import { $, state } from "./state.js";
import { tabSet, wireTabs } from "./tabs.js";
import { acct, cellOf, finRow } from "./tables.js";

// ---- Deal view: the acquisition side of the course model ------------------------------------
// Inputs (deal.json, saved on this device) → the whole-firm DCF with synergies and the just-synergies
// DCF (run in this browser) → the course Summary: standalone range, offer price range, premiums.
// Weights and the relative power of the target recompute here as they change (same math as
// L2_models/reconcile/deal.py); Save keeps them for the next run.

export const DEAL_MODELS = ["dcf_synergy", "just_synergy"];
const SYNERGY_METHODS = new Set(DEAL_MODELS);

function savedDeal() {
  try { return JSON.parse(deviceAssumptions()[`${state.company.ticker}/deal.json`] || "null"); } catch { return null; }
}

/** The deal behind this run: saved on this device, else what the models ran with. */
function currentDeal() {
  const mine = savedDeal();
  if (mine) return mine;
  const c = state.comparison?.deal, syn = state.deal?.dcf_synergy?.details?.synergies || state.deal?.just_synergy?.details?.synergies;
  if (!c && !syn) return null;
  const s = { ...(syn || {}) };
  // the default one-time cost (2 x annual synergies) was filled in by the model: leave the field blank
  if (fin(s.one_time_cost) && Math.abs(s.one_time_cost - 2 * s.annual_cost * (1 + (s.revenue_pct_of_cost || 0))) < 1) s.one_time_cost = null;
  return { pre_announcement_price: c?.pre_announcement_source === "deal inputs" ? c.pre_announcement_price : null,
    offer_price: c?.offer_price ?? null, relative_power: c?.relative_power ?? 0.5, synergies: s };
}

/** deal.py's summary, recomputed from the stored method values with these weights and power. */
function summarize(base, weights, power) {
  const pre = base.pre_announcement_price;
  const side = (rows, w) => {
    const live = rows.filter((r) => r.values && (w[r.method] ?? r.weight) > 0);
    const total = live.reduce((s, r) => s + (w[r.method] ?? r.weight), 0);
    return rows.map((r) => ({ ...r, weight: w[r.method] ?? r.weight,
      adjusted_weight: total && live.includes(r) ? (w[r.method] ?? r.weight) / total : 0 }));
  };
  const st = side(base.standalone.methods, weights.standalone || {}), of = side(base.offer.methods, weights.offer || {});
  const sum = (rows, pick) => rows.filter((r) => r.adjusted_weight).reduce((s, r) => s + r.adjusted_weight * pick(r), 0);
  const stRange = st.some((r) => r.adjusted_weight)
    ? { conservative: sum(st, (r) => r.values[0]), best_guess: sum(st, (r) => r.values[1]), aggressive: sum(st, (r) => r.values[2]) } : null;
  let offer = null;
  if (of.some((r) => r.adjusted_weight)) {
    const low = sum(of, (r) => r.values[0]), high = sum(of, (r) => r.values[SYNERGY_METHODS.has(r.method) ? 1 : 2]);
    offer = { conservative: low, best_guess: low + (high - low) * power, aggressive: high };
  }
  const gap = offer && pre ? offer.aggressive - pre : null;
  const share = (v) => (gap && fin(v) ? (v - pre) / gap : null);
  const prem = (v) => (fin(v) && pre ? v / pre - 1 : null);
  const map = (o, f) => (o ? Object.fromEntries(Object.entries(o).map(([k, v]) => [k, f(v)])) : null);
  return { pre, st, of, stRange, offer, premium: map(offer, prem), synergyShare: map(offer, share), prem, share };
}

const pctIn = (v) => (fin(v) ? +(v * 100).toFixed(4) : "");
const dollarsIn = (v) => (fin(v) ? +(v / unit().scale).toFixed(4) : "");

function inputsCard(d, demo) {
  const s = d?.synergies || {}, px = state.detail.market?.price;
  const f = (id, lbl, val, hint, attrs = 'step="any"') => `<div class="field"><label for="${id}">${lbl}${hint ? ` <span class="hint">${hint}</span>` : ""}</label>
    <input type="number" id="${id}" ${attrs} value="${val ?? ""}"></div>`;
  return `<p class="muted small">Dollar amounts in ${esc(unit().label.replace("$ ", ""))} (the $K / $M / $B switch).</p>
    <form id="deal-form" autocomplete="off">
      <h3>Deal</h3>
      <div class="form-grid">
        ${f("d-pre", "Pre-Announcement Price ($/share)", d?.pre_announcement_price, `blank = market price${fin(px) ? ` ${price(px)}` : ""}`, 'step="0.01" min="0"')}
        ${f("d-offer", "Actual or Initial Offer ($/share)", d?.offer_price, "optional, for comparison", 'step="0.01" min="0"')}
        ${f("d-power", "Relative Power of the Target", d?.relative_power ?? 0.5, "0 = buyer holds the power, 1 = target", 'step="0.05" min="0" max="1"')}
      </div>
      <h3 style="margin-top:12px">Synergies</h3>
      <div class="form-grid">
        ${f("d-cost", `Annual Cost Synergies (${unitShort()})`, dollarsIn(s.annual_cost), "once fully realized", 'step="any" min="0" required')}
        ${f("d-revpct", "Revenue Synergies (% of Cost Synergies)", pctIn(s.revenue_pct_of_cost ?? 0), "")}
        ${f("d-once", `One-Time Cost to Get Them (${unitShort()})`, dollarsIn(s.one_time_cost), "blank = 2 × annual synergies")}
        ${f("d-years", "Years to Full Synergies", s.years_to_full ?? 2, "", 'step="1" min="1" max="10"')}
        ${f("d-forever", "Cost Synergies That Last Forever (%)", pctIn(s.cost_forever ?? 0), "the rest competes away by the terminal year")}
      </div>
      <h3 style="margin-top:12px">Whole Firm DCF with Synergies</h3>
      <div class="form-grid">
        ${f("d-growth", "Revenue Growth Added (pts)", pctIn(s.revenue_growth_add ?? 0), "from year 1 on")}
        ${f("d-realized", "Cost Synergies Realized (%)", pctIn(s.cost_realized ?? 1), "")}
      </div>
      <div class="actions">
        <button type="submit" class="primary" id="d-run" ${demo ? "disabled" : ""}>Save and Run Deal</button>
        <span class="status" role="status" id="d-status">${demo ? "Demo data: saving is off." : ""}</span>
      </div>
      <p class="legend-note">Runs the whole-firm DCF with synergies and the just-synergies DCF in this browser, on top of
        ${esc(state.company.ticker)}'s standalone DCF inputs, then rebuilds the summary below. Cost synergies cut COGS and SG&amp;A
        (costs rise by the same amount in the closing year for integration, then phase in); revenue synergies last.</p>
    </form>`;
}

function readForm() {
  const v = (id) => { const x = $(id).value.trim(); return x === "" ? null : Number(x); };
  const scale = unit().scale, p = (id) => (v(id) === null ? null : v(id) / 100);
  return {
    pre_announcement_price: v("d-pre"), offer_price: v("d-offer"), relative_power: v("d-power") ?? 0.5,
    synergies: { annual_cost: v("d-cost") === null ? null : v("d-cost") * scale, revenue_pct_of_cost: p("d-revpct") ?? 0,
      one_time_cost: v("d-once") === null ? null : v("d-once") * scale, years_to_full: v("d-years") ?? 2,
      cost_forever: p("d-forever") ?? 0, revenue_growth_add: p("d-growth") ?? 0, cost_realized: p("d-realized") ?? 1 },
  };
}

function rangeRows(rows, prem) {
  return rows.map((r) => `<tr class="${r.adjusted_weight ? "" : "na"}">
    <td>${esc(r.name)}</td>
    ${[0, 1, 2].map((i) => `<td>${r.values ? price(r.values[i]) : NA}</td>`).join("")}
    <td><input type="number" class="dw" data-m="${esc(r.method)}" min="0" max="100" step="1" value="${pctIn(r.weight)}" aria-label="${esc(r.name)} weight"></td>
    <td>${r.values ? pct(r.adjusted_weight) : "No value"}</td>
    ${prem ? `<td>${r.values ? pct(prem(r.values[1])) : NA}</td>` : ""}</tr>`).join("");
}

function summaryCard(s, d) {
  const total = (lbl, r, extra = "") => `<tr class="sub"><td>${lbl}</td>${r ? ["conservative", "best_guess", "aggressive"].map((k) => `<td><b>${price(r[k])}</b></td>`).join("") : "<td colspan=3>No method has a value yet</td>"}<td></td><td></td>${extra}</tr>`;
  const offerPx = d?.offer_price;
  return `<div class="card"><div class="card-head"><h2>Offer Table</h2><span class="muted small">The course summary: each method's range, its weight, and what the offer range implies</span></div>
    <div class="table-wrap"><table class="list deal-sum" id="deal-sum">
      <thead><tr><th>Valuation Approach</th><th>Conservative</th><th>Best Guess</th><th>Aggressive</th><th>Weight (%)</th><th>Used</th></tr></thead>
      <tbody>
        <tr class="group"><td colspan="6">Standalone</td></tr>
        ${rangeRows(s.st)}
        ${total("Standalone Range", s.stRange)}
        <tr class="group"><td colspan="6">Offer Price</td></tr>
        ${rangeRows(s.of)}
        ${total("Offer Price Range", s.offer)}
        ${s.offer ? `<tr class="memo"><td>Premium over Pre-Announcement ${price(s.pre)}</td>${["conservative", "best_guess", "aggressive"].map((k) => `<td>${pct(s.premium[k])}</td>`).join("")}<td></td><td></td></tr>
        <tr class="memo"><td>Share of Synergies Paid to the Target</td>${["conservative", "best_guess", "aggressive"].map((k) => `<td>${pct(s.synergyShare[k])}</td>`).join("")}<td></td><td></td></tr>` : ""}
        ${fin(offerPx) ? `<tr class="key"><td>Actual or Initial Offer</td><td colspan="3">${price(offerPx)} · premium ${pct(s.prem(offerPx))}${s.offer ? ` · ${pct(s.share(offerPx))} of the synergies to the target` : ""}</td><td></td><td></td></tr>` : ""}
      </tbody></table></div>
    <div class="actions">
      <button type="button" id="dw-save" ${state.company.demo ? "disabled" : ""}>Save Weights</button>
      <span class="status" role="status" id="dw-status"></span>
    </div>
    <p class="legend-note">Weights follow the course model: a method with no value passes its weight to the others ("Used").
      The top of the offer range takes the synergy methods at their best guess, since paying for synergies beyond what you expect gives the whole gain away;
      the best guess sits between the ends by the relative power of the target (${num(d?.relative_power ?? 0.5)}). The LBO shows what a financial buyer could pay; it carries no weight unless you give it one.</p>
    ${state.comparison?.deal?.notes?.length ? `<p class="legend-note">${state.comparison.deal.notes.map((n) => esc(sentence(n))).join(" ")}</p>` : ""}
  </div>`;
}

/** Football field: standalone methods, then transaction methods, each block ending in its weighted range,
 *  with the pre-announcement price (dashed) and the offer (solid) through every row. */
function fieldBody(s, d) {
  const block = (label, rows, total, totalName, group) => [
    { head: label },
    ...rows.filter((r) => r.values).map((r) => ({ ...r, group })),
    total && { name: totalName, values: [total.conservative, total.best_guess, total.aggressive], total: true, group }];
  const rows = [...block("Standalone", s.st, s.stRange, "Standalone Range", "st"),
    ...block("Transaction", s.of, s.offer, "Offer Price Range", "of")].filter(Boolean);
  const bars = rows.filter((r) => r.values);
  if (!bars.length) return "";
  const offerPx = d?.offer_price;
  const vals = bars.flatMap((r) => [r.values[0], r.values[2]]).concat([s.pre, offerPx].filter(fin));
  const lo = Math.min(...vals) * 0.97, hi = Math.max(...vals) * 1.03, x = (v) => `${((v - lo) / (hi - lo)) * 100}%`;
  const marks = `${fin(s.pre) ? `<span class="px" style="left:${x(s.pre)}" title="Pre-announcement ${price(s.pre)}"></span>` : ""}${fin(offerPx) ? `<span class="px offer" style="left:${x(offerPx)}" title="Offer ${price(offerPx)}"></span>` : ""}`;
  return `<div class="legend deal-legend"><span><span class="key" style="background:var(--series-1)"></span>Standalone methods</span>
      <span><span class="key" style="background:var(--series-2)"></span>Transaction methods</span>
      ${fin(s.pre) ? `<span><span class="key line"></span>Pre-announcement ${price(s.pre)}</span>` : ""}
      ${fin(offerPx) ? `<span><span class="key line offer"></span>Offer ${price(offerPx)}</span>` : ""}
      <span class="muted">Bar = conservative to aggressive, tick = best guess</span></div>
    <div class="ff deal-ff">${rows.map((r) => r.head ? `<div class="ff-group">${r.head}</div>` : `<div class="ff-row ${r.total ? "total" : r.adjusted_weight ? "" : "ref"} ${r.group}">
        <div class="ff-name"><b>${esc(r.name)}</b>${r.total ? "" : `<div class="muted small">Weight ${pct(r.adjusted_weight, true)}</div>`}</div>
        <div class="ff-bar ${r.total ? "blend" : ""}"><span class="rng" style="left:${x(r.values[0])};width:calc(${x(r.values[2])} - ${x(r.values[0])})"></span>
          <span class="tick" style="left:${x(r.values[1])}"></span>${marks}</div>
        <div class="ff-num">${price(r.values[0])} – ${price(r.values[2])}</div><div class="ff-num"><b>${price(r.values[1])}</b></div>
        <div class="ff-num">${fin(s.pre) ? pct(r.values[1] / s.pre - 1) : ""}</div></div>`).join("")}</div>`;
}

const synergyPerShare = () => state.deal?.just_synergy?.details?.synergy_per_share;

/** Value bridge: pre-announcement price + the synergies' value per share = the most a buyer can pay,
 *  against the offer. Figures from the just-synergies model. */
function bridgeChart(s, d) {
  const syn = synergyPerShare(), pre = s.pre, offerPx = d?.offer_price;
  if (!fin(syn) || !fin(pre)) return "";
  const cap = pre + syn;
  const steps = [{ name: ["Pre-announcement", "price"], from: 0, to: pre, cls: "base" },
    { name: ["Synergies", "per share"], from: pre, to: cap, cls: "up" },
    { name: ["Most a buyer", "can pay"], from: 0, to: cap, cls: "total" }];
  if (fin(offerPx)) {
    steps.push(offerPx >= cap ? { name: ["Paid above", "synergies"], from: cap, to: offerPx, cls: "over" }
      : { name: ["Kept by", "the buyer"], from: offerPx, to: cap, cls: "kept" });
    steps.push({ name: ["Offer", ""], from: 0, to: offerPx, cls: "offer" });
  }
  const top = Math.max(...steps.map((t) => t.to)), floor = Math.min(pre, ...(fin(offerPx) ? [offerPx] : [])) * 0.85;
  const raw = (top - floor) / 4, mag = 10 ** Math.floor(Math.log10(raw)), step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((v) => v >= raw);
  const lo = Math.floor(floor / step) * step, hi = Math.ceil(top * 1.04 / step) * step;
  const W = 440, H = 250, B = 196, T = 24, X0 = 46, bw = 52;
  const y = (v) => B - ((Math.max(v, lo) - lo) / (hi - lo)) * (B - T);
  const gap = (W - X0 - 8 - steps.length * bw) / Math.max(1, steps.length - 1);
  let g = "";
  for (let t = lo; t <= hi + step / 2; t += step) g += `<line class="grid" x1="${X0 - 4}" x2="${W - 4}" y1="${y(t)}" y2="${y(t)}"/><text class="axis" x="${X0 - 8}" y="${y(t) + 4}" text-anchor="end">$${+t.toFixed(2)}</text>`;
  steps.forEach((t, i) => {
    const x0 = X0 + i * (bw + gap), yt = y(Math.max(t.from, t.to)), yb = y(Math.min(t.from, t.to) || lo);
    const lbl = t.cls === "up" || t.cls === "over" ? `+${price(t.to - t.from)}` : t.cls === "kept" ? `−${price(t.to - t.from)}` : price(t.to);
    g += `<rect class="wf ${t.cls}" x="${x0}" y="${yt}" width="${bw}" height="${Math.max(2, yb - yt)}"/>
      <text class="val" x="${x0 + bw / 2}" y="${yt - 6}" text-anchor="middle">${lbl}</text>
      ${t.name.map((n, k) => `<text class="axis" x="${x0 + bw / 2}" y="${B + 15 + k * 12}" text-anchor="middle">${esc(n)}</text>`).join("")}`;
    if (i < steps.length - 1) {
      const lvl = t.cls === "kept" ? y(t.from) : yt;
      g += `<line class="link" x1="${x0 + bw}" x2="${x0 + bw + gap}" y1="${lvl}" y2="${lvl}"/>`;
    }
  });
  return `<svg class="deal-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="Value bridge from the pre-announcement price to the most a buyer can pay${fin(offerPx) ? " and the offer" : ""}">${g}
    <text class="axis" x="${X0 - 8}" y="10">Axis from ${price(lo)}</text></svg>`;
}

/** Premiums paid: each prior deal's premium as a dot, the middle half shaded, the median and the bid marked. */
function premiumStrip(s, d) {
  const r = state.deal?.precedents?.details, st = r?.central?.stats?.premium;
  if (!r || !st) return "";
  const prem = r.deals.map((x) => x.premium).filter(fin);
  const bid = fin(d?.offer_price) && fin(s.pre) ? d.offer_price / s.pre - 1 : null;
  const top = Math.max(...prem, bid ?? 0), hi = Math.ceil((top + 0.05) * 10) / 10;
  const W = 420, H = 160, L = 14, R = 14, cy = 78, x = (v) => L + (v / hi) * (W - L - R);
  let g = "";
  for (let t = 0; t <= hi + 1e-9; t += hi > 0.6 ? 0.2 : 0.1) g += `<line class="grid" x1="${x(t)}" x2="${x(t)}" y1="30" y2="124"/><text class="axis" x="${x(t)}" y="140" text-anchor="middle">${Math.round(t * 100)}%</text>`;
  g += `<rect class="band" x="${x(st.q1)}" y="${cy - 22}" width="${x(st.q3) - x(st.q1)}" height="44"/>
    <line class="med" x1="${x(st.median)}" x2="${x(st.median)}" y1="${cy - 26}" y2="${cy + 26}"/>`;
  const seen = {};
  prem.forEach((p) => { const k = Math.round(p * 60); seen[k] = (seen[k] || 0) + 1; const n = seen[k] - 1, dy = n ? (n % 2 ? 1 : -1) * Math.ceil(n / 2) * 9 : 0;
    g += `<circle class="deal-dot" cx="${x(p)}" cy="${cy + dy}" r="4.5"/>`; });
  if (fin(bid)) g += `<line class="bid" x1="${x(bid)}" x2="${x(bid)}" y1="26" y2="124"/><text class="bidlbl" x="${x(bid)}" y="20" text-anchor="${bid > hi * 0.7 ? "end" : "start"}">Bid ${pct(bid)}</text>`;
  g += `<text class="axis" x="${x(st.median)}" y="${fin(bid) && Math.abs(x(bid) - x(st.median)) < 70 ? 152 : 20}" text-anchor="middle">Median ${pct(st.median)}</text>`;
  return `<svg class="deal-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="Premiums paid in ${prem.length} prior deals">${g}</svg>
    <p class="legend-note">Shaded = middle half of deals (${pct(st.q1)}–${pct(st.q3)}); line = median.</p>`;
}

function kpiRow(s, d) {
  const offerPx = d?.offer_price;
  const tile = (l, v, sub, main = false) => `<div class="kpi ${main ? "kpi--main" : ""}"><div class="label">${l}</div><div class="kpi__value num">${v}</div><div class="muted small">${sub}</div></div>`;
  return `<div class="kpis">
    ${tile("Standalone Value", s.stRange ? price(s.stRange.best_guess) : NA, s.stRange ? `Range ${price(s.stRange.conservative)} – ${price(s.stRange.aggressive)}` : "No standalone method yet")}
    ${tile("Offer Price Range", s.offer ? price(s.offer.best_guess) : NA, s.offer ? `Range ${price(s.offer.conservative)} – ${price(s.offer.aggressive)}` : "No offer method yet", true)}
    ${fin(offerPx) ? tile("Initial Offer", price(offerPx), `${pct(s.prem(offerPx))} over ${price(s.pre)} pre-announcement`)
      : tile("Pre-Announcement Price", price(s.pre), "Enter the offer under Deal Inputs to test it")}
    ${fin(offerPx) && s.offer ? tile("Synergies Paid Away", pct(s.share(offerPx), true), "Share of the gap to the top of the offer range")
      : tile("Premium at Best Guess", s.offer ? pct(s.premium.best_guess) : NA, "Over the pre-announcement price")}
  </div>`;
}

/** Page one of the deal: the finding, four numbers, the football field, the bridge and premiums paid. */
function summarySheet(s, d, edited) {
  const h = state.comparison?.deal?.headlines || {};
  const bridge = bridgeChart(s, d), prem = premiumStrip(s, d);
  return `<div class="card sheet">
    <div class="eyebrow">Offer analysis · ${esc(state.company.ticker)} · $ per share</div>
    <h2 class="action-title">${esc(h.summary || "Deal Summary")}</h2>
    ${edited ? `<p class="legend-note">Headlines describe the last run's weights; the numbers below follow your edits. Save Weights and run the deal again to rewrite them.</p>` : ""}
    ${kpiRow(s, d)}
    <div class="sheet-block"><h3 class="block-title">${esc(h.field || "Football Field")}</h3>${fieldBody(s, d)}</div>
    ${bridge || prem ? `<div class="grid-2 sheet-two">
      ${bridge ? `<div class="sheet-block"><h3 class="block-title">${esc(h.bridge || "Value Bridge")}</h3>${bridge}</div>` : ""}
      ${prem ? `<div class="sheet-block"><h3 class="block-title">${esc(h.premiums || "Premiums Paid in Prior Deals")}</h3>${prem}</div>` : ""}
    </div>` : ""}
  </div>`;
}

function grid(rowsAxis, colsAxis, values, fr, fc, baseR, baseC, corner, fv = price, highIsGood = true) {
  const flat = values.flat().filter(fin), lo = Math.min(...flat), hi = Math.max(...flat);
  const tone = (v) => (!fin(v) ? "" : `background-color: color-mix(in srgb, var(--series-1) ${Math.round(6 + 44 * (highIsGood ? hi - v : v - lo) / ((hi - lo) || 1))}%, var(--surface))`);
  return `<div class="table-wrap"><table class="sens"><thead><tr><th>${corner}</th>${colsAxis.map((c) => `<th>${fc(c)}</th>`).join("")}</tr></thead>
    <tbody>${values.map((row, i) => `<tr><td>${fr(rowsAxis[i])}</td>${row.map((v, j) => `<td class="${i === baseR && j === baseC ? "base" : ""}" style="${tone(v)}">${fv(v)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}

const tile = (l, v, sub = "") => `<div class="tile"><div class="label">${esc(l)}</div><div class="value">${v}</div>${sub ? `<div class="delta">${esc(sub)}</div>` : ""}</div>`;

/** Week 9 synergy checks: what it takes to reach a price, whether cost synergies can last, and the deal's
 *  synergies against prior deals'. */
function synergyChecks(c, kind) {
  if (!c) return "";
  const prior = state.deal?.precedents?.details?.synergy_stats, need = c.needed_for_price, last = c.lasting_cost;
  const margin = state.comparison?.cross_checks?.normal_profit?.margin;
  const rows = [];
  if (need) rows.push(["Synergies Needed for " + price(need.price), kind === "whole"
    ? (fin(need.cost_pct) ? `a ${pct(need.cost_pct)} cut to COGS and SG&A (${acct(need.annual_cost)} a year) with ${pct(need.revenue_growth_add)} added growth` : "no cut in range reaches it")
    : (fin(need.annual_cost) ? `${acct(need.annual_cost)} a year in cost synergies (revenue synergies and one-time costs in proportion)` : "no amount in range reaches it")]);
  if (fin(c.synergies_to_sales)) rows.push(["Synergies / Sales", `${pct(c.synergies_to_sales)} for this deal${prior ? `; prior deals ${pct(prior.median)} median, ${pct(prior.mean)} average (${prior.n} deals)` : ""}`]);
  if (last) rows.push(["Cost Synergies That Can Last", `${pct(last.range[0], true)}–${pct(last.range[1])}: ${esc(sentence(last.note))}${margin ? ` ${esc(sentence(margin.note))}` : ""}`]);
  if (!rows.length) return "";
  return `<h3 style="margin-top:16px">Synergy Checks</h3><div class="table-wrap"><table class="list checks"><tbody>${rows.map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join("")}</tbody></table></div>`;
}

function wholeFirmCard(r) {
  const d = r?.details;
  if (!d) return "";
  const g = d.sensitivity, P = d.projection, n = P.length, rg = d.range;
  const idx = [...new Set([1, 2, 3, 4, 5, 10, n].filter((y) => y <= n))];
  const base = state.dcf?.details?.base_period;
  const row = (name, f, o) => finRow(name, idx.map((y) => cellOf(acct(f(P[y - 1])))), o);
  const h = state.comparison?.deal?.headlines || {};
  return `<div class="card"><div class="card-head"><h2 class="action-title">${esc(h.whole_firm || "Whole Firm DCF with Synergies")}</h2><span class="muted small">Whole firm DCF with synergies: the standalone DCF with synergies in its drivers</span></div>
    <div class="tiles">
      ${tile("Value per Share", price(rg.expected), `Range ${price(rg.conservative)} – ${price(rg.aggressive)}`)}
      ${tile("Standalone DCF", price(d.standalone_per_share), "Same inputs, no synergies")}
      ${tile("Synergies per Share", price(d.synergy_per_share), "With synergies less without")}
      ${tile("Cost Cut", pct(d.cost_pct), `Of ${d.cost_lines.map((k) => ({ cogs: "COGS", sga: "SG&A", rnd: "R&D", other_opex: "other costs" })[k] || k).join(" + ")} × ${pct(d.synergies.cost_realized, true)} realized`)}
    </div>
    <div class="table-wrap"><table><thead><tr><th>${unit().label}</th>${idx.map((y) => `<th>${estLabel(base, y)}<span class="th-sub">${y === n ? "Terminal" : y === 1 ? "Closing" : ""}</span></th>`).join("")}</tr></thead>
      <tbody>${row("Revenue", (y) => y.revenue, { kind: "key" })}${row("EBITDA", (y) => y.ebitda, { indent: 1 })}
        ${row("Unlevered FCF", (y) => y.fcf, { kind: "sub" })}${row("Present Value", (y) => y.pv, { kind: "memo", indent: 1 })}</tbody></table></div>
    <h3 style="margin-top:16px">Sensitivity: Cost Synergies Realized × Revenue Growth Added</h3>
    ${grid(g.realized, g.revenue_growth_add, g.values, (v) => pct(v, true), (v) => `${v < 0 ? "−" : "+"}${pct(Math.abs(v))}`, 3, 2, "Realized ↓ · Growth Added →")}
    ${synergyChecks(d.checks, "whole")}
    <p class="legend-note">Range: conservative = realized ${pct(-rg.steps.realized, true)} and growth ${pct(-rg.steps.revenue_growth_add)}; aggressive the reverse (the course's sensitivity table).
      Terminal ROIC ${pct(d.terminal?.roic)} · terminal value ${pct(d.terminal_value_share)} of EV · WACC ${pct(d.rates.wacc)} (terminal ${pct(d.rates.wacc_terminal)}).${r.notes?.length ? " " + esc(r.notes.map(sentence).join(" ")) : ""}</p></div>`;
}

function justSynergyCard(r) {
  const d = r?.details;
  if (!d) return "";
  const g = d.sensitivity, rg = d.range, Y = d.years;
  const baseRow = g.cost_forever.findIndex((f) => Math.abs(f - d.synergies.cost_forever) < 1e-9);
  const h = state.comparison?.deal?.headlines || {};
  return `<div class="card"><div class="card-head"><h2 class="action-title">${esc(h.just_synergy || "Just Synergies")}</h2><span class="muted small">Just synergies: pre-announcement price + the synergies' DCF value per share</span></div>
    <div class="tiles">
      ${tile("Value per Share", price(rg.expected), `Range ${price(rg.conservative)} – ${price(rg.aggressive)}`)}
      ${tile("Synergies per Share", price(d.synergy_per_share), `On ${price(d.pre_announcement_price)} pre-announcement`)}
      ${tile("Most a Buyer Could Pay", pct(d.max_premium), "Premium over pre-announcement")}
      ${tile("Terminal Value Share", pct(d.terminal_value_share), `Of the synergies' value`)}
    </div>
    <div class="table-wrap"><table><thead><tr><th>${unit().label}</th>${Y.map((y) => `<th>Year ${y.year}${y.year === 0 ? '<span class="th-sub">Closing</span>' : y.year === Y.length - 1 ? '<span class="th-sub">Terminal</span>' : ""}</th>`).join("")}</tr></thead>
      <tbody>${finRow("Cost Synergies", Y.map((y) => cellOf(acct(y.cost))), { indent: 1 })}
        ${finRow("Revenue Synergies", Y.map((y) => cellOf(acct(y.revenue))), { indent: 1 })}
        ${finRow("One-Time Costs", Y.map((y) => cellOf(acct(-y.one_time))), { indent: 1 })}
        ${finRow("After Tax", Y.map((y) => cellOf(acct(y.after_tax))), { kind: "sub" })}
        ${finRow("Terminal Value", Y.map((y) => cellOf(y.terminal_value ? acct(y.terminal_value) : "")), { indent: 1 })}
        ${finRow("Present Value", Y.map((y) => cellOf(acct(y.pv))), { kind: "memo", indent: 1 })}</tbody></table></div>
    <h3 style="margin-top:16px">Sensitivity: Lasting Share of Cost Synergies × Annual Cost Synergies</h3>
    ${grid(g.cost_forever, g.annual_cost, g.values, (v) => pct(v, true), (v) => `${acct(v)}`, baseRow, 3, `Lasting ↓ · Annual (${unitShort()}) →`)}
    ${synergyChecks(d.checks, "just")}
    <p class="legend-note">Year 0 is the closing year (not discounted). Cost synergies phase in over ${d.synergies.years_to_full} years then grow with revenue (${pct(d.growth)});
      revenue synergies are ${pct(d.synergies.revenue_pct_of_cost)} of cost synergies and last; only ${pct(d.synergies.cost_forever)} of cost synergies enter the terminal value.
      Range: annual synergies ${pct(-rg.steps.annual_cost, true)} / +${pct(rg.steps.annual_cost, true)}.</p></div>`;
}

// ---- LBO: what a financial sponsor could pay ------------------------------------------------

const TRANCHE = { senior: "Senior Debt", subordinated: "Subordinated Debt", mezzanine: "Mezzanine" };
const signedX = (v) => `${v < 0 ? "−" : "+"}${Math.abs(v).toFixed(1)}x`;

function lboCard(r) {
  const d = r?.details;
  if (!d) return null;
  const P = d.schedule, debt = d.debt, pu = d.purchase, su = d.sources_uses, ex = d.exit, rg = d.range, inp = d.inputs;
  const yrs = P.map((y) => `<th>Year ${y.year}</th>`).join("");
  const row = (name, f, o) => finRow(name, P.map((y) => cellOf(acct(f(y)))), o);
  const g1 = d.grids.max_price_by_irr_and_exit, g2 = d.grids.irr_by_exit_and_coverage;
  const pctCell = (v) => (fin(v) ? pct(v) : NA);
  return `<div class="card"><div class="card-head"><h2 class="action-title">${esc(state.comparison?.deal?.headlines?.lbo || "LBO: What a Financial Buyer Could Pay")}</h2>
      <span class="muted small">A sponsor's ${pct(d.sponsor_irr, true)} target return in place of WACC, levered cash flows, and a sale after ${P.length} years</span></div>
    <div class="tiles">
      ${tile(`Max Price at ${pct(d.sponsor_irr, true)} IRR`, price(d.max_price), `Range ${price(rg.conservative)} (${pct(d.sponsor_irr + 0.05, true)}) – ${price(rg.aggressive)} (${pct(d.sponsor_irr - 0.05, true)})`)}
      ${tile("Max Premium", pct(d.max_premium), `Over ${price(pu.price)}; standalone DCF ${price(d.standalone_per_share)}`)}
      ${tile(`IRR at ${price(pu.offer_price)} Offer`, fin(d.irr_at_offer) ? pct(d.irr_at_offer) : NA, `${pct(pu.offer_premium)} premium · ${fin(d.money_multiple) ? d.money_multiple.toFixed(2) + "× money" : ""}`)}
      ${tile("Debt / EBITDA", times(debt.total_leverage), `Coverage at close ${times(debt.coverage)} (target ${times(inp.coverage)})`)}
    </div>
    <div class="grid-2">
      <div><h3>Sources and Uses (${unitShort()})</h3><div class="table-wrap"><table class="wrap-names"><tbody>
        <tr class="group"><td colspan="3">Sources</td></tr>
        ${Object.entries(TRANCHE).map(([k, n]) => finRow(`${n} (${pct(debt.rates[k])}, ${times(debt.leverage?.[k])})`, [cellOf(acct(su.sources[k]))], { indent: 1 })).join("")}
        ${finRow("Sponsor Equity", [cellOf(acct(su.sources.sponsor_equity))], { indent: 1 })}
        ${finRow("Total", [cellOf(acct(su.total))], { kind: "sub" })}
        <tr class="group"><td colspan="3">Uses</td></tr>
        ${finRow(`Purchase Equity (${price(pu.offer_price)} × ${num(pu.shares / 1e6)}M shares)`, [cellOf(acct(su.uses.purchase_equity))], { indent: 1 })}
        ${finRow("Refinance Net Debt", [cellOf(acct(su.uses.refinance_net_debt))], { indent: 1 })}
        ${finRow(`Fees (${pct(inp.fees, true)} of new debt)`, [cellOf(acct(su.uses.fees))], { indent: 1 })}
        ${finRow("Total", [cellOf(acct(su.total))], { kind: "sub" })}
      </tbody></table></div>
      <p class="legend-note">Senior debt is capped by the securable assets (${acct(inp.securable_assets)}, ${esc(inp.securable_basis)}); subordinated is ${pct(inp.sub_to_senior, true)} of senior; mezzanine fills the rest until EBIT covers interest ${times(inp.coverage)}.</p></div>
      <div><h3>Returns (${unitShort()})</h3><div class="table-wrap"><table class="wrap-names"><tbody>
        ${finRow(`Exit EBITDA (Year ${P.length})`, [cellOf(acct(ex.ebitda))], { indent: 1 })}
        ${finRow(`× Exit Multiple (today's ${mult(pu.multiple_at_current)} ${signedX(ex.multiple_change)})`, [cellOf(mult(ex.multiple))], { indent: 1 })}
        ${finRow("Enterprise Value at Exit", [cellOf(acct(ex.enterprise_value))], { kind: "sub" })}
        ${finRow("Less: Debt Remaining", [cellOf(acct(-ex.debt))], { indent: 1 })}
        ${finRow("Sponsor Equity at Exit", [cellOf(acct(ex.equity))], { kind: "sub" })}
        ${finRow("Sponsor Equity at Close", [cellOf(acct(d.sponsor_equity))], { indent: 1 })}
        ${finRow(`IRR at the ${price(pu.offer_price)} Offer`, [cellOf(fin(d.irr_at_offer) ? pct(d.irr_at_offer) : NA)], { kind: "grand" })}
        ${finRow(`Multiple at Offer / Today`, [cellOf(`${mult(pu.multiple_at_offer)} / ${mult(pu.multiple_at_current)}`)], { indent: 1, kind: "memo" })}
      </tbody></table></div></div>
    </div>
    <h3 style="margin-top:16px">Cash Flow and Debt Paydown (${unitShort()})</h3>
    <div class="table-wrap"><table><thead><tr><th>${unit().label}</th>${yrs}</tr></thead><tbody>
      ${row("EBITDA", (y) => y.ebitda, { kind: "key" })}
      ${row("Less: Capex", (y) => -y.capex, { indent: 1 })}
      ${row("Less: Increase in NWC", (y) => -y.change_in_nwc, { indent: 1 })}
      ${row("Less: Cash Interest", (y) => -y.total_interest, { indent: 1 })}
      ${row("Less: Cash Taxes", (y) => -y.cash_taxes, { indent: 1 })}
      ${row("Cash for Debt Repayment", (y) => y.cash_for_debt, { kind: "sub" })}
      ${Object.entries(TRANCHE).map(([k, n]) => row(`${n}, End of Year`, (y) => y.end[k], { indent: 1 })).join("")}
      ${row("Cash to the Sponsor", (y) => y.to_sponsor, { indent: 1, kind: "memo" })}
      ${finRow("EBIT ÷ Interest", P.map((y) => cellOf(times(y.coverage))), { kind: "memo" })}
    </tbody></table></div>
    <h3 style="margin-top:16px">Sensitivity: Max Price by Sponsor IRR × Exit Multiple</h3>
    ${grid(g1.sponsor_irr, g1.exit_multiple_change, g1.values, (v) => pct(v, true), (v) => signedX(v), g1.sponsor_irr.findIndex((x) => Math.abs(x - d.sponsor_irr) < 1e-9), 2, "IRR ↓ · Exit Multiple Change →")}
    <h3 style="margin-top:16px">Sensitivity: IRR at the Offer by Coverage × Exit Multiple</h3>
    ${grid(g2.coverage, g2.exit_multiple_change, g2.values, (v) => times(v), (v) => signedX(v), g2.coverage.findIndex((x) => Math.abs(x - inp.coverage) < 1e-9), 2, "Coverage ↓ · Exit Multiple Change →", pctCell, false)}
    <p class="legend-note">Max price = (PEMV at the target IRR + LBO debt − net debt − fees) ÷ shares, where PEMV discounts the cash left for the sponsor and the exit equity (EBITDA × exit multiple − debt).
      The offer premium changes neither the debt nor the exit multiple, so it moves the IRR but not the max price; the target IRR moves the max price but not the IRR.
      Interest is on each year's average balance (the model's circularity, solved by iteration); the sweep pays senior first.${r.notes?.length ? " " + esc(r.notes.map(sentence).join(" ")) : ""}</p></div>`;
}

function savedLbo() {
  try { return JSON.parse(deviceAssumptions()[`${state.company.ticker}/lbo.json`] || "null"); } catch { return null; }
}

function lboInputs(r, demo) {
  const x = savedLbo() || r?.details?.inputs || {}, st = savedLbo()?.steps || r?.details?.steps || {};
  const f = (id, lbl, val, hint, attrs = 'step="any"') => `<div class="field"><label for="${id}">${lbl}${hint ? ` <span class="hint">${hint}</span>` : ""}</label>
    <input type="number" id="${id}" ${attrs} value="${val ?? ""}"></div>`;
  const securable = savedLbo() ? x.securable_assets : null;
  return `<h3>LBO</h3>
    <div class="form-grid">
      ${f("l-irr", "Sponsor Target IRR (%)", pctIn(x.sponsor_irr ?? 0.2), "15–25% typical")}
      ${f("l-hold", "Years Held", x.hold_years ?? 5, "", 'step="1" min="1" max="10"')}
      ${f("l-prem", "Offer Premium (%)", pctIn(x.offer_premium ?? 0.3), "for the IRR at the offer")}
      ${f("l-exit", "Exit Multiple Change (x)", x.exit_multiple_change ?? 0, "added to today's EV/EBITDA")}
      ${f("l-cov", "Interest Coverage (EBIT ÷ Interest)", x.coverage ?? 2, "lenders' floor", 'step="0.1" min="0.5"')}
      ${f("l-sec", `Securable Assets (${unitShort()})`, dollarsIn(securable), "blank = PP&E + receivables + inventories")}
      ${f("l-pctsec", "Share of Assets Secured (%)", pctIn(x.pct_secured ?? 1), "")}
      ${f("l-sub", "Subordinated ÷ Senior (%)", pctIn(x.sub_to_senior ?? 0.6), "")}
      ${f("l-rate", "Senior Rate (%)", savedLbo() ? pctIn(x.senior_rate) : "", "blank = the DCF's cost of debt")}
      ${f("l-step", "Rate Step per Tranche (pts)", pctIn(x.rate_step ?? 0.03), "")}
      ${f("l-fees", "Fees (% of New Debt)", pctIn(x.fees ?? 0.02), "")}
    </div>
    <h3 style="margin-top:12px">Sponsor's Improvements</h3>
    <div class="form-grid">
      ${f("l-g", "Revenue Growth Added (pts)", pctIn(st.growth_add ?? 0), "every year")}
      ${f("l-m", "EBITDA Margin Added (pts)", pctIn(st.margin_add ?? 0), "from year 1")}
      ${f("l-c", "Capex / Sales Added (pts)", pctIn(st.capex_add ?? 0), "negative = cut")}
      ${f("l-n", "Working Capital Change in Year 1 (%)", pctIn(st.nwc_change ?? 0), "e.g. −25 releases a quarter")}
    </div>
    <div class="actions">
      <button type="button" class="primary" id="l-run" ${demo ? "disabled" : ""}>Save and Run LBO</button>
      <span class="status" role="status" id="l-status">${demo ? "Demo data: saving is off." : ""}</span>
    </div>
    <p class="legend-note">Starts from ${esc(state.company.ticker)}'s standalone DCF projection; the improvements are what a sponsor would have to deliver
      (ask what it takes to justify the premium, and what other deals achieved).</p>`;
}

async function runLbo() {
  const st = $("l-status"), t = state.company.ticker, btn = $("l-run");
  const v = (id) => { const x = $(id).value.trim(); return x === "" ? null : Number(x); };
  const p = (id) => (v(id) === null ? null : v(id) / 100);
  const doc = { sponsor_irr: p("l-irr"), hold_years: v("l-hold"), offer_premium: p("l-prem"), exit_multiple_change: v("l-exit"),
    coverage: v("l-cov"), securable_assets: v("l-sec") === null ? null : v("l-sec") * unit().scale, pct_secured: p("l-pctsec"),
    sub_to_senior: p("l-sub"), senior_rate: p("l-rate"), rate_step: p("l-step"), fees: p("l-fees"),
    steps: { growth_add: p("l-g"), margin_add: p("l-m"), capex_add: p("l-c"), nwc_change: p("l-n") } };
  btn.disabled = true;
  try {
    await saveAssumption(`${t}/lbo.json`, doc);
    const models = [...new Set([...(state.run.models || []).filter((m) => m !== "lbo"), "dcf", "lbo"])];
    await runInBrowser({ ticker: t, models: models.join(",") }, st);
  } catch (err) { setStatus(st, { ok: false, msg: `Couldn't save in this browser: ${err.message}` }); } finally { if (btn.isConnected) btn.disabled = false; }
}

// ---- prior deals (transaction comps) ------------------------------------------------------

function savedDeals() {
  try { return JSON.parse(deviceAssumptions()[`${state.company.ticker}/precedents.json`] || "null"); } catch { return null; }
}

const CHOICES = { 0: "Best deals for standalone, all deals for the offer (course default)", 1: "Best deals only", 2: "All deals only" };
const xm = (v) => (fin(v) ? `${v.toFixed(1)}x` : NA);
const ALIGN = { green: ["m-green", "Close"], yellow: ["m-yellow", "Near"], red: ["m-red", "Far"] };
const alignCell = (a) => {
  if (!a?.light) return `<td class="na">${NA}</td>`;
  const [cls, word] = ALIGN[a.light];
  return `<td class="${cls}" title="${esc(`${word}: ${a.gap >= 0 ? "+" : "−"}${Math.abs(a.gap * 100).toFixed(0)}% vs. the target's multiple`)}">${a.gap >= 0 ? "+" : "−"}${Math.abs(a.gap * 100).toFixed(0)}% <span class="m-icon" role="img" aria-label="${word}"></span></td>`;
};

function priorDealsInputs(r, demo) {
  const d = r?.details, mine = savedDeals();
  const choice = mine?.choice ?? d?.choice ?? 0;
  return `<h3>Prior Deals</h3>
    <div class="form-grid">
      <div class="field"><label for="pd-file">Deal List <span class="hint">CSV, or a sheet saved as CSV; an SDC export works as is</span></label>
        <input type="file" id="pd-file" accept=".csv,.tsv,.txt,text/csv,text/plain"></div>
      <div class="field"><label for="pd-choice">Which Deals Feed the Summary</label>
        <select id="pd-choice">${Object.entries(CHOICES).map(([k, n]) => `<option value="${k}" ${Number(k) === Number(choice) ? "selected" : ""}>${esc(n)}</option>`).join("")}</select></div>
    </div>
    <div class="field" style="margin-top:8px"><label for="pd-paste">Or Paste from Excel <span class="hint">copy the deal rows with their header row</span></label>
      <textarea id="pd-paste" rows="4" placeholder="Target Name&#9;Price Per Share&#9;Target Share Price 1 Week Prior&#9;Shares&#9;Net Debt&#9;Sales&#9;EBITDA …">${esc(mine?.csv || "")}</textarea></div>
    <div class="actions">
      <button type="button" class="primary" id="pd-run" ${demo ? "disabled" : ""}>Save and Run Prior Deals</button>
      <span class="status" role="status" id="pd-status">${demo ? "Demo data: a synthetic deal list, saving is off." : ""}</span>
    </div>
    <p class="legend-note">Columns are matched by name: target, acquirer, year or date, offer price per share, price 1 week (and 4 weeks) before
      the announcement, shares, net debt, sales, EBITDA, and the EV at the offer price if your source reports it. Keep each row in one unit
      (SDC uses $ millions); only ratios cross over to ${esc(state.company.ticker)}. Mark the most comparable deals in a "Best" column, or tick them in the appendix's deal list.</p>`;
}

const ROW_NAMES = { pre_sales: "Pre-announcement EV/Sales", pre_ebitda: "Pre-announcement EV/EBITDA", tx_sales: "Transaction EV/Sales",
  tx_ebitda: "Transaction EV/EBITDA", premium: "Premium Paid" };

/** Method tab: the implied value per share from best deals and from all deals. */
function priorDealsResults(r) {
  const d = r?.details;
  if (!d) return null;
  const c = d.central, b = d.best_rows, t = d.target, h = state.comparison?.deal?.headlines || {};
  const rng = (x) => (x ? x.map((v) => `<td>${price(v)}</td>`).join("") : `<td colspan="3" class="na">${NA}</td>`);
  return `<div class="card"><div class="card-head"><h2 class="action-title">${esc(h.prior_deals || "Prior Deals (Transaction Comps)")}</h2>
      <span class="muted small">Prior deals: target ${price(t.price)}, EV/Sales ${xm(t.ev_sales)}, EV/EBITDA ${xm(t.ev_ebitda)}</span></div>
    <div class="table-wrap"><table class="list deal-sum"><thead><tr><th>Implied Value per Share</th><th colspan="3">Best Deals: Lowest · Average · Highest</th>
      <th colspan="3">All Deals: Central Tendency</th></tr></thead><tbody>
      ${Object.entries(ROW_NAMES).map(([k, n]) => `<tr><td>${n}</td>${rng(b.ranges[k])}${rng(c.ranges[k])}</tr>`).join("")}
    </tbody></table></div>
    <p class="legend-note">Central tendency: premium at the 1st quartile, median and 3rd quartile; multiples at the ${pct(c.percentiles.ev_sales[1], true)} (EV/Sales) and
      ${pct(c.percentiles.ev_ebitda[1], true)} (EV/EBITDA) percentile ±10 points, where ${esc(state.company.ticker)}'s own multiples rank among the deals' pre-announcement multiples.
      Best deals rebuild each deal's EV from offer × shares + net debt. The full list and its statistics are in the appendix.${r.notes?.length ? " " + esc(r.notes.map(sentence).join(" ")) : ""}</p>
    ${regressionBlock(d)}</div>`;
}

/** Week 9: premium paid regressed on the pre-announcement EV/EBITDA across the deals. */
function regressionBlock(d) {
  const g = d.regression;
  if (!g) return "";
  const t2 = (v) => (fin(v) ? v.toFixed(2) : NA);
  return `<h3 style="margin-top:16px">Premium Paid vs. Pre-Announcement EV/EBITDA</h3>
    <div class="table-wrap"><table class="list checks"><tbody>
      <tr><td>Premium = a + b × EV/EBITDA</td><td>a = ${pct(g.intercept)} (t ${t2(g.t_intercept)}) · b = ${pct(g.slope)} per turn (t ${t2(g.t_slope)}) · R² ${t2(g.r_squared)} · ${g.n} deals</td></tr>
      <tr><td>Implied for ${esc(state.company.ticker)} at ${xm(g.target_x)}</td><td>premium ${pct(g.implied_premium)} → ${price(g.implied_price)} per share</td></tr>
      <tr><td>Sign</td><td><span class="${g.sign_ok ? "status--good" : "status--warning"}">${g.sign_ok ? "As expected" : "Check"}</span> ${g.sign_ok
        ? "negative: a target already priced rich leaves less room for a premium (the underlying value method)"
        : "positive in this list, unlike the usual negative link: read the implied premium with care"}</td></tr>
    </tbody></table></div>`;
}

/** Appendix: every deal (tick the most comparable) and the statistics across them. */
function priorDealsList(r) {
  const d = r?.details;
  if (!d) return null;
  const deals = d.deals, c = d.central, best = new Set(d.best || []);
  const align = Object.fromEntries((d.alignment || []).map((a) => [a.target, a]));
  const st = (k, q, f) => f(c.stats[k]?.[q]);
  const qs = [["mean", "Mean"], ["min", "Minimum"], ["q1", "1st Quartile"], ["median", "Median"], ["q3", "3rd Quartile"], ["max", "Maximum"]];
  return `<div class="card"><div class="card-head"><h2>Deal List</h2><span class="muted small">${deals.length} deals · ${best.size} most comparable (ticked)</span></div>
    <div class="table-wrap"><table class="list deal-sum"><thead><tr><th>All Deals</th><th>Premium</th><th>Trans. EV/Sales</th><th>Trans. EV/EBITDA</th>
      <th>Pre-ann. EV/Sales</th><th>Pre-ann. EV/EBITDA</th><th>EBITDA Margin</th></tr></thead><tbody>
      ${qs.map(([q, n]) => `<tr><td>${n}</td><td>${st("premium", q, pct)}</td><td>${st("tx_ev_sales", q, xm)}</td><td>${st("tx_ev_ebitda", q, xm)}</td>
        <td>${st("pre_ev_sales", q, xm)}</td><td>${st("pre_ev_ebitda", q, xm)}</td><td>${st("ebitda_margin", q, pct)}</td></tr>`).join("")}
    </tbody></table></div>
    <div class="table-wrap" style="margin-top:12px"><table class="list deal-sum" id="pd-table"><thead><tr><th>Best</th><th>Target</th><th>Acquirer</th><th>Year</th>
      <th>Premium</th><th>Trans. EV/Sales</th><th>Trans. EV/EBITDA</th><th>Pre-ann. EV/EBITDA</th><th title="The deal's own pre-announcement EV/EBITDA against the target's: green within 15%, yellow within 30%">Lines Up with Target</th><th>EBITDA Margin</th></tr></thead><tbody>
      ${deals.map((x) => `<tr><td><input type="checkbox" value="${esc(x.target)}" ${best.has(x.target) ? "checked" : ""} aria-label="Best: ${esc(x.target)}"></td>
        <td>${esc(x.target)}</td><td class="muted">${esc(x.acquirer || "")}</td><td>${fin(x.year) ? x.year : ""}</td><td>${pct(x.premium)}</td>
        <td>${xm(x.tx_ev_sales)}</td><td>${xm(x.tx_ev_ebitda)}</td><td>${xm(x.pre_ev_ebitda)}</td>${alignCell(align[x.target])}<td>${pct(x.ebitda_margin)}</td></tr>`).join("")}
    </tbody></table></div>
    <p class="legend-note">Lines Up with Target: a transaction multiple only works when the deal's own pre-announcement EV/EBITDA is close to ${esc(state.company.ticker)}'s (${xm(d.target?.ev_ebitda)}).
      <span class="m-green"><span class="m-icon"></span> within 15%</span>, <span class="m-yellow"><span class="m-icon"></span> within 30%</span>, <span class="m-red"><span class="m-icon"></span> further</span>.
      Premium = offer over the price 1 week (or 4 weeks, whichever is larger) before the announcement; a negative premium counts as 10% and anything over 100% as 100%.
      Tick the most comparable deals (up to about five) and press Save and Run Prior Deals under Deal Inputs.</p></div>`;
}

async function runPriorDeals() {
  const st = $("pd-status"), t = state.company.ticker, btn = $("pd-run");
  const file = $("pd-file").files?.[0];
  const csv = file ? await file.text() : $("pd-paste").value;
  if (!csv.trim()) { setStatus(st, { ok: false, msg: "Choose a deal list file or paste the deals." }); return; }
  const ticked = [...document.querySelectorAll("#pd-table input[type=checkbox]:checked")].map((x) => x.value);
  const old = savedDeals() || {};
  const doc = { ...old, csv, choice: Number($("pd-choice").value), sources: { deals: file ? `uploaded ${file.name}` : "pasted deal list" } };
  if (csv === old.csv && ticked.length) doc.best = ticked; else delete doc.best;      // a new list starts from its own "Best" column
  btn.disabled = true;
  try {
    await saveAssumption(`${t}/precedents.json`, doc);
    const deal = savedDeal() ? DEAL_MODELS : [];
    const models = [...new Set([...(state.run.models || []).filter((m) => m === "dcf" || m === "comps"), "dcf", "precedents", ...deal])];
    await runInBrowser({ ticker: t, models: models.join(",") }, st);
  } catch (err) { setStatus(st, { ok: false, msg: `Couldn't save in this browser: ${err.message}` }); } finally { if (btn.isConnected) btn.disabled = false; }
}

export function renderDeal() {
  const box = $("panel-deal");
  if (!box || !state.detail) return;
  const d = currentDeal(), base = state.comparison?.deal, demo = !!(state.company.demo || state.detail.demo);
  const w = d?.weights || {};
  const s = base ? summarize(base, w, d?.relative_power ?? base.relative_power ?? 0.5) : null;
  const pr = state.deal?.precedents;
  const methods = tabSet("deal-methods", [
    { key: "prior", label: "Prior Deals", html: priorDealsResults(pr) },
    { key: "whole", label: "Whole Firm with Synergies", html: wholeFirmCard(state.deal?.dcf_synergy) || null },
    { key: "just", label: "Just Synergies", html: justSynergyCard(state.deal?.just_synergy) || null },
    { key: "lbo", label: "LBO", html: lboCard(state.deal?.lbo) },
  ], { title: "Method Detail" });
  const appendix = tabSet("deal-appendix", [{ key: "deals", label: "Deal List", html: priorDealsList(pr) }], { title: "Appendix" });
  box.innerHTML = `${s ? `<div id="deal-sumbox">${summarySheet(s, d) + summaryCard(s, d)}</div>` : `<div class="card empty"><h2>No Deal Run Yet</h2><p>Enter the expected synergies under <b>Deal Inputs</b> below and press <b>Save and Run Deal</b>.
      The standalone values (DCF, comps, 52-week range) fill the standalone side; the synergy models and prior deals fill the offer side.</p></div>`}
    ${methods}
    <details class="card inputs-card" id="deal-inputs" ${s ? "" : "open"}><summary><h2>Deal Inputs</h2><span class="muted small">Synergies, the offer and the prior-deal list, saved on this device</span></summary>
      ${inputsCard(d, demo)}<div class="subsection">${priorDealsInputs(pr, demo)}</div><div class="subsection">${lboInputs(state.deal?.lbo, demo)}</div></details>
    ${appendix}`;
  $("pd-run").onclick = runPriorDeals;
  $("l-run").onclick = runLbo;
  wireTabs(box);
  wire(base);
}

function wire(base) {
  const t = state.company.ticker;
  $("deal-form").onsubmit = async (e) => {
    e.preventDefault();
    const st = $("d-status"), doc = { ...(savedDeal() || {}), ...readForm() };
    if (!fin(doc.synergies.annual_cost)) { setStatus(st, { ok: false, msg: "Enter the annual cost synergies." }); return; }
    const btn = $("d-run");
    btn.disabled = true;
    try {
      await saveAssumption(`${t}/deal.json`, doc);
      const models = [...new Set([...(state.run.models || []).filter((m) => m === "dcf" || m === "comps" || m === "precedents"), "dcf",
        ...(savedDeals() ? ["precedents"] : []), ...DEAL_MODELS])];
      await runInBrowser({ ticker: t, models: models.join(",") }, st);
    } catch (err) { setStatus(st, { ok: false, msg: `Couldn't save in this browser: ${err.message}` }); } finally { if (btn.isConnected) btn.disabled = false; }
  };
  wireSummary(base);
}

function wireSummary(base) {
  const t = state.company.ticker, table = $("deal-sum");
  if (!table || !base) return;
  const current = () => {
    const w = { standalone: {}, offer: {} };
    table.querySelectorAll(".dw").forEach((x) => {
      const side = base.standalone.methods.some((r) => r.method === x.dataset.m) ? "standalone" : "offer";
      w[side][x.dataset.m] = x.value === "" ? 0 : Number(x.value) / 100;
    });
    return w;
  };
  table.querySelectorAll(".dw").forEach((x) => { x.onchange = () => requestAnimationFrame(() => {
    // redraw the football field and summary with the edited weights (kept on Save Weights)
    const d = { ...(currentDeal() || {}), weights: current() }, s = summarize(base, d.weights, d.relative_power ?? 0.5);
    $("deal-sumbox").innerHTML = summarySheet(s, d, true) + summaryCard(s, d);
    wireSummary(base);
  }); });
  $("dw-save").onclick = async () => {
    try {
      await saveAssumption(`${t}/deal.json`, { ...(currentDeal() || {}), weights: current() });
      setStatus($("dw-status"), { ok: true, msg: "Weights saved on this device." });
    } catch (err) { setStatus($("dw-status"), { ok: false, msg: `Couldn't save: ${err.message}` }); }
  };
}
