import { actionsUrl, dispatchPipeline, gh, setStatus } from "./github.js";
import { esc } from "./format.js";
import { $, state, store } from "./state.js";

// ---- Run Pipeline tab ------------------------------------------------------------
export function repoGuess() {
  const h = location.hostname;
  if (h.endsWith(".github.io")) return { owner: h.split(".")[0], repo: location.pathname.split("/").filter(Boolean)[0] || `${h}` };
  return { owner: "", repo: "valuation" };
}

export function runMode() { return document.querySelector("#r-mode [aria-pressed=true]")?.dataset.mode || "company"; }

/** Fill the Sector list from the taxonomy (called once it has loaded). */
export function fillSectorList() {
  const sel = $("r-sector-id");
  if (!sel || !state.taxonomy) return;
  sel.innerHTML = state.taxonomy.sectors.map((x) => `<option value="${esc(x.id)}">${esc(x.name)}</option>`).join("");
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
