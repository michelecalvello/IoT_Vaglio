// IoT Vaglio – portale dei dati di monitoraggio.
// Nessun backend: legge catalog.json e i CSV in data/. Tutti gli orari sono UTC+1 (stringhe 'YYYY-MM-DD HH:MM').
(function () {
  "use strict";

  const DEFAULT = { from: "2023-01-01 00:00", to: "2026-09-30 22:59", sel: ["VAG_CF_RAIN", "VAG_S3_VWC_012"] };
  const S = { cat: null, byId: {}, sel: [], from: DEFAULT.from, to: DEFAULT.to, res: "auto",
              cache: new Map(), last: [] };
  const $ = (q) => document.querySelector(q);

  // ---- utilità di tempo (le stringhe restano in UTC+1: si usa UTC solo per l'aritmetica) ----
  const ms = (s) => Date.parse(s.replace(" ", "T") + ":00Z");
  const spanDays = () => (ms(S.to) - ms(S.from)) / 864e5;
  const toInput = (s) => s.replace(" ", "T");
  const fromInput = (s) => s.replace("T", " ");

  // ---- stato nell'URL (condivisibile) ----
  function readHash() {
    const p = new URLSearchParams(location.hash.slice(1));
    S.sel = p.get("sel") ? p.get("sel").split(",") : DEFAULT.sel.slice();
    S.from = p.get("from") || DEFAULT.from;
    S.to = p.get("to") || DEFAULT.to;
    S.res = p.get("res") || "auto";
  }
  function writeHash() {
    const p = new URLSearchParams({ sel: S.sel.join(","), from: S.from, to: S.to, res: S.res });
    history.replaceState(null, "", "#" + p.toString());
  }

  // ---- caricamento file ----
  async function fetchText(url) {
    if (!S.cache.has(url)) {
      const r = await fetch(url);
      if (!r.ok) throw new Error(`${url} (${r.status})`);
      S.cache.set(url, r.text());
    }
    return S.cache.get(url);
  }

  function parseRows(txt) {
    const lines = txt.split("\n");
    const hdr = lines[0].trim().split(",");
    const out = [];
    for (let i = 1; i < lines.length; i++) {
      const l = lines[i].trim();
      if (!l) continue;
      const p = l.split(",");
      const r = { t: p[0].length === 10 ? p[0] + " 00:00" : p[0] };   // giornalieri: 'YYYY-MM-DD' -> mezzanotte
      for (let j = 1; j < hdr.length; j++) {
        const x = p[j];
        r[hdr[j]] = x === undefined || x === "" ? null : Number(x);
      }
      out.push(r);
    }
    return out;
  }

  function resFor(s) {
    let r = S.res;
    if (r === "auto") { const d = spanDays(); r = d > 90 ? "1d" : d > 4 ? "1h" : "raw"; }
    if (r === "10min" && !s.data.agg_10min) r = "1h";
    return r;
  }

  async function loadSeries(s) {
    const r = resFor(s);
    if (r === "raw") {
      const y0 = +S.from.slice(0, 4), y1 = +S.to.slice(0, 4);
      let rows = [];
      for (const y of s.data.years.filter((y) => y >= y0 && y <= y1)) {
        const txt = await fetchText(s.data.raw.replace("{year}", y));
        for (const q of parseRows(txt)) if (q.t >= S.from && q.t <= S.to) rows.push(q);
      }
      return { s, kind: "dato originale", rows };
    }
    const txt = await fetchText(s.data[`agg_${r}`]);
    const rows = parseRows(txt).filter((q) => q.t >= S.from && q.t <= S.to);
    return { s, kind: r, rows };
  }

  // ---- interfaccia ----
  const varLabel = (s) => (s.variable === "rain" ? "Pioggia" : S.cat.variables[s.variable].label_it);
  const shortLabel = (s) => (s.variable === "rain" ? "Pioggia (pluviometro)"
    : `${varLabel(s)} ${Math.round(s.depth_m * 100)} cm`);
  const unitLabel = (v) => `${S.cat.variables[v].label_it} (${S.cat.variables[v].unit})`;

  function buildList() {
    const box = $("#series-list");
    box.innerHTML = "";
    for (const st of S.cat.stations) {
      const ss = S.cat.series.filter((s) => s.station_id === st.station_id);
      if (!ss.length) continue;
      const h = document.createElement("div");
      h.className = "group";
      h.textContent = st.name;
      box.appendChild(h);
      for (const s of ss) {
        const row = document.createElement("label");
        row.className = "item";
        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.value = s.series_id;
        cb.checked = S.sel.includes(s.series_id);
        cb.addEventListener("change", () => {
          S.sel = [...box.querySelectorAll("input:checked")].map((c) => c.value);
          render();
        });
        row.append(cb, document.createTextNode(" " + shortLabel(s)));
        box.appendChild(row);
      }
    }
  }

  function bindControls() {
    $("#from").value = toInput(S.from);
    $("#to").value = toInput(S.to);
    $("#res").value = S.res;
    $("#from").addEventListener("change", (e) => { S.from = fromInput(e.target.value); render(); });
    $("#to").addEventListener("change", (e) => { S.to = fromInput(e.target.value); render(); });
    $("#res").addEventListener("change", (e) => { S.res = e.target.value; render(); });
    $("#csv").addEventListener("click", exportCSV);
  }

  function buildMap() {
    const pts = S.cat.stations.filter((s) => s.lat != null);
    const box = $("#map");
    if (!pts.length || typeof L === "undefined") { box.textContent = "Coordinate non disponibili."; return; }
    const map = L.map(box).setView([pts[0].lat, pts[0].lon], 11);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { attribution: "© OpenStreetMap" }).addTo(map);
    for (const s of pts) {
      L.marker([s.lat, s.lon]).addTo(map).bindPopup(`<b>${s.name}</b><br>${s.owner}<br>${s.elevation_m ?? ""} m s.l.m.`);
    }
    const nodo = S.cat.stations.filter((s) => s.lat == null).map((s) => s.name);
    if (nodo.length) {
      const p = document.createElement("p");
      p.className = "sub";
      p.textContent = "Senza coordinate: " + nodo.join("; ") + ".";
      box.parentNode.appendChild(p);
    }
  }

  // ---- grafico ----
  const axisName = (i) => (i === 0 ? "y" : "y" + (i + 1));
  const axisKey = (i) => (i === 0 ? "yaxis" : "yaxis" + (i + 1));

  function drawChart(results) {
    const order = ["rain", "vwc", "psi", "t_soil"];
    const panels = order.filter((v) => results.some((r) => r.s.variable === v));
    const n = panels.length;
    const gap = 0.07, h = (1 - gap * (n - 1)) / n;
    const layout = { margin: { t: 20, r: 20, b: 50, l: 70 }, showlegend: true,
                     legend: { orientation: "h", y: -0.12 }, height: 280 * n + 90,
                     xaxis: { anchor: axisName(n - 1), title: "Data e ora (UTC+1)" } };
    panels.forEach((v, i) => {
      const top = 1 - i * (h + gap);
      layout[axisKey(i)] = { domain: [top - h, top], anchor: "x", title: unitLabel(v),
                             rangemode: v === "rain" ? "tozero" : "normal" };
    });
    const traces = results.map((r) => {
      const i = panels.indexOf(r.s.variable);
      const isRain = r.s.variable === "rain";
      const x = r.rows.map((q) => q.t);
      const y = r.rows.map((q) => q.value);
      const base = { x, y, name: `${shortLabel(r.s)} – ${r.kind}`, yaxis: axisName(i) };
      return isRain
        ? { ...base, type: "bar", marker: { color: "#1f6f8b" } }
        : { ...base, type: r.kind === "dato originale" ? "scattergl" : "scatter", mode: "lines" };
    });
    Plotly.newPlot("chart", traces, layout, { responsive: true });
  }

  // ---- statistiche e metadati ----
  function drawStats(results) {
    const fmt = (v, d = 3) => (Number.isFinite(v) ? v.toFixed(d) : "–");
    let html = "<table><tr><th>Serie</th><th>Risoluzione</th><th>Valori</th><th>Statistiche</th></tr>";
    for (const r of results) {
      const vals = r.rows.map((q) => q.value).filter((v) => v !== null && Number.isFinite(v));
      if (!vals.length) { html += `<tr><td>${shortLabel(r.s)}</td><td>${r.kind}</td><td>0</td><td>nessun dato nel periodo</td></tr>`; continue; }
      const sum = vals.reduce((a, b) => a + b, 0);
      const mx = vals.reduce((a, b) => (b > a ? b : a), -Infinity);
      const mn = vals.reduce((a, b) => (b < a ? b : a), Infinity);
      const stat = r.s.variable === "rain"
        ? `totale ${fmt(sum, 1)} mm; massimo ${fmt(mx, 2)} mm nell'intervallo`
        : `media ${fmt(sum / vals.length, 3)} ${S.cat.variables[r.s.variable].unit}; min ${fmt(mn)}; max ${fmt(mx)}`;
      html += `<tr><td>${shortLabel(r.s)}</td><td>${r.kind}</td><td>${vals.length}</td><td>${stat}</td></tr>`;
    }
    $("#stats").innerHTML = html + "</table>";
  }

  function drawMeta(sel) {
    const st = (id) => S.cat.stations.find((x) => x.station_id === id);
    $("#meta").innerHTML = sel.map((s) => {
      const gaps = s.gaps_over_24h.length
        ? s.gaps_over_24h.map((g) => `${g.from.slice(0, 16).replace("T", " ")} → ${g.to.slice(0, 16).replace("T", " ")} (${g.hours} h)`).join("; ")
        : "nessuna lacuna > 24 h";
      const notes = s.qc_notes.length ? "<ul>" + s.qc_notes.map((n) => `<li>${n}</li>`).join("") + "</ul>" : "";
      return `<div class="meta"><b>${s.label}</b><br>
        Stazione: ${st(s.station_id).name}. Proprietario: ${st(s.station_id).owner}.<br>
        Unità: ${s.unit}; aggregazione: ${s.aggregation}; passo: ${s.step_min} min.<br>
        Periodo: ${s.start.slice(0, 16).replace("T", " ")} → ${s.end.slice(0, 16).replace("T", " ")} (UTC+1).<br>
        Lacune: ${gaps}.${notes}</div>`;
    }).join("");
  }

  function exportCSV() {
    const lines = ["serie,time,value,min,max,n,coverage,flag"];
    for (const r of S.last) for (const q of r.rows) {
      lines.push([r.s.series_id, q.t, q.value ?? "", q.min ?? "", q.max ?? "", q.n ?? "", q.coverage ?? "", q.flag ?? ""].join(","));
    }
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/csv" }));
    a.download = `vaglio_${S.from.replace(/[ :]/g, "")}_${S.to.replace(/[ :]/g, "")}.csv`;
    a.click();
  }

  // ---- ciclo principale ----
  async function render() {
    writeHash();
    const status = $("#status");
    const sel = S.sel.map((id) => S.byId[id]).filter(Boolean);
    if (!(spanDays() > 0)) { status.textContent = "Intervallo non valido: la data finale deve essere successiva a quella iniziale."; return; }
    if (!sel.length) { $("#chart").innerHTML = "<p>Seleziona almeno una serie.</p>"; $("#stats").innerHTML = ""; $("#meta").innerHTML = ""; status.textContent = ""; return; }
    status.textContent = "Caricamento dei dati…";
    try {
      S.last = await Promise.all(sel.map(loadSeries));
      status.textContent = `Risoluzione: ${S.last.map((r) => r.kind).filter((v, i, a) => a.indexOf(v) === i).join(", ")}`;
      drawChart(S.last);
      drawStats(S.last);
      drawMeta(sel);
    } catch (e) {
      status.textContent = "Errore nel caricamento: " + e.message;
    }
  }

  async function init() {
    S.cat = await (await fetch("catalog.json")).json();
    S.byId = Object.fromEntries(S.cat.series.map((s) => [s.series_id, s]));
    readHash();
    buildList();
    bindControls();
    buildMap();
    render();
  }

  init();
})();
