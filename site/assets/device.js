import { device } from "./state.js";

// ---- Runs made in this browser ------------------------------------------------------
// The in-browser Run (pyworker.js) returns the visitor's own site-data files. They are kept
// here, in IndexedDB, on this device only: nothing is sent to the site or to GitHub.
const DB = "valuation-device", FILES = "files";

function open() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(FILES);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function tx(mode, work) {
  return open().then((db) => new Promise((resolve, reject) => {
    const t = db.transaction(FILES, mode), out = work(t.objectStore(FILES));
    t.oncomplete = () => { db.close(); resolve(out.result ?? out); };
    t.onerror = t.onabort = () => { db.close(); reject(t.error); };
  }));
}

/** Read everything saved on this device into device.files ({path under data/: text}). */
export async function loadDevice() {
  try {
    const files = {};
    await tx("readonly", (os) => {
      const req = os.openCursor();
      req.onsuccess = () => { const c = req.result; if (c) { files[c.key] = c.value; c.continue(); } };
      return {};
    });
    device.files = files;
  } catch { device.files = {}; }       // private window or storage blocked: nothing saved
  return device.files;
}

/** Replace this device's files with a run's output (which already includes the earlier runs). */
export async function saveDevice(files) {
  await tx("readwrite", (os) => { os.clear(); for (const [k, v] of Object.entries(files)) os.put(v, k); return {}; });
  device.files = { ...files };
}

export async function clearDevice() {
  await tx("readwrite", (os) => { os.clear(); return {}; });
  device.files = {};
}

/** The device's index.json, or null when nothing has been run here. */
export function deviceIndex() {
  try { return device.files["index.json"] ? JSON.parse(device.files["index.json"]) : null; } catch { return null; }
}

// ---- The engine: Python in a web worker (Pyodide) ------------------------------------
let worker = null, seq = 0;
const waiting = new Map();

/** Run one ticker in this browser. onProgress gets short status lines. Resolves to {report, files}. */
export function runHere({ ticker, asOf, models, proxy }, onProgress) {
  if (!worker) {
    worker = new Worker(new URL("./pyworker.js", import.meta.url));
    worker.onmessage = (e) => {
      const w = waiting.get(e.data.id);
      if (!w) return;
      if (e.data.progress) { w.onProgress?.(e.data.progress); return; }
      waiting.delete(e.data.id);
      e.data.ok ? w.resolve(JSON.parse(e.data.out)) : w.reject(new Error(e.data.error));
    };
    worker.onerror = (e) => { for (const w of waiting.values()) w.reject(new Error(e.message || "the engine failed to load")); waiting.clear(); worker = null; };
  }
  const id = ++seq;
  return new Promise((resolve, reject) => {
    waiting.set(id, { resolve, reject, onProgress });
    worker.postMessage({ id, ticker, asOf, models, proxy, saved: device.files });
  });
}
