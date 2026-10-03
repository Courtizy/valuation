// Small SVG charts: columns, lines, ranges. No dependencies.
// Marks: bars <= 24px with a 4px rounded data end, 2px lines, 8px end dots with
// a 2px surface ring, hairline grid. Hover tooltips on every chart.

const NS = "http://www.w3.org/2000/svg";

function el(tag, attrs = {}, parent) {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (parent) parent.appendChild(n);
  return n;
}

function niceTicks(min, max, count = 4) {
  if (min === max) { max = min + 1; }
  const span = max - min;
  const step0 = span / count;
  const mag = 10 ** Math.floor(Math.log10(step0));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= step0);
  const lo = Math.floor(min / step) * step, hi = Math.ceil(max / step) * step;
  const ticks = [];
  for (let v = lo; v <= hi + step / 2; v += step) ticks.push(Math.abs(v) < step / 1e6 ? 0 : v);
  return ticks;
}

function setup(container, height) {
  container.innerHTML = "";
  container.classList.add("chart");
  const width = Math.max(280, container.clientWidth || 600);
  const svg = el("svg", { viewBox: `0 0 ${width} ${height}`, role: "img" }, container);
  const tip = document.createElement("div");
  tip.className = "tooltip";
  container.appendChild(tip);
  return { svg, tip, width, height };
}

