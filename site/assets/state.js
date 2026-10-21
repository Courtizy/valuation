

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

// Runs made in this browser (device.js) live in IndexedDB under "device/…" paths, never on the site.
export const device = { files: {} };
const DEVICE = "device/";

export async function getJSON(path) {
  if (path.startsWith(DEVICE)) {
    const text = device.files[path.slice(DEVICE.length)];
    if (text === undefined) throw new Error(`${path}: not saved on this device`);
    return JSON.parse(text);
  }
  const r = await fetch(path, { cache: "no-cache" });
  if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
  return r.json();
}

/** Where the selected company's run files live: the site's data, or this device. */
export const runRoot = () => (state.company?.device ? DEVICE : state.root);

/** A link to a data file; device files become a blob URL, since they aren't on the site. */
export function fileHref(path) {
  if (!path.startsWith(DEVICE)) return path;
  const text = device.files[path.slice(DEVICE.length)];
  return text === undefined ? "#" : URL.createObjectURL(new Blob([text], { type: "application/json" }));
}

export function banner(msg) {
  const b = $("banner");
  b.hidden = !msg;
  b.textContent = msg || "";
}
