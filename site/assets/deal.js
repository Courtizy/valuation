import { NA, esc, estLabel, fin, num, pct, price, sentence, unit, unitShort } from "./format.js";
import { deviceAssumptions, saveAssumption } from "./device.js";
import { setStatus } from "./status.js";
import { runInBrowser } from "./run.js";
import { $, state } from "./state.js";
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
  return `<div class="card"><div class="card-head"><h2>Deal Inputs</h2><span class="muted small">Saved on this device; dollar amounts in ${esc(unit().label.replace("$ ", ""))} (the $K / $M / $B switch)</span></div>
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
    </form></div>`;
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
  return `<div class="card"><div class="card-head"><h2>Summary</h2><span class="muted small">Standalone value vs. what to offer, value per share</span></div>
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
      the best guess sits between the ends by the relative power of the target (${num(d?.relative_power ?? 0.5)}). The LBO joins once it's built.</p>
    ${state.comparison?.deal?.notes?.length ? `<p class="legend-note">${state.comparison.deal.notes.map((n) => esc(sentence(n))).join(" ")}</p>` : ""}
  </div>`;
}

function fieldCard(s, d) {
  const rows = [...s.st.filter((r) => r.values).map((r) => ({ ...r, group: "st" })),
    s.stRange && { name: "Standalone Range", values: [s.stRange.conservative, s.stRange.best_guess, s.stRange.aggressive], total: true },
    ...s.of.filter((r) => r.values).map((r) => ({ ...r, group: "of" })),
    s.offer && { name: "Offer Price Range", values: [s.offer.conservative, s.offer.best_guess, s.offer.aggressive], total: true }].filter(Boolean);
  if (!rows.length) return "";
  const offerPx = d?.offer_price;
  const vals = rows.flatMap((r) => [r.values[0], r.values[2]]).concat([s.pre, offerPx].filter(fin));
  const lo = Math.min(...vals) * 0.97, hi = Math.max(...vals) * 1.03, x = (v) => `${((v - lo) / (hi - lo)) * 100}%`;
  const marks = `${fin(s.pre) ? `<span class="px" style="left:${x(s.pre)}" title="Pre-announcement ${price(s.pre)}"></span>` : ""}${fin(offerPx) ? `<span class="px offer" style="left:${x(offerPx)}" title="Offer ${price(offerPx)}"></span>` : ""}`;
  return `<div class="card"><div class="card-head"><h2>Football Field</h2><span class="muted small">Bar = conservative to aggressive, tick = best guess · dashed = pre-announcement ${price(s.pre)}${fin(offerPx) ? ` · solid = offer ${price(offerPx)}` : ""}</span></div>
    <div class="ff">${rows.map((r) => `<div class="ff-row ${r.total ? "total" : r.adjusted_weight ? "" : "ref"}">
        <div class="ff-name"><b>${esc(r.name)}</b>${r.total ? "" : `<div class="muted small">${r.group === "st" ? "Standalone" : "Offer"} · ${pct(r.adjusted_weight, true)}</div>`}</div>
        <div class="ff-bar ${r.total ? "blend" : ""}"><span class="rng" style="left:${x(r.values[0])};width:calc(${x(r.values[2])} - ${x(r.values[0])})"></span>
          <span class="tick" style="left:${x(r.values[1])}"></span>${marks}</div>
        <div class="ff-num">${price(r.values[0])} – ${price(r.values[2])}</div><div class="ff-num"><b>${price(r.values[1])}</b></div>
        <div class="ff-num">${fin(s.pre) ? pct(r.values[1] / s.pre - 1) : ""}</div></div>`).join("")}</div></div>`;
}

