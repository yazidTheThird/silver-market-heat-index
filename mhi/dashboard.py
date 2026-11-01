"""Writes docs/index.html — a self-contained dashboard (GitHub Pages serves /docs)."""
from __future__ import annotations

import json
import os

import pandas as pd

from .index import COMPONENTS, ROOT

LABELS = {
    "drops": "Colorized drops selling out",
    "ebay": "eBay collector premium",
    "attention": "Colorized chatter",
    "silver": "Silver price mood",
    "calendar": "Calendar & competition",
}


def build(hist: pd.DataFrame, cfg: dict, groups: pd.DataFrame | None = None) -> str:
    h = hist.tail(180).copy()
    h = h.where(pd.notnull(h), None)
    rows = []
    for _, r in h.iterrows():
        rows.append({
            "date": r["date"], "index": r.get("index"), "label": r.get("label"),
            "coverage": r.get("coverage"),
            "spot": r.get("silver_spot"),
            "scores": {c: r.get(f"score_{c}") for c in COMPONENTS},
        })
    gl = []
    if groups is not None and not groups.empty:
        g = groups.astype(object).where(pd.notnull(groups), None)
        gl = g.to_dict("records")
    products = []
    if gl:
        try:
            from . import tags
            from .drops import STATE
            products = tags.product_rows(pd.read_csv(STATE, dtype=str), cfg)
        except Exception:  # noqa: BLE001
            products = []
    payload = {
        "groups": gl,
        "products": products,
        "rows": rows,
        "labels": LABELS,
        "weights": cfg["weights"],
        "hot": cfg["thresholds"]["hot"],
        "dead": cfg["thresholds"]["dead"],
    }
    html = TEMPLATE.replace("__DATA__", json.dumps(payload, default=float))
    out = os.path.join(ROOT, "docs", "index.html")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    return out


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Market Heat Index</title>
<style>
:root {
  color-scheme: light;
  --surface-0: #f4f3f0;
  --surface-1: #fcfcfb;
  --border: #e3e2dd;
  --grid: #ecebe7;
  --text-primary: #0b0b0b;
  --text-secondary: #52514e;
  --text-muted: #7a7974;
  --series-1: #2a78d6;
  --band-hot: rgba(12,163,12,0.08);
  --band-dead: rgba(208,59,59,0.08);
  --good: #0ca30c; --warning: #c98500; --critical: #d03b3b;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --surface-0: #111110; --surface-1: #1a1a19; --border: #2c2c2a; --grid: #262624;
    --text-primary: #f0efec; --text-secondary: #c3c2b7; --text-muted: #8f8e88;
    --series-1: #3987e5;
    --band-hot: rgba(12,163,12,0.14); --band-dead: rgba(208,59,59,0.14);
    --warning: #fab219;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --surface-0: #111110; --surface-1: #1a1a19; --border: #2c2c2a; --grid: #262624;
  --text-primary: #f0efec; --text-secondary: #c3c2b7; --text-muted: #8f8e88;
  --series-1: #3987e5;
  --band-hot: rgba(12,163,12,0.14); --band-dead: rgba(208,59,59,0.14);
  --warning: #fab219;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--surface-0); color: var(--text-primary);
  font: 15px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
main { max-width: 860px; margin: 0 auto; padding: 24px 16px 48px; }
h1 { font-size: 18px; font-weight: 600; margin: 0 0 4px; }
.sub { color: var(--text-secondary); font-size: 13px; margin: 0 0 20px; }
.card { background: var(--surface-1); border: 1px solid var(--border); border-radius: 12px;
  padding: 20px; margin-bottom: 16px; }
.hero { display: flex; align-items: center; gap: 24px; flex-wrap: wrap; }
.hero .num { font-size: 64px; font-weight: 700; line-height: 1; font-variant-numeric: tabular-nums; }
.hero .num small { font-size: 20px; color: var(--text-muted); font-weight: 500; }
.status { display: inline-flex; align-items: center; gap: 8px; font-weight: 600; font-size: 18px; }
.status svg { width: 20px; height: 20px; }
.advice { color: var(--text-secondary); margin-top: 6px; max-width: 420px; }
.meta { color: var(--text-muted); font-size: 12px; margin-top: 8px; }
h2 { font-size: 14px; font-weight: 600; margin: 0 0 12px; color: var(--text-secondary); }
.bars .row { display: grid; grid-template-columns: 250px 1fr 44px; gap: 12px; align-items: center;
  padding: 6px 0; }
.bars .name { font-size: 14px; }
.bars .name span { color: var(--text-muted); font-size: 12px; }
.bars .track { height: 10px; background: var(--grid); border-radius: 5px; position: relative; }
.bars .fill { position: absolute; left: 0; top: 0; bottom: 0; background: var(--series-1);
  border-radius: 5px; }
.bars .val { text-align: right; font-variant-numeric: tabular-nums; }
.bars .na { color: var(--text-muted); font-size: 13px; }
#chart { width: 100%; height: 240px; display: block; }
.tip { position: fixed; pointer-events: none; background: var(--surface-1); border: 1px solid var(--border);
  border-radius: 8px; padding: 8px 10px; font-size: 13px; box-shadow: 0 4px 16px rgba(0,0,0,.12);
  display: none; z-index: 5; }
table { width: 100%; border-collapse: collapse; font-size: 13px; font-variant-numeric: tabular-nums; }
th, td { text-align: right; padding: 6px 4px; border-bottom: 1px solid var(--grid); }
th:first-child, td:first-child { text-align: left; }
th { color: var(--text-muted); font-weight: 500; }
.tabs { display: flex; gap: 6px; flex-wrap: wrap; }
.tabs button { font: inherit; font-size: 13px; padding: 5px 12px; border-radius: 999px;
  border: 1px solid var(--border); background: transparent; color: var(--text-secondary); cursor: pointer; }
.tabs button.on { background: var(--series-1); border-color: var(--series-1); color: #fff; }
.grow { cursor: pointer; }
.grow:hover td { background: var(--grid); }
.grow td:first-child::before { content: "▸ "; color: var(--text-muted); }
.grow.open td:first-child::before { content: "▾ "; }
.plist td { text-align: left; padding: 0 0 10px; }
.plist ul { list-style: none; margin: 0; padding: 4px 0 0 14px; max-height: 360px; overflow-y: auto; }
.plist li { padding: 5px 0; border-bottom: 1px solid var(--grid); font-size: 13px; display: flex; gap: 8px; align-items: baseline; }
.plist a { color: var(--series-1); text-decoration: none; flex: 1; }
.plist a:hover { text-decoration: underline; }
.pill { font-size: 11px; padding: 1px 7px; border-radius: 999px; white-space: nowrap; }
.pill.sold { background: rgba(12,163,12,.15); color: var(--good); }
.pill.in { background: var(--grid); color: var(--text-muted); }
.pmeta { color: var(--text-muted); font-size: 11px; white-space: nowrap; }
.hb { display: inline-block; height: 8px; border-radius: 4px; background: var(--series-1); vertical-align: middle; margin-right: 6px; }
details summary { cursor: pointer; color: var(--text-secondary); font-size: 14px; }
.tablewrap { overflow-x: auto; margin-top: 12px; }
@media (max-width: 560px) {
  .bars .row { grid-template-columns: 1fr 44px; }
  .bars .track { grid-column: 1 / -1; order: 3; }
  .hero .num { font-size: 52px; }
}
</style>
</head>
<body>
<main>
  <h1>Market Heat Index</h1>
  <p class="sub">Demand gauge for colorized silver coins &amp; collectibles · 0 = dead market, 100 = hottest in 90 days</p>

  <section class="card hero" id="hero"></section>

  <section class="card">
    <h2>What's driving it today</h2>
    <div class="bars" id="bars"></div>
  </section>

  <section class="card">
    <h2>What's hot (silver) · by sell-out speed</h2>
    <div class="tabs" id="gtabs"></div>
    <div class="tablewrap"><table id="gtbl"></table></div>
    <p class="meta" id="gnote"></p>
  </section>

  <section class="card">
    <h2>Index over time</h2>
    <svg id="chart" role="img" aria-label="Market Heat Index over time"></svg>
  </section>

  <section class="card">
    <details>
      <summary>Daily numbers (table)</summary>
      <div class="tablewrap"><table id="tbl"></table></div>
    </details>
  </section>
</main>
<div class="tip" id="tip"></div>

<script>
const D = __DATA__;
const rows = D.rows.filter(r => r.index !== null);
const last = rows[rows.length - 1];
const fmt = v => (v === null || v === undefined || Number.isNaN(v)) ? "—" : Math.round(v);

const STATUS = {
  HOT:    { color: "var(--good)", text: "Hot market",
            advice: "Good window to launch. Demand is strong — consider a larger mintage.",
            icon: '<svg viewBox="0 0 20 20"><path d="M10 2c1 3 4 4.5 4 8.5A4 4 0 0 1 6 10.5c0-1.5.8-2.6 1.6-3.4C8 9 9 9.5 9.5 9.5 9.5 6.5 9 4 10 2z" fill="currentColor"/></svg>' },
  NORMAL: { color: "var(--warning)", text: "Normal market",
            advice: "Launch with a waitlist and a moderate mintage. Expect a steady sell-through, not an instant sellout.",
            icon: '<svg viewBox="0 0 20 20"><circle cx="10" cy="10" r="7" fill="none" stroke="currentColor" stroke-width="2"/><path d="M6 10h8" stroke="currentColor" stroke-width="2"/></svg>' },
  DEAD:   { color: "var(--critical)", text: "Dead market",
            advice: "Hold the release, or open pre-orders only and let demand set the mintage.",
            icon: '<svg viewBox="0 0 20 20"><circle cx="10" cy="10" r="7" fill="none" stroke="currentColor" stroke-width="2"/><path d="M7 7l6 6M13 7l-6 6" stroke="currentColor" stroke-width="2"/></svg>' },
  "LOW DATA": { color: "var(--text-muted)", text: "Not enough data today",
            advice: "Too few sources answered today to give a verdict. Check the bars below for what's missing.",
            icon: '<svg viewBox="0 0 20 20"><circle cx="10" cy="10" r="7" fill="none" stroke="currentColor" stroke-width="2"/><path d="M10 6v5M10 13.5v.5" stroke="currentColor" stroke-width="2"/></svg>' },
};

function hero() {
  const el = document.getElementById("hero");
  if (!last) { el.innerHTML = "<p>No data yet — the first daily run hasn't happened.</p>"; return; }
  const s = STATUS[last.label] || STATUS.NORMAL;
  const prev = rows.length > 7 ? rows[rows.length - 8].index : null;
  const delta = prev !== null ? Math.round(last.index - prev) : null;
  el.innerHTML = `
    <div class="num">${fmt(last.index)}<small> / 100</small></div>
    <div>
      <div class="status" style="color:${s.color}">${s.icon}<span>${s.text}</span></div>
      <div class="advice">${s.advice}</div>
      <div class="meta">${last.date}${delta !== null ? ` · ${delta >= 0 ? "+" : ""}${delta} vs a week ago` : ""}
        ${last.spot ? ` · silver $${Number(last.spot).toFixed(2)}` : ""}
        · data coverage ${Math.round((last.coverage || 0) * 100)}%</div>
    </div>`;
}

function bars() {
  const el = document.getElementById("bars");
  el.innerHTML = Object.keys(D.labels).map(k => {
    const v = last ? last.scores[k] : null;
    const body = (v === null || v === undefined)
      ? `<div class="track"></div><div class="val na">n/a</div>`
      : `<div class="track"><div class="fill" style="width:${Math.max(2, v)}%"></div></div><div class="val">${fmt(v)}</div>`;
    return `<div class="row"><div class="name">${D.labels[k]} <span>· weight ${D.weights[k]}</span></div>${body}</div>`;
  }).join("");
}

function chart() {
  const svg = document.getElementById("chart");
  const W = svg.clientWidth || 800, H = 240, m = { l: 32, r: 12, t: 10, b: 24 };
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  const data = rows.slice(-90);
  if (data.length < 2) { svg.innerHTML = `<text x="${m.l}" y="40" fill="var(--text-muted)" font-size="13">The chart fills in after a couple of daily runs.</text>`; return; }
  const x = i => m.l + (i / (data.length - 1)) * (W - m.l - m.r);
  const y = v => m.t + (1 - v / 100) * (H - m.t - m.b);
  let g = "";
  g += `<rect x="${m.l}" y="${y(100)}" width="${W-m.l-m.r}" height="${y(D.hot)-y(100)}" fill="var(--band-hot)"/>`;
  g += `<rect x="${m.l}" y="${y(D.dead)}" width="${W-m.l-m.r}" height="${y(0)-y(D.dead)}" fill="var(--band-dead)"/>`;
  [0, D.dead, D.hot, 100].forEach(t => {
    g += `<line x1="${m.l}" x2="${W-m.r}" y1="${y(t)}" y2="${y(t)}" stroke="var(--grid)"/>`;
    g += `<text x="${m.l-6}" y="${y(t)+4}" text-anchor="end" font-size="11" fill="var(--text-muted)">${t}</text>`;
  });
  g += `<text x="${W-m.r-4}" y="${y(100)+14}" text-anchor="end" font-size="11" fill="var(--text-muted)">hot</text>`;
  g += `<text x="${W-m.r-4}" y="${y(0)-6}" text-anchor="end" font-size="11" fill="var(--text-muted)">dead</text>`;
  const step = Math.max(1, Math.ceil(data.length / 6));
  data.forEach((d, i) => { if (i % step === 0 || i === data.length - 1)
    g += `<text x="${x(i)}" y="${H-6}" text-anchor="${i === data.length - 1 ? "end" : i === 0 ? "start" : "middle"}" font-size="11" fill="var(--text-muted)">${d.date.slice(5)}</text>`; });
  const path = data.map((d, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(d.index).toFixed(1)}`).join("");
  g += `<path d="${path}" fill="none" stroke="var(--series-1)" stroke-width="2" stroke-linejoin="round"/>`;
  const li = data.length - 1;
  g += `<circle cx="${x(li)}" cy="${y(data[li].index)}" r="4" fill="var(--series-1)" stroke="var(--surface-1)" stroke-width="2"/>`;
  g += `<line id="xh" y1="${m.t}" y2="${H-m.b}" stroke="var(--text-muted)" stroke-dasharray="3 3" visibility="hidden"/>`;
  g += `<circle id="dot" r="5" fill="var(--series-1)" stroke="var(--surface-1)" stroke-width="2" visibility="hidden"/>`;
  g += `<rect x="${m.l}" y="0" width="${W-m.l-m.r}" height="${H}" fill="transparent" id="hit"/>`;
  svg.innerHTML = g;
  const tip = document.getElementById("tip"), xh = svg.querySelector("#xh"), dot = svg.querySelector("#dot");
  const move = ev => {
    const pt = svg.getBoundingClientRect();
    const px = (ev.clientX - pt.left) * (W / pt.width);
    const i = Math.max(0, Math.min(li, Math.round((px - m.l) / (W - m.l - m.r) * li)));
    const d = data[i];
    xh.setAttribute("x1", x(i)); xh.setAttribute("x2", x(i)); xh.setAttribute("visibility", "visible");
    dot.setAttribute("cx", x(i)); dot.setAttribute("cy", y(d.index)); dot.setAttribute("visibility", "visible");
    tip.innerHTML = `<b>${d.date}</b><br>Index ${fmt(d.index)} · ${d.label}` +
      Object.keys(D.labels).map(k => `<br><span style="color:var(--text-secondary)">${D.labels[k]}: ${fmt(d.scores[k])}</span>`).join("");
    tip.style.display = "block";
    const tx = Math.min(window.innerWidth - tip.offsetWidth - 8, ev.clientX + 14);
    tip.style.left = tx + "px"; tip.style.top = (ev.clientY + 14) + "px";
  };
  const hit = svg.querySelector("#hit");
  hit.addEventListener("pointermove", move);
  hit.addEventListener("pointerleave", () => { tip.style.display = "none";
    xh.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden"); });
}

function table() {
  const keys = Object.keys(D.labels);
  const head = `<tr><th>Date</th><th>Index</th><th>Status</th>${keys.map(k => `<th>${D.labels[k].split(" ")[0]}</th>`).join("")}</tr>`;
  const body = rows.slice(-30).reverse().map(r =>
    `<tr><td>${r.date}</td><td>${fmt(r.index)}</td><td>${r.label}</td>${keys.map(k => `<td>${fmt(r.scores[k])}</td>`).join("")}</tr>`).join("");
  document.getElementById("tbl").innerHTML = head + body;
}

function groups(dim) {
  const G = (D.groups || []).filter(g => g.dimension === dim && g.group !== "Other" && g.confidence !== "too few");
  const tbl = document.getElementById("gtbl"), note = document.getElementById("gnote");
  if (!G.length) { tbl.innerHTML = ""; note.textContent = "Fills in after the tracker has seen a few launches."; return; }
  const rank = c => (c === "high" ? 2 : c === "medium" ? 1 : 0);
  G.sort((a, b) => (rank(b.confidence) - rank(a.confidence)) || ((b.heat ?? -1) - (a.heat ?? -1)));
  const pct = v => v === null || v === undefined ? "—" : Math.round(v * 100) + "%";
  const hrs = v => v === null || v === undefined ? "—" : (v < 48 ? Math.round(v) + " h" : (v / 24).toFixed(1) + " d");
  window._gdim = dim;
  tbl.innerHTML = `<tr><th>${dim}</th><th>Heat</th><th>Launches sold out</th><th>Median time to sell out</th><th>Sold out now</th><th>Tracked</th><th>Confidence</th></tr>` +
    G.map((g, i) => `<tr class="grow" data-g="${encodeURIComponent(g.group)}"><td>${g.group}</td><td><span class="hb" style="width:${Math.max(2, (g.heat || 0) * 0.6)}px"></span>${fmt(g.heat)}</td>` +
      `<td>${g.launches ? pct(g.launch_soldout_share) + " of " + g.launches : "—"}</td><td>${hrs(g.median_hours_to_sellout)}</td>` +
      `<td>${pct(g.snapshot_soldout_share)}</td><td>${g.tracked}</td><td>${g.confidence}</td></tr>`).join("");
  tbl.querySelectorAll(".grow").forEach(tr => tr.onclick = () => toggle(tr, dim, decodeURIComponent(tr.dataset.g)));
  const early = G.every(g => g.confidence.startsWith("low"));
  note.textContent = early ? "Tap a row to see the products. Early read: ranked by what's sold out right now. Launch timing takes over as new launches sell out." :
    "Tap a row to see the products behind it. Heat = share of recent launches that sold out, how many sold out within 2 days, and median time to sell out.";
}
const esc = s => String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
function inGroup(p, dim, grp) {
  if (dim === "Theme") return p.th.includes(grp);
  if (dim === "Base coin") return p.b === grp;
  if (dim === "Size") return p.z === grp;
  return p.f === grp;
}
function toggle(tr, dim, grp) {
  const next = tr.nextElementSibling;
  if (next && next.classList.contains("plist")) { next.remove(); tr.classList.remove("open"); return; }
  tr.classList.add("open");
  const P = (D.products || []).filter(p => inGroup(p, dim, grp));
  // Sold out first (most recent first), then in stock (newest first).
  P.sort((a, b) => (a.a - b.a) || (b.so || "").localeCompare(a.so || "") || (b.fs || "").localeCompare(a.fs || ""));
  const dur = h => h === null ? "" : (h < 48 ? ` in ${Math.round(h)} h` : ` in ${(h / 24).toFixed(1)} d`);
  const li = P.map(p => `<li><span class="pill ${p.a ? "in" : "sold"}">${p.a ? "in stock" : "sold out" + dur(p.h)}</span>` +
    `<a href="${esc(p.u)}" target="_blank" rel="noopener">${esc(p.t)}</a>` +
    `<span class="pmeta">${esc(p.s)}${p.new ? " · new " + p.fs.slice(5) : ""}${p.so ? " · gone " + p.so.slice(5) : ""}</span></li>`).join("");
  const row = document.createElement("tr");
  row.className = "plist";
  row.innerHTML = `<td colspan="7"><ul>${li || "<li>No products listed.</li>"}</ul></td>`;
  tr.after(row);
}
function gtabs() {
  const el = document.getElementById("gtabs");
  const dims = ["Theme", "Base coin", "Size", "Finish"];
  el.innerHTML = dims.map((d, i) => `<button data-d="${d}" class="${i ? "" : "on"}">${d}</button>`).join("");
  el.querySelectorAll("button").forEach(b => b.onclick = () => {
    el.querySelectorAll("button").forEach(x => x.classList.remove("on")); b.classList.add("on"); groups(b.dataset.d); });
  groups("Theme");
}

hero(); bars(); gtabs(); chart(); table();
window.addEventListener("resize", chart);
</script>
</body>
</html>
"""
