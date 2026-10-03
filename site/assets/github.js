import { $, store } from "./state.js";

// ---- GitHub: start a pipeline run, read and write a repo file -----------------
// The token lives only in this browser (and only when "Remember" is ticked).
export function gh() {
  const owner = ($("r-owner").value || store.get("gh_owner") || "").trim();
  const repo = ($("r-repo").value || store.get("gh_repo") || "").trim();
  const token = ($("r-token").value || store.get("gh_token") || "").trim();
  return { owner, repo, token, base: `https://api.github.com/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}` };
}
export const GH_HEADERS = (token) => ({ Accept: "application/vnd.github+json", Authorization: `Bearer ${token}`, "X-GitHub-Api-Version": "2022-11-28" });
export const actionsUrl = (g) => `https://github.com/${encodeURIComponent(g.owner)}/${encodeURIComponent(g.repo)}/actions`;

export async function dispatchPipeline(inputs) {
  const g = gh();
  if (!g.owner || !g.repo) return { ok: false, msg: "Fill in the owner and repository on the Run Pipeline tab." };
  if (!g.token) return { ok: false, noToken: true, msg: "No token: add one on the Run Pipeline tab, or use the Actions page." };
  const res = await fetch(`${g.base}/actions/workflows/pipeline.yml/dispatches`, {
    method: "POST", headers: GH_HEADERS(g.token), body: JSON.stringify({ ref: "main", inputs }) });
  if (res.status === 204) return { ok: true, html: `Started. <a href="${actionsUrl(g)}" target="_blank" rel="noopener">Follow it on GitHub</a>; reload this page when it finishes.` };
  const msg = await res.json().catch(() => ({}));
  return { ok: false, msg: `GitHub said ${res.status}: ${msg.message || "request failed"}` };
}

export const b64encode = (str) => btoa(String.fromCharCode(...new TextEncoder().encode(str)));
export const b64decode = (b64) => new TextDecoder().decode(Uint8Array.from(atob(b64.replace(/\s/g, "")), (c) => c.charCodeAt(0)));

export async function readRepoJSON(path) {
  const g = gh();
  // no-store: GitHub lets browsers cache this for 60 s, and a stale sha makes the next write fail with 409
  const res = await fetch(`${g.base}/contents/${path}?ref=main`, { headers: GH_HEADERS(g.token), cache: "no-store" });
  if (res.status === 404) return { sha: null, doc: null };
  if (!res.ok) throw new Error(`GitHub said ${res.status} reading ${path}`);
  const j = await res.json();
  return { sha: j.sha, doc: JSON.parse(b64decode(j.content)) };
}

export async function writeRepoJSON(path, doc, sha, message) {
  const g = gh();
  const res = await fetch(`${g.base}/contents/${path}`, {
    method: "PUT", headers: GH_HEADERS(g.token),
    body: JSON.stringify({ message, content: b64encode(JSON.stringify(doc, null, 2) + "\n"), branch: "main", ...(sha ? { sha } : {}) }) });
  if (!res.ok) {
    const msg = await res.json().catch(() => ({}));
    const err = new Error(res.status === 403
      ? "GitHub said 403: the token needs Contents: read and write on this repository"
      : `GitHub said ${res.status}: ${msg.message || "write failed"}`);
    err.status = res.status;
    throw err;
  }
}

export function setStatus(el, r) {
  el.className = `status ${r.ok ? "ok" : r.noToken ? "" : "err"}`;
  if (r.html) el.innerHTML = r.html; else el.textContent = r.msg;
}
