// Overview and Method pages. Every number shown comes from the engine's JSON (dcf.json,
// changelog.json); this file only lays it out.
import { esc, fin, pct, price } from "./format.js";
import { $, getJSON, state } from "./state.js";

const repoUrl = () => {
  const h = location.hostname, first = location.pathname.split("/").filter(Boolean)[0];
  return h.endsWith(".github.io") && first ? `https://github.com/${h.split(".")[0]}/${first}` : "https://github.com/Courtizy/valuation";
};

/** The headline numbers for the selected company, from the DCF's simulation block. */
export function simulationSummary() {
  const s = state.dcf?.details?.simulation;
  if (!s?.per_share) return null;
  return { low: s.middle_90[0], high: s.middle_90[1], median: s.per_share.p50, tv: s.terminal_value_share,
    runs: s.runs, used: s.runs_used, seed: s.seed, inputs: s.inputs };
}

// ---------------------------------------------------------------- overview

export function renderOverview() {
  const body = $("ov-body");
  if (!body || state.tab !== "overview") return;
  const s = simulationSummary(), co = state.company;
  const headline = s
    ? `<span class="eyebrow">Headline · ${esc(co.ticker)}${co.demo ? " (synthetic)" : ""}</span>
       <span class="ov-range num">${price(s.low)}–${price(s.high)}</span>
       <span>per share, middle 90% of simulated outcomes</span>
       <span class="muted small">Median ${price(s.median)} · terminal value ${pct(s.tv)} of total · ${s.used.toLocaleString()} runs</span>`
    : `<span class="eyebrow">Headline</span>
       <span class="ov-range num muted">[$L–$H]</span>
       <span>per share, middle 90% of simulated outcomes</span>
       <span class="muted small">${co ? `No DCF has run for ${esc(co.ticker)} yet.` : "No company published yet. Press Demo to see one."}</span>`;
  body.innerHTML = `
    <div class="ov-hero">
      <div class="ov-lead">
        <span class="eyebrow">03 · Deals</span>
        <h2 class="ov-title">A valuation is a range, not a number.</h2>
        <p class="ov-text">This model builds a company's financials from public filings, values it three standard ways, and runs the key assumptions thousands of times to show where the value really sits and what drives it.</p>
        <div class="ov-actions"><a class="btn primary" href="#valuation">See results</a><a class="btn" href="#method">How it works</a></div>
      </div>
      <div class="ov-card">${headline}
        <span class="muted small ov-disclaimer">Analysis of method, not investment advice.</span></div>
    </div>
    <section class="ov-section"><span class="eyebrow">How it works</span>
      <div class="ov-steps">
        ${step("01", "Normalize the filings", "SEC statements mapped to one consistent set of line items, with balance and tie-out checks on every run.")}
        ${step("02", "Value it three ways", "Discounted cash flow, trading comparables and precedent deals (precedents illustrative until that model is built).")}
        ${step("03", "Simulate the range", "Near-term growth, discount rate and terminal growth drawn as ranges, 2,000 seeded runs; then reconcile where the methods disagree.")}
      </div>
    </section>
    <div class="ov-pair">
      <div class="ov-box"><h3>What it can't tell you</h3>
        <p>It's analysis of method, not a buy or sell call. Built for non-financial operating companies; banks, REITs and biotech need different frameworks. Terminal value often dominates, so the range is only as good as the long-run assumptions.</p></div>
      <div class="ov-box"><h3>Built on</h3>
        <p>Public SEC filings (XBRL company facts), the FRED 10-year Treasury rate and a pure-Python engine. Runs privately as a Python app; this page shows precomputed results.</p>
        <a href="${repoUrl()}" target="_blank" rel="noopener">Code on GitHub</a></div>
    </div>`;
}

const step = (n, title, text) => `<div class="ov-step"><span class="ov-step__n num">${n}</span><b>${title}</b><span class="muted">${text}</span></div>`;

// ---------------------------------------------------------------- method

const SECTIONS = [["m-problem", "Problem"], ["m-inputs", "Inputs and sources"], ["m-model", "The model"],
  ["m-validation", "Validation"], ["m-limits", "Limits"], ["m-changelog", "Changelog"]];

const INPUTS = [
  ["Financial statements", "Normalized line items, annual / quarterly / LTM", "SEC EDGAR company facts (XBRL)"],
  ["Industry", "SIC code → sector › group › industry", "SEC EDGAR submissions"],
  ["Sector benchmarks", "Quartiles across the sector", "SEC frames API"],
  ["Risk-free rate", "10-year Treasury yield", "FRED (DGS10)"],
  ["Near-term growth, margins", "Triangular range around a stated case", "Company history or configs/public/assumptions"],
  ["Discount rate (WACC)", "Triangular range around the built-up rate", "Sector illustrative beta, book or target D/E"],
  ["Share price, peer prices", "Not published here (data terms)", "Synthetic in the Demo; private runs only otherwise"],
  ["Peer set", "Hand-picked or ranked by similarity", "configs/public/assumptions/{ticker}/comps.json"],
];