function showTip(tip, container, x, y, title, rows) {
  tip.innerHTML = `<div class="t-title">${title}</div>` + rows.map((r) =>
    `<div class="t-row">${r.color ? `<span class="key dot" style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${r.color}"></span>` : ""}<span>${r.label}</span><b>${r.value}</b></div>`).join("");
  tip.style.display = "block";
  const cw = container.clientWidth, tw = tip.offsetWidth;
  let left = x + 12;
  if (left + tw > cw) left = x - tw - 12;
  tip.style.left = `${Math.max(0, left)}px`;
  tip.style.top = `${Math.max(0, y - 10)}px`;
}

function hideTip(tip) { tip.style.display = "none"; }

// Bar with 4px rounded data end, square at the baseline.
function barPath(x, w, y0, y1, r = 4) {
  const up = y1 < y0;
  const h = Math.abs(y1 - y0);
  r = Math.min(r, h, w / 2);
  if (up) {
    return `M${x},${y0}V${y1 + r}Q${x},${y1} ${x + r},${y1}H${x + w - r}Q${x + w},${y1} ${x + w},${y1 + r}V${y0}Z`;
  }
  return `M${x},${y0}V${y1 - r}Q${x},${y1} ${x + r},${y1}H${x + w - r}Q${x + w},${y1} ${x + w},${y1 - r}V${y0}Z`;
}

function observe(container, draw) {
  draw();
  if (container._ro) container._ro.disconnect();
  let last = container.clientWidth;
  container._ro = new ResizeObserver(() => {
    if (Math.abs(container.clientWidth - last) > 4) { last = container.clientWidth; draw(); }
  });
  container._ro.observe(container);
}

export function columnChart(container, { categories, values, format, label = "", height = 220, estimate = [] }) {
  observe(container, () => {
    const { svg, tip, width } = setup(container, height);
    svg.setAttribute("aria-label", label);
    const m = { t: 16, r: 8, b: 26, l: 56 };
    const finite = values.filter((v) => Number.isFinite(v));
    if (!finite.length) { container.innerHTML = '<p class="muted small">No data for this view.</p>'; return; }
    const ticks = niceTicks(Math.min(0, ...finite), Math.max(0, ...finite));
    const lo = ticks[0], hi = ticks[ticks.length - 1];
    const ih = height - m.t - m.b, iw = width - m.l - m.r;
    const y = (v) => m.t + ih - ((v - lo) / (hi - lo)) * ih;
    for (const t of ticks) {
      el("line", { x1: m.l, x2: width - m.r, y1: y(t), y2: y(t), class: t === 0 ? "baseline" : "gridline" }, svg);
      el("text", { x: m.l - 8, y: y(t) + 4, "text-anchor": "end", class: "tick" }, svg).textContent = format(t, true);
    }
    const band = iw / categories.length;
    const bw = Math.min(24, band * 0.6);
    const every = Math.ceil(categories.length / Math.floor(iw / 64));
    categories.forEach((c, i) => {
      const cx = m.l + band * i + band / 2;
      const hover = el("rect", { x: m.l + band * i, y: m.t, width: band, height: ih, class: "hover-band", opacity: 0 }, svg);
      const v = values[i];
      if (Number.isFinite(v) && v !== 0) {
        el("path", { d: barPath(cx - bw / 2, bw, y(0), y(v)), fill: "var(--series-1)", class: "bar",
          "fill-opacity": estimate[i] ? 0.4 : 1 }, svg);
      }
      if ((categories.length - 1 - i) % every === 0) {   // anchor labels on the latest period
        el("text", { x: cx, y: height - 8, "text-anchor": "middle", class: "tick" }, svg).textContent = c;
      }
      if (i === categories.length - 1 && Number.isFinite(v)) {
        el("text", { x: cx, y: v >= 0 ? y(v) - 6 : y(v) + 14, "text-anchor": "middle", class: "dlabel" }, svg)
          .textContent = format(v);
      }
      const hit = el("rect", { x: m.l + band * i, y: m.t, width: band, height: ih, class: "hit" }, svg);
      hit.addEventListener("mousemove", (e) => {
        hover.setAttribute("opacity", 1);
        const r = container.getBoundingClientRect();
        showTip(tip, container, e.clientX - r.left, e.clientY - r.top, c,
          [{ label: estimate[i] ? `${label} (projected)` : label, value: Number.isFinite(v) ? format(v) : "n/a", color: "var(--series-1)" }]);
      });
      hit.addEventListener("mouseleave", () => { hover.setAttribute("opacity", 0); hideTip(tip); });
    });
  });
}

export function lineChart(container, { categories, series, format, label = "", height = 220 }) {
  observe(container, () => {
    const { svg, tip, width } = setup(container, height);
    svg.setAttribute("aria-label", label);
    const all = series.flatMap((s) => s.values).filter((v) => Number.isFinite(v));
    if (!all.length) { container.innerHTML = '<p class="muted small">No data for this view.</p>'; return; }
    const m = { t: 12, r: 96, b: 26, l: 56 };
    const ticks = niceTicks(Math.min(0, ...all), Math.max(...all));
    const lo = ticks[0], hi = ticks[ticks.length - 1];
    const ih = height - m.t - m.b, iw = width - m.l - m.r;
    const x = (i) => m.l + (categories.length === 1 ? iw / 2 : (iw * i) / (categories.length - 1));
    const y = (v) => m.t + ih - ((v - lo) / (hi - lo)) * ih;
    for (const t of ticks) {
      el("line", { x1: m.l, x2: m.l + iw, y1: y(t), y2: y(t), class: t === 0 ? "baseline" : "gridline" }, svg);
      el("text", { x: m.l - 8, y: y(t) + 4, "text-anchor": "end", class: "tick" }, svg).textContent = format(t, true);
    }
    const every = Math.ceil(categories.length / Math.floor(iw / 64));
    categories.forEach((c, i) => {
      if ((categories.length - 1 - i) % every === 0) {   // anchor labels on the latest period
        el("text", { x: x(i), y: height - 8, "text-anchor": "middle", class: "tick" }, svg).textContent = c;
      }
    });
    const cross = el("line", { y1: m.t, y2: m.t + ih, class: "baseline", opacity: 0 }, svg);
    const ends = [];
    for (const s of series) {
      let d = "", pen = false;
      s.values.forEach((v, i) => {
        if (!Number.isFinite(v)) { pen = false; return; }
        d += `${pen ? "L" : "M"}${x(i)},${y(v)}`; pen = true;
      });
      el("path", { d, fill: "none", stroke: s.color, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }, svg);
      const li = s.values.map((v, i) => (Number.isFinite(v) ? i : -1)).filter((i) => i >= 0).pop();
      if (li !== undefined) {
        el("circle", { cx: x(li), cy: y(s.values[li]), r: 4, fill: s.color, stroke: "var(--surface)", "stroke-width": 2 }, svg);
        ends.push({ s, y: y(s.values[li]), v: s.values[li], x: x(li) });
      }
    }
    // direct end labels only when they don't collide; the legend carries identity otherwise
    ends.sort((a, b) => a.y - b.y);
    const clear = ends.every((e, i) => i === 0 || e.y - ends[i - 1].y >= 14);
    if (clear) {
      for (const e of ends) {
        el("text", { x: e.x + 10, y: e.y + 4, class: "dlabel" }, svg).textContent = `${e.s.name} ${format(e.v)}`;
      }
    }
    const hit = el("rect", { x: m.l, y: m.t, width: iw, height: ih, class: "hit" }, svg);
    hit.addEventListener("mousemove", (e) => {
      const r = container.getBoundingClientRect();
      const px = ((e.clientX - r.left) / r.width) * width;
      const i = Math.max(0, Math.min(categories.length - 1, Math.round(((px - m.l) / iw) * (categories.length - 1))));
      cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i)); cross.setAttribute("opacity", 1);
      showTip(tip, container, e.clientX - r.left, e.clientY - r.top, categories[i],
        series.map((s) => ({ label: s.name, color: s.color, value: Number.isFinite(s.values[i]) ? format(s.values[i]) : "n/a" })));
    });
    hit.addEventListener("mouseleave", () => { cross.setAttribute("opacity", 0); hideTip(tip); });
  });
}

