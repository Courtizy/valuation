import { PROXY_URL } from "./config.js";
import { clearDevice, deviceIndex, runHere, saveDevice } from "./device.js";
import { actionsUrl, dispatchPipeline, gh, setStatus } from "./github.js";
import { esc } from "./format.js";
import { $, state, store } from "./state.js";

let showDevice = null, route = null;    // injected by main.js (avoids a circular import)
export function setRunHooks(hooks) { ({ showDevice, route } = hooks); }

// ---- Run in this browser (anyone) -------------------------------------------------
const proxyUrl = () => ($("h-proxy").value.trim() || PROXY_URL).replace(/\/+$/, "");
const avKey = () => $("h-avkey").value.trim();

/** Where Run Comps, Save Peers, Screen and Build go: GitHub only for the owner (a token is set)
 *  working on a published company; everyone else, and every company run here, uses this browser. */
export const useGitHub = () => !!gh().token && !state.company?.device;

function renderSaved() {
  const list = deviceIndex()?.companies || [], sectors = deviceIndex()?.sectors || [];
  const what = [...list.map((c) => `<b>${esc(c.ticker)}</b> (${c.runs.length} run${c.runs.length > 1 ? "s" : ""})`),
    ...sectors.map((x) => `<b>${esc(x.label || x.id)}</b> screen`)];
  $("h-saved").innerHTML = what.length
    ? `Saved on this device: ${what.join(", ")}. <button type="button" class="linkish" id="h-clear">Clear</button>`
    : '<span class="muted">Nothing saved on this device yet.</span>';
  const clear = $("h-clear");
  if (clear) clear.onclick = async () => {
    if (!confirm("Remove every run, sector screen and peer list saved in this browser?")) return;
    await clearDevice(); renderSaved(); await showDevice?.(null);
  };
}

/** Run a company ({ticker, models}) or screen a sector ({sector}) in this browser, keep it on
 *  this device and open it. Progress and the outcome go to the status element. */
export async function runInBrowser(job, status) {
  const asOf = job.asOf || new Date().toISOString().slice(0, 10);
  if (!proxyUrl()) { setStatus(status, { ok: false, msg: "The data proxy isn't set up: add its URL on the Run page under Settings." }); return false; }
  status.className = "status"; status.textContent = "Starting…";
  try {
    const out = await runHere({ ...job, asOf, proxy: proxyUrl(), avKey: job.sector ? "" : avKey() }, (msg) => { status.textContent = msg; });
    const failed = out.report.filter(([, st]) => st === "failed");
    const built = job.sector ? !failed.length : !!out.files[`${job.ticker}/${asOf}/company_detail.json`];
    if (!built) throw new Error(failed.map(([step, , msg]) => `${step}: ${msg}`).join("; ") || "nothing was built");
    await saveDevice(out.files);
    renderSaved();
    setStatus(status, { ok: !failed.length, msg: failed.length
      ? `Done, with problems: ${failed.map(([step, , msg]) => `${step} (${msg})`).join("; ")}`
      : `Done. ${job.sector ? "The screen" : job.ticker} is saved on this device.` });
    await showDevice?.(job.sector ? null : job.ticker);
    return true;
  } catch (err) {
    setStatus(status, { ok: false, msg: `Run failed: ${err.message}` });
    return false;
  }
}

export function setupHereForm() {
  $("h-proxy").value = store.get("proxy_url") || "";
  $("h-avkey").value = store.get("av_key") || "";
  $("h-asof").value = new Date().toISOString().slice(0, 10);
  renderSaved();
  const remember = () => {
    store.set("proxy_url", $("h-proxy").value.trim() || null);
    store.set("av_key", avKey() || null);
  };
  $("h-proxy").onchange = $("h-avkey").onchange = remember;
  const busy = async (btn, work) => { btn.disabled = true; try { await work(); } finally { btn.disabled = false; } };
  $("here-form").onsubmit = (e) => {
    e.preventDefault();
    remember();
    const ticker = $("h-ticker").value.trim().toUpperCase();
    if (!/^[A-Z][A-Z0-9.\-]{0,9}$/.test(ticker)) { setStatus($("h-status"), { ok: false, msg: "Enter a valid ticker." }); return; }
    busy($("h-go"), () => runInBrowser({ ticker, asOf: $("h-asof").value, models: "auto" }, $("h-status")));
  };
  $("h-screen").onclick = () => {
    remember();
    busy($("h-screen"), () => runInBrowser({ sector: `sector:${$("h-sector").value}`, asOf: $("h-asof").value }, $("h-status")));
  };
}

// ---- Publish to the site (owner) -------------------------------------------------------------
export function repoGuess() {
  const h = location.hostname;
  if (h.endsWith(".github.io")) return { owner: h.split(".")[0], repo: location.pathname.split("/").filter(Boolean)[0] || `${h}` };
  return { owner: "", repo: "valuation" };
}

export function runMode() { return document.querySelector("#r-mode [aria-pressed=true]")?.dataset.mode || "company"; }

