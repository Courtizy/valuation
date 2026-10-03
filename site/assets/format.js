// Presentation standard: every label, period and number on the site goes through here.
//   Titles, headers, line items, buttons: Title Case (small words lower case).
//   Periods: 2025 (reported fiscal year) · Q3 2026 (fiscal quarter) · LTM Jun 2026 · 2027E (estimate).
//   Numbers: $ millions with one decimal in tables; $5.76B in tiles; percentages one
//   decimal; valuation multiples one decimal ("11.1x"); turnover two ("1.58x").
//   "–" = no data; "NM" = not meaningful (a multiple on a loss or negative base).
import { state } from "./state.js";

export const fin = (v) => typeof v === "number" && Number.isFinite(v);
export const NA = "–";
export const NM = "NM";
const minus = (s) => s.replace("-", "−");

export function money(v, axis = false) {
  if (!fin(v)) return NA;
  const a = Math.abs(v), s = v < 0 ? "−" : "";
  if (a >= 1e12) return `${s}$${(a / 1e12).toFixed(axis ? 1 : 2)}T`;
  if (a >= 1e9) return `${s}$${(a / 1e9).toFixed(axis ? 1 : 2)}B`;
  if (a >= 1e6) return `${s}$${(a / 1e6).toFixed(axis ? 0 : 1)}M`;
  if (a >= 1e3) return `${s}$${(a / 1e3).toFixed(0)}K`;
  return `${s}$${a.toFixed(0)}`;
}
export const millions = (v) => (fin(v) ? minus((Math.abs(v) < 5e4 ? 0 : v / 1e6).toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 })) : NA);
export const pct = (v, axis = false) => (fin(v) ? minus(`${(v * 100).toFixed(axis ? 0 : 1)}%`) : NA);
export const pts = (v) => (fin(v) ? `${v >= 0 ? "+" : "−"}${Math.abs(v * 100).toFixed(1)} pts` : NA);
/** Valuation multiple: one decimal; NM when the base is a loss (negative multiple). */
export const mult = (v) => (!fin(v) ? NA : v < 0 ? NM : `${v.toFixed(1)}x`);
/** First letter capitalised (notes written in sentence case by the Python layers). */
export const sentence = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : "");
/** Turnover and coverage ratios: two decimals, sign kept. */
export const times = (v) => (fin(v) ? minus(`${v.toFixed(2)}x`) : NA);
export const days = (v) => (fin(v) ? `${v.toFixed(1)} Days` : NA);
export const num = (v) => (fin(v) ? minus(v.toFixed(2)) : NA);
export const price = (v, axis = false) => (fin(v) ? `$${v.toFixed(axis ? 0 : 2)}` : NA);

// ---- periods
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export const monthYear = (iso) => `${MONTHS[Number(iso.slice(5, 7)) - 1]} ${iso.slice(0, 4)}`;

/** A reported period: 2025 (fiscal year), Q3 2026 (fiscal quarter), LTM Jun 2026. */
export function periodLabel(p) {
  if (!p) return "";
  if (p.fiscal_period === "FY") return String(p.fiscal_year);
  if (String(p.label).startsWith("TTM") || p.months === 12) return `LTM ${monthYear(p.end)}`;
  return `${p.fiscal_period} ${p.fiscal_year}`;
}

/** Estimate year t (1-based) after a base period: 2027E on a fiscal base, else "Year t". */
export function estLabel(base, t) {
  return base?.kind === "fiscal" && fin(base.fiscal_year) ? `${base.fiscal_year + t}E` : `Year ${t}E`;
}

// ---- words
const SMALL = new Set(["a", "an", "and", "as", "at", "by", "for", "in", "of", "on", "or", "the", "to", "vs", "vs.", "via", "with"]);
const KEEP = new Set(["EBITDA", "EBIT", "EV", "FCF", "CFO", "NOPAT", "NOPLAT", "RNOA", "ROCE", "ROA", "ROE", "WACC", "DCF", "LTM",
  "D&A", "SG&A", "R&D", "EPS", "NOA", "NBC", "FLEV", "OLLEV", "SIC", "TTM", "IPO", "LBO", "NM", "P/E", "EV/EBITDA", "EV/Sales"]);
/** Title Case: capitalise each word except small words (after the first); keep acronyms. */
export function titleCase(s) {
  return String(s ?? "").split(/(\s+|-)/).map((w, i) => {
    if (/^\s+$|^-$/.test(w) || !w) return w;
    if (KEEP.has(w.toUpperCase()) || /[A-Z].*[A-Z]/.test(w)) return KEEP.has(w.toUpperCase()) ? w.toUpperCase() : w;
    const lw = w.toLowerCase();
    if (i > 0 && SMALL.has(lw)) return lw;
    return lw.charAt(0).toUpperCase() + lw.slice(1);
  }).join("");
}

export function esc(s) { return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]); }

/** Concept display name from the registry, in Title Case with "&" for "and". */
export function label(id) {
  const n = state.concepts[id]?.name || id.replace(/_/g, " ");
  return titleCase(n.replace(/\band\b/gi, "&"));
}

/** The one source line every card ends with. */
export const sourceLine = (extra = "") => `<p class="source-line">Source: SEC filings via XBRL${extra ? `; ${esc(extra)}` : ""}.</p>`;
