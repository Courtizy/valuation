// Data notes: the engine's build warnings (company_detail.json "warnings"), shown as a quiet,
// collapsible note next to the result instead of a banner above the page. Display only: the
// wording is translated into plain English, and any message not recognized here is shown as written.
import { esc } from "./format.js";

const CHECKS = {
  "balance sheet balances": "total assets didn't equal liabilities plus equity",
  "gross profit ties": "filed gross profit didn't equal revenue minus cost of sales",
  "net income split ties": "net income didn't equal the parent's share plus the minority interest",
};

/** One warning string from the engine -> one or more plain-English notes. */
export function plainNotes(warning) {
  if (warning.startsWith("interest not tagged in the latest year"))
    return ["The latest annual filing doesn't tag interest expense or income, so net financing expense is set to zero in the operating vs. financing ratios (RNOA, ROCE)."];
  if (warning.startsWith("no four contiguous quarters"))
    return ["The quarterly filings have a gap, so there is no trailing-twelve-month (LTM) view."];
  if (warning.startsWith("no 12-month periods found"))
    return ["No full-year periods were found in the filings, so the annual analysis is empty."];
  if (warning.startsWith("filings don't tie out: ")) {
    return warning.slice("filings don't tie out: ".length).split("; ").map((part) => {
      const m = part.match(/^(.+?) in (\d+) of (\d+) periods$/);
      if (!m || !CHECKS[m[1]]) return `A filed subtotal doesn't match its parts: ${part}.`;
      return `In ${m[2]} of ${m[3]} filed periods, ${CHECKS[m[1]]}. The model keeps the figures as filed.`;
    });
  }
  return [warning.charAt(0).toUpperCase() + warning.slice(1) + (/[.!?]$/.test(warning) ? "" : ".")];
}

/** A collapsed "Data notes (n)" disclosure, or "" when the build had no warnings. */
export function dataNotesHTML(warnings) {
  const notes = (warnings || []).flatMap(plainNotes);
  if (!notes.length) return "";
  return `<details class="data-notes">
    <summary>Data notes (${notes.length})</summary>
    <ul>${notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>
  </details>`;
}