// Football field: one horizontal range per row (low..high) with a best-guess tick.
export function rangeChart(container, { rows, format, reference, label = "" }) {
  observe(container, () => {
    const rowH = 40;
    const height = rows.length * rowH + 40;
    const { svg, tip, width } = setup(container, height);
    svg.setAttribute("aria-label", label);
    const m = { t: 8, r: 24, b: 28, l: Math.min(150, width * 0.32) };
    const vals = rows.flatMap((r) => [r.lo, r.hi]).concat(reference ? [reference.value] : []).filter(Number.isFinite);
    const ticks = niceTicks(Math.min(...vals) * 0.95, Math.max(...vals) * 1.05, 5);
    const lo = ticks[0], hi = ticks[ticks.length - 1];
    const iw = width - m.l - m.r;
    const x = (v) => m.l + ((v - lo) / (hi - lo)) * iw;
    const bottom = m.t + rows.length * rowH;
    for (const t of ticks) {
      el("line", { x1: x(t), x2: x(t), y1: m.t, y2: bottom, class: "gridline" }, svg);
      el("text", { x: x(t), y: bottom + 18, "text-anchor": "middle", class: "tick" }, svg).textContent = format(t, true);
    }
    rows.forEach((r, i) => {
      const cy = m.t + i * rowH + rowH / 2;
      el("text", { x: m.l - 10, y: cy + 4, "text-anchor": "end", class: "dlabel" }, svg).textContent = r.label;
      const x0 = x(r.lo), x1 = x(r.hi);
      el("rect", { x: x0, y: cy - 8, width: Math.max(2, x1 - x0), height: 16, rx: 4, fill: "var(--series-1)", class: "range" }, svg);
      if (Number.isFinite(r.mid)) {
        el("rect", { x: x(r.mid) - 1.5, y: cy - 12, width: 3, height: 24, rx: 1.5, fill: "var(--ink)", stroke: "var(--surface)", "stroke-width": 2 }, svg);
      }
      const hit = el("rect", { x: 0, y: cy - rowH / 2, width, height: rowH, class: "hit" }, svg);
      hit.addEventListener("mousemove", (e) => {
        const b = container.getBoundingClientRect();
        showTip(tip, container, e.clientX - b.left, e.clientY - b.top, r.label, [
          { label: "Low (P10)", value: format(r.lo) }, { label: "Best (P50)", value: format(r.mid) },
          { label: "High (P90)", value: format(r.hi) }]);
      });
      hit.addEventListener("mouseleave", () => hideTip(tip));
    });
    if (reference && Number.isFinite(reference.value)) {
      const rx = x(reference.value);
      el("line", { x1: rx, x2: rx, y1: m.t - 4, y2: bottom, stroke: "var(--ink-2)", "stroke-width": 1 }, svg);
      el("text", { x: rx + 4, y: m.t + 6, class: "dlabel" }, svg).textContent = `${reference.label} ${format(reference.value)}`;
    }
  });
}