const MODEL = [
  ["Normalize", "Map each filing's tags to one canonical set of line items; derive Q4 and LTM; check that the balance sheet balances and subtotals tie."],
  ["Value", "DCF on a three-statement projection, trading comparables on the peer range, precedents (illustrative). Each method has its own range."],
  ["Simulate", "2,000 seeded runs over near-term growth, WACC and terminal growth. Runs where the terminal WACC isn't above growth are dropped. The middle 90% is the headline range."],
  ["Reconcile", "Weights follow the company's measured profile (stage, predictability, asset intensity, leverage); the football field shows each range and why they differ."],
];

const VALIDATION = [
  ["Projected statements balance and cash ties", "Done", "Unit tests on every build"],
  ["Normalized statements tie to reported totals", "Done", "Balance, gross profit and net income checks run with every normalization"],
  ["Simulation is seeded and reproducible", "Done", "Same inputs and seed give the same numbers"],
  ["Ratios, DCF and comps match the course workbooks", "Done locally", "Parity tests need the workbooks, so they're skipped in CI"],
  ["Shared math imports nothing else from the app", "Done", "Enforced by a test until it moves to Shared Core"],
  ["Live runs reviewed on real tickers against published estimates", "Planned", ""],
  ["Parity and seeded-run suites in CI", "Planned", ""],
];

export async function renderMethod() {
  const body = $("method-body");
  if (!body || state.tab !== "method") return;
  if (!body.dataset.ready) {
    body.dataset.ready = "1";
    body.innerHTML = `<div class="method">
      <nav class="method-nav" aria-label="On this page">${SECTIONS.map(([id, t]) => `<a href="#${id}" data-jump="${id}">${t}</a>`).join("")}</nav>
      <div class="method-main">
        <section id="m-problem" class="card"><h2>Problem</h2>
          <p>Most valuations end in one number, but every input behind it is an estimate. A decision-maker needs the range of reasonable values, and which assumptions move it most.</p></section>
        <section id="m-inputs" class="card"><h2>Inputs and sources</h2>
          <div class="table-wrap"><table class="list"><thead><tr><th>Input</th><th>Form</th><th>Source</th></tr></thead>
          <tbody>${INPUTS.map((r) => `<tr>${r.map((c) => `<td>${esc(c)}</td>`).join("")}</tr>`).join("")}</tbody></table></div></section>
        <section id="m-model" class="card"><h2>The model</h2>
          <div class="ov-steps">${MODEL.map(([t, x], i) => step(String(i + 1).padStart(2, "0"), t, x)).join("")}</div></section>
        <section id="m-validation" class="card"><h2>Validation</h2>
          <ul class="checklist">${VALIDATION.map(([t, st, note]) => `<li><span class="vstat ${st === "Planned" ? "planned" : "done"}">${st}</span>
            <span><b>${esc(t)}</b>${note ? `<span class="muted small"> · ${esc(note)}</span>` : ""}</span></li>`).join("")}</ul></section>
        <section id="m-limits" class="card"><h2>Limits</h2>
          <p>Analysis of method, not investment advice. Built for non-financial operating companies; banks, insurers, REITs and pre-revenue biotech need different frameworks. US GAAP filers only (no 20-F / IFRS). Terminal value usually carries most of the value, so long-run assumptions matter more than any single year. Precedents are illustrative until that model is built. The public site shows no real market prices.</p></section>
        <section id="m-changelog" class="card"><h2>Changelog</h2><div id="m-changes" class="muted">Loading…</div></section>
      </div></div>`;
    body.querySelectorAll("[data-jump]").forEach((a) => a.onclick = (e) => {
      e.preventDefault(); e.stopPropagation();
      $(a.dataset.jump).scrollIntoView({ behavior: "smooth", block: "start" });
    });
    const log = await getJSON("data/changelog.json").catch(() => null);
    $("m-changes").innerHTML = log?.releases?.length ? log.releases.map((r) => `<div class="release">
        <div><b class="num">${esc(r.version)}</b> <span class="muted small">· ${esc(r.date || "")}</span></div>
        <ul>${(r.items || []).map((i) => `<li>${esc(i)}</li>`).join("")}</ul></div>`).join("")
      : "No changelog published yet.";
  }
}
