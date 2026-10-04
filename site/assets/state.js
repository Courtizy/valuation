

export const $ = (id) => document.getElementById(id);
export const state = { root: "data/", demoMode: false, index: null, concepts: {}, company: null, run: null, detail: null, comparison: null, scn: "p50", companies: null,
                view: "annual", fw: "reformulated", tab: "company", sector: null, sectorMeta: null,
                secSort: { key: "revenue", dir: -1 } };

// ---------------------------------------------------------------- storage

export const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { v === null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch { /* ignore */ } },
};

// ---------------------------------------------------------------- data

export async function getJSON(path) {
  const r = await fetch(path, { cache: "no-cache" });
  if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
  return r.json();
}

export function banner(msg) {
  const b = $("banner");
  b.hidden = !msg;
  b.textContent = msg || "";
}
