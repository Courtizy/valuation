/** Show an outcome ({ok, msg} or {ok, html}) in a status element. */
export function setStatus(el, r) {
  el.className = `status ${r.ok ? "ok" : "err"}`;
  if (r.html) el.innerHTML = r.html; else el.textContent = r.msg;
}