// Area for reported values, dashed line for projected ones, with an optional
// shaded low-high band over the projection. Points sit at the centre of each
// period's slot so labels line up with the other charts.
//   estimate[i] true = projected; low[i] / high[i] = band (projected points only)
//   growth[i] (optional) shown in the tooltip
export function areaChart(container, { categories, values, estimate = [], low = [], high = [], growth = [],
  format, pctFormat = (v) => `${(v * 100).toFixed(1)}%`, label = "", bandLabel = "Range", height = 220 }) {
  observe(container, () => {
    const { svg, tip, width } = setup(container, height);
    svg.setAttribute("aria-label", label);
    const m = { t: 18, r: 12, b: 26, l: 56 };
    const finite = values.concat(low, high).filter((v) => Number.isFinite(v));
    if (!finite.length) { container.innerHTML = '<p class="muted small">No data for this view.</p>'; return; }
    const ticks = niceTicks(Math.min(0, ...finite), Math.max(0, ...finite));
    const lo = ticks[0], hi = ticks[ticks.length - 1];
    const ih = height - m.t - m.b, iw = width - m.l - m.r;
    const band = iw / categories.length;
    const x = (i) => m.l + band * i + band / 2;
    const y = (v) => m.t + ih - ((v - lo) / (hi - lo)) * ih;
    for (const t of ticks) {
      el("line", { x1: m.l, x2: width - m.r, y1: y(t), y2: y(t), class: t === 0 ? "baseline" : "gridline" }, svg);
      el("text", { x: m.l - 8, y: y(t) + 4, "text-anchor": "end", class: "tick" }, svg).textContent = format(t, true);
    }
    const act = values.map((v, i) => (!estimate[i] && Number.isFinite(v) ? i : -1)).filter((i) => i >= 0);
    const est = values.map((v, i) => (estimate[i] && Number.isFinite(v) ? i : -1)).filter((i) => i >= 0);
    const last = act.at(-1);
    const pts = (ix, f = (i) => values[i]) => ix.map((i) => `${x(i)},${y(f(i))}`).join("L");

    if (est.length && last != null) {
      const sx = (x(last) + x(est[0])) / 2;
      el("line", { x1: sx, x2: sx, y1: m.t - 6, y2: m.t + ih, class: "divider" }, svg);
      el("text", { x: sx + 6, y: m.t + 4, class: "tick" }, svg).textContent = "projected →";
      const bi = est.filter((i) => Number.isFinite(low[i]) && Number.isFinite(high[i]));
      if (bi.length) {
        const top = [`${x(last)},${y(values[last])}`, ...bi.map((i) => `${x(i)},${y(high[i])}`)];
        const bot = [...bi.map((i) => `${x(i)},${y(low[i])}`).reverse(), `${x(last)},${y(values[last])}`];
        el("path", { d: `M${top.join("L")}L${bot.join("L")}Z`, class: "range-band" }, svg);
      }
    }
    if (act.length) {
      el("path", { d: `M${x(act[0])},${y(Math.max(lo, 0))}L${pts(act)}L${x(last)},${y(Math.max(lo, 0))}Z`, class: "area-fill" }, svg);
      el("path", { d: `M${pts(act)}`, class: "area-line" }, svg);
    }
    if (est.length) {
      const ix = last != null ? [last, ...est] : est;
      el("path", { d: `M${pts(ix)}`, class: "area-line projected" }, svg);
    }
    const every = Math.ceil(categories.length / Math.floor(iw / 64));
    const dots = [];
    categories.forEach((c, i) => {
      const v = values[i];
      if ((categories.length - 1 - i) % every === 0) {
        el("text", { x: x(i), y: height - 8, "text-anchor": "middle", class: "tick" + (estimate[i] ? " est" : "") }, svg).textContent = c;
      }
      if (Number.isFinite(v)) dots[i] = el("circle", { cx: x(i), cy: y(v), r: 3, class: "area-dot" + (estimate[i] ? " projected" : "") }, svg);
      if (i === categories.length - 1 && Number.isFinite(v)) {
        el("text", { x: x(i), y: y(Number.isFinite(high[i]) ? high[i] : v) - 7, "text-anchor": "end", class: "dlabel" }, svg).textContent = format(v);
      }
    });
    const cross = el("line", { y1: m.t, y2: m.t + ih, class: "baseline", opacity: 0 }, svg);
    categories.forEach((c, i) => {
      const hit = el("rect", { x: m.l + band * i, y: m.t, width: band, height: ih, class: "hit" }, svg);
      hit.addEventListener("mousemove", (e) => {
        cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i)); cross.setAttribute("opacity", 1);
        dots.forEach((d, k) => d && d.setAttribute("r", k === i ? 5 : 3));
        const r = container.getBoundingClientRect();
        const rows = [{ label: estimate[i] ? `${label} (projected)` : label, value: Number.isFinite(values[i]) ? format(values[i]) : "n/a", color: "var(--series-1)" }];
        if (Number.isFinite(growth[i])) rows.push({ label: "Growth", value: pctFormat(growth[i]) });
        if (Number.isFinite(low[i]) && Number.isFinite(high[i])) rows.push({ label: bandLabel, value: `${format(low[i])} – ${format(high[i])}` });
        showTip(tip, container, e.clientX - r.left, e.clientY - r.top, c, rows);
      });
      hit.addEventListener("mouseleave", () => { cross.setAttribute("opacity", 0); dots.forEach((d) => d && d.setAttribute("r", 3)); hideTip(tip); });
    });
  });
}

