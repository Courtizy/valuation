// Guided tour of the demo: each step switches to the right tab and company, opens the section,
// highlights it and explains what it shows. Keyboard: ← → to move, Esc to close.
import { $, state } from "./state.js";
import { esc } from "./format.js";

let selectCompany = null;          // injected by main.js (avoids a circular import)
export function setTourHooks(hooks) { ({ selectCompany } = hooks); }

const tab = (name) => document.querySelector(`.tab[data-tab="${name}"]`)?.click();
const open = (key) => {
  const card = document.querySelector(`.card[data-collapse="${key}"]`);
  if (card?.classList.contains("collapsed")) card.querySelector(".collapse-btn").click();
};
const company = async (t) => {
  if (state.company?.ticker !== t && state.index.companies.some((c) => c.ticker === t)) {
    $("company").value = t;
    await selectCompany(t);
  }
};
const view = (v) => document.querySelector(`#view-seg [data-view="${v}"]`)?.click();

const STEPS = [
  { at: "#company", title: "Pick a Company", go: async () => { tab("company"); await company("DEMO"); view("annual"); },
    text: "Three featured companies show contrasting cases: <b>DEMO</b> (mature manufacturer), <b>DEMOG</b> (high-growth software) and <b>DEMOU</b> (leveraged utility). <b>ZZA–ZZF</b> are DEMO's comps peers. All synthetic, all run through the real pipeline." },
  { at: "#tiles", title: "Key Figures", text: "Latest twelve months from the filings, plus projected revenue growth over 5 and 10 years from the DCF case." },
  { at: "#rev-chart", card: true, title: "Revenue", text: "Reported revenue as an area, the projection dashed, and a Bear–Bull band around it. Hover for each year's growth." },
  { at: "#ret-chart", card: true, title: "Returns", text: "RNOA (operating returns) against ROCE (returns to shareholders). Green shading = leverage adds to shareholder returns; red = it subtracts. The dashed line is the WACC." },
  { at: "#view-seg", title: "Annual · Quarterly · LTM", go: async () => { open("statements"); },
    text: "One switch drives the statements and all four charts. Quarterly Returns use rolling twelve-month ratios so they stay comparable." },
  { at: "#stmt-table", title: "Statements", go: async () => { await company("DEMOU"); view("annual"); open("statements"); },
    text: "Hybrid accounting layout: indents, subtotal bands, deductions in parentheses, estimates shaded. Small marks show provenance: <b>d</b> = derived (Q4 = year − 9 months), <b>y</b> = missing from the filings and filled from Yahoo (DEMOU's D&amp;A for two years)." },
  { at: "#ratio-seg", title: "Ratios", go: async () => { open("ratios"); },
    text: "Five frameworks: reformulated (operating vs financing), managerial balance sheet, traditional, risk (Altman Z, credit) and accounting signals." },
  { at: "#sector-levels", title: "Sector › Group › Industry", go: async () => { await company("DEMO"); open("sector"); },
    text: "The company's whole sector is screened from SEC data, then narrowed by level. Counts show how many companies each level holds; the benchmarks and charts below follow your choice." },
  { at: "#bench-card", title: "Relative Performance", text: "Each figure against the sector's quartiles: the bar is Q1–Q3, the line the median, the dot this company. Green and red mark favourable and unfavourable gaps." },
  { at: "#sector-card", title: "Companies", text: "Growth vs margin scatter (dot size = revenue), a revenue ranking and a sortable table. Click a company to open it, or build its detail if it only has screen figures." },
  { at: "#val-head", title: "Value vs. Price", go: async () => { await company("DEMO"); tab("valuation"); },
    text: "The blended value for the scenario you pick, against the share price. The line under the price says where it came from and whether the backup source agreed (<i>Checked against Alpha Vantage</i>)." },
  { at: "#val-ff", title: "Football Field", text: "Each method's Bear–Base–Bull range, weight and reason, plus the blend. Switch Bear / Base / Bull at the top right. Precedents is tagged Illustrative until that model is built." },
  { at: "#val-profile", title: "Company Profile", text: "Four measured traits (stage, cash-flow predictability, asset intensity, capital structure) decide which method leads and the default weights, with the reason spelled out." },
  { at: "#val-comps", title: "Public Comps", text: "Every peer's implied price on each multiple as a dot, with the range and median. DEMO is compared with six detailed peers and one hand-entered company." },
  { at: "#val-peers", title: "Peer Picker", text: "Peers ranked by similarity within the sector level you choose. On your own data, Save Peers writes comps.json to your repo and Run Comps starts the pipeline (saving is off in the demo)." },
  { at: "#val-dcf", title: "DCF", text: "Enterprise-to-equity bridge, discount rates (beta unlevered and relevered, WACC now and in the terminal year), the projection and a WACC × terminal-growth sensitivity grid." },
  { at: "#val-head", title: "Implied Mode and a Price Flag", go: async () => { await company("DEMOG"); tab("valuation"); },
    text: "DEMOG runs in <b>implied mode</b>: the DCF solves the growth the price implies. Its price line shows a <b>red flag</b>: the backup source's close differs by more than 2%." },
  { at: "#val-dcf", title: "Default Assumptions", go: async () => { await company("DEMOU"); tab("valuation"); },
    text: "DEMOU has no dcf.json, so the DCF runs on the <b>default case</b> from its own data (tagged on the card). Its price came from the backup source because the primary was unavailable." },
  { at: "#val-similar", title: "Similar Companies", text: "Every published company ranked by closeness on growth, margins, cash-flow stability, capital intensity, leverage and size; weak matches are hidden." },
  { at: "#run-form", title: "Run It on a Real Company", go: async () => { tab("run"); },
    text: "Pick a ticker, tick Company Details and the models, and the GitHub action runs the pipeline and publishes the results here. Press <b>Exit Demo</b> at the top to see your own data." },
];