function grid(rowsAxis, colsAxis, values, fr, fc, baseR, baseC, corner) {
  const flat = values.flat().filter(fin), lo = Math.min(...flat), hi = Math.max(...flat);
  const tone = (v) => (!fin(v) ? "" : `background-color: color-mix(in srgb, var(--series-1) ${Math.round(6 + 44 * (hi - v) / ((hi - lo) || 1))}%, var(--surface))`);
  return `<div class="table-wrap"><table class="sens"><thead><tr><th>${corner}</th>${colsAxis.map((c) => `<th>${fc(c)}</th>`).join("")}</tr></thead>
    <tbody>${values.map((row, i) => `<tr><td>${fr(rowsAxis[i])}</td>${row.map((v, j) => `<td class="${i === baseR && j === baseC ? "base" : ""}" style="${tone(v)}">${price(v)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}

const tile = (l, v, sub = "") => `<div class="tile"><div class="label">${esc(l)}</div><div class="value">${v}</div>${sub ? `<div class="delta">${esc(sub)}</div>` : ""}</div>`;

function wholeFirmCard(r) {
  const d = r?.details;
  if (!d) return "";
  const g = d.sensitivity, P = d.projection, n = P.length, rg = d.range;
  const idx = [...new Set([1, 2, 3, 4, 5, 10, n].filter((y) => y <= n))];
  const base = state.dcf?.details?.base_period;
  const row = (name, f, o) => finRow(name, idx.map((y) => cellOf(acct(f(P[y - 1])))), o);
  return `<div class="card"><div class="card-head"><h2>Whole Firm DCF with Synergies</h2><span class="muted small">The standalone DCF with synergies in its drivers</span></div>
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
    <p class="legend-note">Range: conservative = realized ${pct(-rg.steps.realized, true)} and growth ${pct(-rg.steps.revenue_growth_add)}; aggressive the reverse (the course's sensitivity table).
      Terminal ROIC ${pct(d.terminal?.roic)} · terminal value ${pct(d.terminal_value_share)} of EV · WACC ${pct(d.rates.wacc)} (terminal ${pct(d.rates.wacc_terminal)}).${r.notes?.length ? " " + esc(r.notes.map(sentence).join(" ")) : ""}</p></div>`;
}

function justSynergyCard(r) {
  const d = r?.details;
  if (!d) return "";
  const g = d.sensitivity, rg = d.range, Y = d.years;
  const baseRow = g.cost_forever.findIndex((f) => Math.abs(f - d.synergies.cost_forever) < 1e-9);
  return `<div class="card"><div class="card-head"><h2>Just Synergies</h2><span class="muted small">Pre-announcement price + the synergies' DCF value per share</span></div>
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
    <p class="legend-note">Year 0 is the closing year (not discounted). Cost synergies phase in over ${d.synergies.years_to_full} years then grow with revenue (${pct(d.growth)});
      revenue synergies are ${pct(d.synergies.revenue_pct_of_cost)} of cost synergies and last; only ${pct(d.synergies.cost_forever)} of cost synergies enter the terminal value.
      Range: annual synergies ${pct(-rg.steps.annual_cost, true)} / +${pct(rg.steps.annual_cost, true)}.</p></div>`;
}

// ---- prior deals (transaction comps) ------------------------------------------------------

function savedDeals() {
  try { return JSON.parse(deviceAssumptions()[`${state.company.ticker}/precedents.json`] || "null"); } catch { return null; }
}

const CHOICES = { 0: "Best deals for standalone, all deals for the offer (course default)", 1: "Best deals only", 2: "All deals only" };
const xm = (v) => (fin(v) ? `${v.toFixed(1)}x` : NA);

function priorDealsCard(r, demo) {
  const d = r?.details, mine = savedDeals();
  const choice = mine?.choice ?? d?.choice ?? 0;
  const best = new Set(d?.best || []);
  const inputs = `<div class="form-grid">
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
      (SDC uses $ millions); only ratios cross over to ${esc(state.company.ticker)}. Mark the most comparable deals in a "Best" column or tick them below.</p>`;
  if (!d) return `<div class="card"><div class="card-head"><h2>Prior Deals (Transaction Comps)</h2><span class="muted small">Upload the deals to compare against</span></div>${inputs}</div>`;
  const deals = d.deals, c = d.central, b = d.best_rows, t = d.target;
  const st = (k, q, f) => f(c.stats[k]?.[q]);
  const qs = [["mean", "Mean"], ["min", "Minimum"], ["q1", "1st Quartile"], ["median", "Median"], ["q3", "3rd Quartile"], ["max", "Maximum"]];
  const rowNames = { pre_sales: "Pre-announcement EV/Sales", pre_ebitda: "Pre-announcement EV/EBITDA", tx_sales: "Transaction EV/Sales",
    tx_ebitda: "Transaction EV/EBITDA", premium: "Premium Paid" };
  const rng = (x) => (x ? x.map((v) => `<td>${price(v)}</td>`).join("") : `<td colspan="3" class="na">${NA}</td>`);
  return `<div class="card"><div class="card-head"><h2>Prior Deals (Transaction Comps)</h2>
      <span class="muted small">${deals.length} deals · ${best.size} most comparable · target ${price(t.price)}, EV/Sales ${xm(t.ev_sales)}, EV/EBITDA ${xm(t.ev_ebitda)}</span></div>
    ${inputs}
    <h3 style="margin-top:16px">Implied Value per Share</h3>
    <div class="table-wrap"><table class="list deal-sum"><thead><tr><th></th><th colspan="3">Best Deals: Lowest · Average · Highest</th>
      <th colspan="3">All Deals: Central Tendency</th></tr></thead><tbody>
      ${Object.entries(rowNames).map(([k, n]) => `<tr><td>${n}</td>${rng(b.ranges[k])}${rng(c.ranges[k])}</tr>`).join("")}
    </tbody></table></div>
    <p class="legend-note">Central tendency: premium at the 1st quartile, median and 3rd quartile; multiples at the ${pct(c.percentiles.ev_sales[1], true)} (EV/Sales) and
      ${pct(c.percentiles.ev_ebitda[1], true)} (EV/EBITDA) percentile ±10 points, where ${esc(state.company.ticker)}'s own multiples rank among the deals' pre-announcement multiples.
      Best deals rebuild each deal's EV from offer × shares + net debt.${r.notes?.length ? " " + esc(r.notes.map(sentence).join(" ")) : ""}</p>
    <h3 style="margin-top:16px">All Deals</h3>
    <div class="table-wrap"><table class="list deal-sum"><thead><tr><th></th><th>Premium</th><th>Trans. EV/Sales</th><th>Trans. EV/EBITDA</th>
      <th>Pre-ann. EV/Sales</th><th>Pre-ann. EV/EBITDA</th><th>EBITDA Margin</th></tr></thead><tbody>
      ${qs.map(([q, n]) => `<tr><td>${n}</td><td>${st("premium", q, pct)}</td><td>${st("tx_ev_sales", q, xm)}</td><td>${st("tx_ev_ebitda", q, xm)}</td>
        <td>${st("pre_ev_sales", q, xm)}</td><td>${st("pre_ev_ebitda", q, xm)}</td><td>${st("ebitda_margin", q, pct)}</td></tr>`).join("")}
    </tbody></table></div>
    <div class="table-wrap" style="margin-top:12px"><table class="list deal-sum" id="pd-table"><thead><tr><th>Best</th><th>Target</th><th>Acquirer</th><th>Year</th>
      <th>Premium</th><th>Trans. EV/Sales</th><th>Trans. EV/EBITDA</th><th>Pre-ann. EV/EBITDA</th><th>EBITDA Margin</th></tr></thead><tbody>
      ${deals.map((x) => `<tr><td><input type="checkbox" value="${esc(x.target)}" ${best.has(x.target) ? "checked" : ""} aria-label="Best: ${esc(x.target)}"></td>
        <td>${esc(x.target)}</td><td class="muted">${esc(x.acquirer || "")}</td><td>${fin(x.year) ? x.year : ""}</td><td>${pct(x.premium)}</td>
        <td>${xm(x.tx_ev_sales)}</td><td>${xm(x.tx_ev_ebitda)}</td><td>${xm(x.pre_ev_ebitda)}</td><td>${pct(x.ebitda_margin)}</td></tr>`).join("")}
    </tbody></table></div>
    <p class="legend-note">Premium = offer over the price 1 week (or 4 weeks, whichever is larger) before the announcement; a negative premium counts as 10% and anything over 100% as 100%.
      Tick the most comparable deals (up to about five) and press Save and Run Prior Deals.</p>
  </div>`;
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
  box.innerHTML = `${inputsCard(d, demo)}
    ${s ? `<div id="deal-sumbox">${fieldCard(s, d) + summaryCard(s, d)}</div>` : `<div class="card empty"><h2>No Deal Run Yet</h2><p>Enter the expected synergies above and press <b>Save and Run Deal</b>.
      The standalone values (DCF, comps, 52-week range) fill the summary's standalone side; the synergy models and prior deals fill the offer side.</p></div>`}
    ${priorDealsCard(state.deal?.precedents, demo)}${wholeFirmCard(state.deal?.dcf_synergy)}${justSynergyCard(state.deal?.just_synergy)}`;
  $("pd-run").onclick = runPriorDeals;
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
    $("deal-sumbox").innerHTML = fieldCard(s, d) + summaryCard(s, d);
    wireSummary(base);
  }); });
  $("dw-save").onclick = async () => {
    try {
      await saveAssumption(`${t}/deal.json`, { ...(currentDeal() || {}), weights: current() });
      setStatus($("dw-status"), { ok: true, msg: "Weights saved on this device." });
    } catch (err) { setStatus($("dw-status"), { ok: false, msg: `Couldn't save: ${err.message}` }); }
  };
}