// Scatter: one dot per company. points: [{x, y, label, sub, highlight, r}]
// onClick(point) optional. Axis titles sit along the axes.
export function scatterChart(container, { points, xFormat, yFormat, xLabel = "", yLabel = "", height = 280, onClick }) {
  observe(container, () => {
    const { svg, tip, width } = setup(container, height);
    svg.setAttribute("aria-label", `${yLabel} against ${xLabel}`);
    const pts = points.filter((p) => Number.isFinite(p.x) && Number.isFinite(p.y));
    if (!pts.length) { container.innerHTML = '<p class="muted small">No data for this chart.</p>'; return; }
    const m = { t: 24, r: 14, b: 40, l: 56 };
    const xt = niceTicks(Math.min(0, ...pts.map((p) => p.x)), Math.max(...pts.map((p) => p.x)));
    const yt = niceTicks(Math.min(0, ...pts.map((p) => p.y)), Math.max(...pts.map((p) => p.y)));
    const iw = width - m.l - m.r, ih = height - m.t - m.b;
    const x = (v) => m.l + ((v - xt[0]) / (xt.at(-1) - xt[0])) * iw;
    const y = (v) => m.t + ih - ((v - yt[0]) / (yt.at(-1) - yt[0])) * ih;
    for (const t of yt) {
      el("line", { x1: m.l, x2: m.l + iw, y1: y(t), y2: y(t), class: t === 0 ? "baseline" : "gridline" }, svg);
      el("text", { x: m.l - 8, y: y(t) + 4, "text-anchor": "end", class: "tick" }, svg).textContent = yFormat(t, true);
    }
    for (const t of xt) {
      if (t === 0) el("line", { x1: x(0), x2: x(0), y1: m.t, y2: m.t + ih, class: "baseline" }, svg);
      el("text", { x: x(t), y: m.t + ih + 16, "text-anchor": "middle", class: "tick" }, svg).textContent = xFormat(t, true);
    }
    el("text", { x: m.l + iw, y: height - 4, "text-anchor": "end", class: "tick axis-title" }, svg).textContent = `${xLabel} →`;
    el("text", { x: m.l, y: 12, class: "tick axis-title" }, svg).textContent = `↑ ${yLabel}`;
    const ordered = [...pts].sort((a, b) => (a.highlight ? 1 : 0) - (b.highlight ? 1 : 0));   // highlight drawn last
    for (const p of ordered) {
      const c = el("circle", { cx: x(p.x), cy: y(p.y), r: p.highlight ? 7 : 5, class: "sc-dot" + (p.highlight ? " me" : "") + (onClick ? " link" : "") }, svg);
      if (p.highlight) el("text", { x: x(p.x) + 10, y: y(p.y) + 4, class: "dlabel" }, svg).textContent = p.label;
      c.addEventListener("mousemove", (e) => {
        const r = container.getBoundingClientRect();
        showTip(tip, container, e.clientX - r.left, e.clientY - r.top, p.label + (p.sub ? ` · ${p.sub}` : ""),
          [{ label: xLabel, value: xFormat(p.x) }, { label: yLabel, value: yFormat(p.y) }]);
      });
      c.addEventListener("mouseleave", () => hideTip(tip));
      if (onClick) c.addEventListener("click", () => onClick(p));
    }
  });
}

