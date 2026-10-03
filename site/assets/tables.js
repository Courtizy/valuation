import { NA, esc, fin } from "./format.js";
import { $ } from "./state.js";

// ---- financial-table formatting ----------------------------------------------
// Statement look: indented components, costs as deductions in parentheses,
// shaded bands on subtotals and totals. Positives reserve the ")" width so digits line up.
export function acct(v, { digits = 1, scale = 1e6 } = {}) {
  if (!fin(v)) return NA;
  const x = scale === 1e6 && Math.abs(v) < 5e4 ? 0 : v / scale;
  const body = Math.abs(x).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  const neg = x < 0 && body !== (0).toFixed(digits);
  return `<span class="${neg ? "an" : "ap"}">${neg ? `(${body})` : body}</span>`;
}
// One row of a financial table. kind: item | head | sub (shaded band) | grand (stronger accent band)
// | key (bold, no band) | memo (muted italic). cells: [{html, cls}]
export function finRow(lbl, cells, { kind = "item", indent = 0, title = "" } = {}) {
  const cls = [kind !== "item" ? kind : "", indent ? `i${indent}` : ""].filter(Boolean).join(" ");
  return `<tr${cls ? ` class="${cls}"` : ""}><td${title ? ` title="${esc(title)}"` : ""}>${lbl}</td>${cells.map((c) =>
    `<td${c.cls ? ` class="${c.cls}"` : ""}>${c.html}</td>`).join("")}</tr>`;
}
export const cellOf = (html, extra = "") => ({ html, cls: [html === NA ? "na" : "", extra].filter(Boolean).join(" ") });
