// ---- section tabs: method detail and reference material behind one tab bar ----------------
// Every panel is rendered up front and hidden, so the renderers that fill panels by id keep
// working; charts in a hidden panel redraw when it opens (their ResizeObserver sees the width).
// The open tab is remembered per tab set in this browser.

const KEY = "tabs";

function remembered(set) {
  try { return JSON.parse(localStorage.getItem(KEY) || "{}")[set] || null; } catch { return null; }
}

function remember(set, key) {
  try {
    const all = JSON.parse(localStorage.getItem(KEY) || "{}");
    all[set] = key;
    localStorage.setItem(KEY, JSON.stringify(all));
  } catch { /* storage blocked: the tab still switches */ }
}

/** A tab bar and its panels. items: [{key, label, html}], items with no html are left out. */
export function tabSet(set, items, { title = "", note = "" } = {}) {
  const live = items.filter((t) => t.html !== null && t.html !== undefined && t.html !== false);
  if (!live.length) return "";
  const open = live.some((t) => t.key === remembered(set)) ? remembered(set) : live[0].key;
  return `<div class="tabset" data-set="${set}">
    <div class="tabset-head">${title ? `<h2 class="tabset-title">${title}</h2>` : ""}
      <div class="seg tabset-bar" role="tablist" aria-label="${title || set}">${live.map((t) =>
        `<button type="button" role="tab" id="tab-${set}-${t.key}" aria-controls="tp-${set}-${t.key}" aria-selected="${t.key === open}"
          aria-pressed="${t.key === open}" data-tab-key="${t.key}">${t.label}</button>`).join("")}</div></div>
    ${note ? `<p class="legend-note">${note}</p>` : ""}
    ${live.map((t) => `<div class="tabset-panel" role="tabpanel" id="tp-${set}-${t.key}" aria-labelledby="tab-${set}-${t.key}" ${t.key === open ? "" : "hidden"}>${t.html}</div>`).join("")}
  </div>`;
}

/** Wire every tab set under root. onOpen(set, key) runs after a panel opens. */
export function wireTabs(root, onOpen) {
  (root || document).querySelectorAll(".tabset").forEach((box) => {
    const set = box.dataset.set;
    const buttons = [...box.querySelectorAll(":scope > .tabset-head [data-tab-key]")];
    const show = (key) => {
      buttons.forEach((b) => { const on = b.dataset.tabKey === key; b.setAttribute("aria-selected", on); b.setAttribute("aria-pressed", on); });
      box.querySelectorAll(":scope > .tabset-panel").forEach((p) => { p.hidden = p.id !== `tp-${set}-${key}`; });
      remember(set, key);
      onOpen?.(set, key);
    };
    buttons.forEach((b, i) => {
      b.onclick = () => show(b.dataset.tabKey);
      b.onkeydown = (e) => {
        const j = e.key === "ArrowRight" ? i + 1 : e.key === "ArrowLeft" ? i - 1 : null;
        if (j === null) return;
        const nb = buttons[(j + buttons.length) % buttons.length];
        nb.focus(); show(nb.dataset.tabKey);
      };
    });
  });
}

/** Open the tab this browser last chose in a tab set written into the page (not by tabSet). */
export function restoreTab(set) {
  const key = remembered(set);
  if (key) document.querySelector(`.tabset[data-set="${set}"] [data-tab-key="${key}"]`)?.click();
}

/** Open a tab by key (the tour and links use it). */
export function openTab(set, key) {
  document.querySelector(`.tabset[data-set="${set}"] [data-tab-key="${key}"]`)?.click();
}