/** Fill the Sector list from the taxonomy (called once it has loaded). */
export function fillSectorList() {
  if (!state.taxonomy) return;
  const opts = state.taxonomy.sectors.map((x) => `<option value="${esc(x.id)}">${esc(x.name)}</option>`).join("");
  for (const id of ["r-sector-id", "h-sector"]) if ($(id)) $(id).innerHTML = opts;
}

export function setupRunForm() {
  const g = repoGuess();
  $("r-owner").value = store.get("gh_owner") || g.owner;
  $("r-repo").value = store.get("gh_repo") || g.repo;
  const tok = store.get("gh_token");
  if (tok) { $("r-token").value = tok; $("r-remember").checked = true; }
  const today = new Date().toISOString().slice(0, 10);
  $("r-asof").value = today; $("r-sasof").value = today;

  document.querySelectorAll("#r-mode button").forEach((b) => b.onclick = () => {
    document.querySelectorAll("#r-mode button").forEach((x) => x.setAttribute("aria-pressed", x === b));
    $("r-company").hidden = b.dataset.mode !== "company"; $("r-sector").hidden = b.dataset.mode !== "sector";
    refresh();
  });
  $("r-skind").onchange = () => {
    document.querySelectorAll("#r-sector [data-for]").forEach((f) => { f.hidden = f.dataset.for !== $("r-skind").value; });
    refresh();
  };
  // models need company details, so picking one locks that box on
  const syncDetail = () => {
    const anyModel = !!document.querySelector("#r-models input:checked");
    if (anyModel) $("r-detail").checked = true;
    $("r-detail").disabled = anyModel;
    $("r-run-hint").textContent = anyModel ? "Models use the company details, so those are rebuilt too." : "";
  };
  $("r-models").addEventListener("change", syncDetail);
  syncDetail();                                       // DCF is ticked by default

  const refresh = () => {
    syncDetail();
    const gg = gh(), i = runInputs();
    $("r-actions-link").href = gg.owner && gg.repo ? `${actionsUrl(gg)}/workflows/pipeline.yml` : "https://github.com";
    const flags = Object.entries(i).filter(([, v]) => v !== "").map(([k, v]) => `-f ${k}=${/\s|;/.test(v) ? `"${v}"` : v}`).join(" ");
    $("r-cli").textContent = `gh workflow run pipeline.yml${gg.owner && gg.repo ? ` -R ${gg.owner}/${gg.repo}` : ""} \\\n  ${flags}`;
  };
  $("run-form").addEventListener("input", refresh);
  $("run-form").addEventListener("change", refresh);
  refresh();

  $("run-form").onsubmit = async (e) => {
    e.preventDefault();
    const status = $("r-status");
    store.set("gh_owner", $("r-owner").value.trim()); store.set("gh_repo", $("r-repo").value.trim());
    store.set("gh_token", $("r-remember").checked && $("r-token").value.trim() ? $("r-token").value.trim() : null);
    const i = runInputs();
    const bad = runInputsError(i);
    if (bad) { setStatus(status, { ok: false, msg: bad }); return; }
    status.className = "status"; status.textContent = "Starting…";
    try { setStatus(status, await dispatchPipeline(i)); } catch (err) { setStatus(status, { ok: false, msg: `Request failed: ${err.message}` }); }
  };
}

// Inputs for the Pipeline workflow. Company mode: company details alone = through L1;
// any model ticked = through L2 with those models. Sector mode: one sector spec.
export function runInputs() {
  if (runMode() === "sector") {
    const kind = $("r-skind").value;
    let spec = "";
    if (kind === "sic") spec = `sic:${$("r-sic").value.trim()}`;
    if (kind === "sector") spec = `sector:${$("r-sector-id").value}`;
    if (kind === "sic-of") spec = `sic-of:${$("r-sicof").value.trim().toUpperCase()}`;
    if (kind === "list") spec = `list:${$("r-list").value.trim()}`;
    if (kind === "traits") spec = "traits:" + [...document.querySelectorAll("#r-sector [data-trait]")]
      .filter((x) => x.value).map((x) => `${x.dataset.trait}=${x.value}`).join(";");
    return { sector: spec, as_of: $("r-sasof").value };
  }
  const models = [...document.querySelectorAll("#r-models input:checked")].map((x) => x.value);
  return { ticker: $("r-ticker").value.trim().toUpperCase(), as_of: $("r-asof").value,
           models: models.join(",") || "dcf", stop_after: models.length ? "L2" : "L1" };
}

export function runInputsError(i) {
  if (i.sector !== undefined) {
    if (/^sector:[a-z_]{3,30}$|^sic:\d{4}$|^sic-of:[A-Z][A-Z0-9.\-]{0,9}$|^list:[A-Za-z0-9_\-]{1,40}$|^traits:[a-z_]+=[a-z ]+(;[a-z_]+=[a-z ]+)*$/.test(i.sector)) return "";
    return i.sector.startsWith("traits:") ? "Pick at least one trait." : "Fill in the sector field (SIC is 4 digits; a list name uses letters, digits, _ and -).";
  }
  if (!/^[A-Za-z][A-Za-z0-9.\-]{0,9}$/.test(i.ticker)) return "Enter a valid ticker.";
  if (!$("r-detail").checked) return "Tick Company details or a model.";
  return "";
}