let i = -1, box = null, focused = null;

function target(step) {
  const el = document.querySelector(step.at);
  return step.card ? el?.closest(".card") || el : el;
}

async function show(n) {
  i = Math.max(0, Math.min(STEPS.length - 1, n));
  const step = STEPS[i];
  if (step.go) await step.go();
  await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  focused?.classList.remove("tour-focus");
  focused = target(step);
  if (focused) {
    focused.classList.add("tour-focus");
    focused.scrollIntoView({ behavior: "smooth", block: "center" });
  }
  box.innerHTML = `<div class="tour__count">${i + 1} of ${STEPS.length}</div>
    <h3 class="tour__title">${esc(step.title)}</h3><p class="tour__text">${step.text}</p>
    <div class="tour__actions"><button type="button" data-t="close">Close</button><span class="spacer"></span>
      <button type="button" data-t="back" ${i === 0 ? "disabled" : ""}>Back</button>
      <button type="button" class="primary" data-t="next">${i === STEPS.length - 1 ? "Finish" : "Next"}</button></div>`;
  box.querySelector('[data-t="next"]').focus({ preventScroll: true });
}

function close() {
  focused?.classList.remove("tour-focus");
  box?.remove();
  box = null; i = -1;
  document.removeEventListener("keydown", onKey);
}

function onKey(e) {
  if (e.key === "Escape") close();
  else if (e.key === "ArrowRight") show(i + 1);
  else if (e.key === "ArrowLeft" && i > 0) show(i - 1);
}

export function startTour() {
  if (box) return;
  box = document.createElement("div");
  box.className = "tour";
  box.setAttribute("role", "dialog");
  box.setAttribute("aria-label", "Guided tour");
  box.onclick = (e) => {
    const t = e.target.closest("button")?.dataset.t;
    if (t === "close") close();
    else if (t === "back") show(i - 1);
    else if (t === "next") (i === STEPS.length - 1 ? close() : show(i + 1));
  };
  document.body.appendChild(box);
  document.addEventListener("keydown", onKey);
  show(0);
}