// Horizontal bars ranked largest first. items: [{label, value, highlight}]
export function barListChart(container, { items, format, rowHeight = 20, labelWidth = 70, onClick }) {
  observe(container, () => {
    const height = items.length * rowHeight + 6;
    const { svg, tip, width } = setup(container, height);
    const max = Math.max(...items.map((i) => i.value).filter(Number.isFinite), 0) || 1;
    const iw = width - labelWidth - 64;
    items.forEach((it, i) => {
      const yy = 3 + i * rowHeight;
      el("text", { x: labelWidth - 8, y: yy + rowHeight * 0.65, "text-anchor": "end", class: "tick" + (it.highlight ? " strong" : "") }, svg).textContent = it.label;
      const w = Number.isFinite(it.value) ? Math.max(2, (it.value / max) * iw) : 0;
      const bar = el("path", { d: barPathH(labelWidth, yy + 3, w, rowHeight - 7), class: "hbar" + (it.highlight ? " me" : "") + (onClick ? " link" : "") }, svg);
      el("text", { x: labelWidth + w + 6, y: yy + rowHeight * 0.65, class: "dlabel" }, svg).textContent = format(it.value);
      bar.addEventListener("mousemove", (e) => {
        const r = container.getBoundingClientRect();
        showTip(tip, container, e.clientX - r.left, e.clientY - r.top, it.title || it.label, [{ label: "Revenue", value: format(it.value) }]);
      });
      bar.addEventListener("mouseleave", () => hideTip(tip));
      if (onClick) bar.addEventListener("click", () => onClick(it));
    });
  });
}

// Horizontal bar with a 4px rounded data end.
function barPathH(x, y, w, h, r = 4) {
  r = Math.min(r, w, h / 2);
  return `M${x},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h - r}Q${x + w},${y + h} ${x + w - r},${y + h}H${x}Z`;
}
