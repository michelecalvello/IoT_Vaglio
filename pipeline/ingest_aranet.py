"""
ingest_aranet.py — sensori Aranet di Vaglio di Basilicata (grado di saturazione del terreno e piezometri).

Input  (INPUT_DIR): file 'Sensor_data_<ID>_<ID>…__<inizio>-<fine>_<gruppo>.xlsx' esportati dalla piattaforma Aranet.
         Un foglio per sensore: righe 1-3 metadati (Sensor ID, Sensor Name, Sensor Group), riga 4 intestazioni
         ('Time' + grandezze), poi i dati. Orari in ora locale italiana (CET/CEST), passo nominale 1 minuto
         (molte righe hanno il timestamp ma nessun valore: sono ignorate).
Output (OUT_DIR):
  - data/raw/<serie>/<anno>.csv          time,value,flag   (dato originale, arrotondato al minuto)
  - data/agg/<serie>_1h.csv, _1d.csv     aggregati (media, min, max, n, coverage)
  - catalog.json, series.csv, data/qc_log.csv aggiornati: le serie Aranet esistenti sono sostituite, le altre restano.

Va eseguito DOPO build_vaglio.py (che rigenera catalog.json da zero), insieme a ingest_gee.py e agli altri script.

Tempo: ora locale -> UTC+1 fisso. L'ora ripetuta di fine ora legale (ottobre) è riconosciuta dall'ordine delle righe
nel file (il secondo passaggio, dopo il salto all'indietro, è CET); l'ora saltata di marzo non crea lacune.

Esecuzione:
  INPUT_DIR=<cartella dei file Aranet> OUT_DIR=<radice del repo> python pipeline/ingest_aranet.py
"""
import glob, hashlib, json, os, re
import numpy as np
import pandas as pd
from python_calamine import CalamineWorkbook     # pip install python-calamine (molto più veloce di openpyxl)

INPUT_DIR = os.environ.get("INPUT_DIR", ".")
OUT_DIR = os.environ.get("OUT_DIR", ".")
HERE = os.path.dirname(os.path.abspath(__file__))
RULES = json.load(open(os.path.join(HERE, "qc_rules.json"), encoding="utf-8"))
TFMT = "%Y-%m-%d %H:%M"
PREFIX = "VAG_"            # le serie Aranet sono riconosciute dall'instrument_id che termina in _ARANET

# ----------------------------------------------------------------------------
# 1. STAZIONI E STRUMENTI
#    Una stazione per verticale di misura (sensori a più profondità) e una per piezometro.
#    Coordinate: da completare (None = stazione non mostrata in mappa).
# ----------------------------------------------------------------------------
OWNER = "Università di Salerno"
SITE = {"site": "Vaglio di Basilicata", "municipality": "Vaglio di Basilicata (PZ)", "owner": OWNER}
STATIONS = {
    "VAG_C1": {"name": "Vaglio – Chiesa, verticale C1", "group": "CHIESA", "lat": 40.66564524349381, "lon": 15.914160379394056, "elevation_m": None},
    "VAG_C2": {"name": "Vaglio – Chiesa, verticale C2", "group": "CHIESA", "lat": 40.66564524349381, "lon": 15.914160379394056, "elevation_m": None},
    "VAG_M1": {"name": "Vaglio – Museo, verticale M1", "group": "MUSEO", "lat": 40.66742456965478, "lon": 15.916780949585764, "elevation_m": None},
    "VAG_M2": {"name": "Vaglio – Villa Museo, verticale M2", "group": "VILLA MUSEO", "lat": 40.66715541624767, "lon": 15.915731436710464, "elevation_m": None},
    "VAG_M3": {"name": "Vaglio – Villa Museo, verticale M3", "group": "VILLA MUSEO", "lat": 40.66715541624767, "lon": 15.915731436710464, "elevation_m": None},
    "VAG_PZ1": {"name": "Vaglio – Piezometro 1", "group": "PIEZOMETRI", "lat": 40.667574562013975, "lon": 15.91569219409092, "elevation_m": None},
    "VAG_PZ2": {"name": "Vaglio – Piezometro 2", "group": "PIEZOMETRI", "lat": 40.667574562013975, "lon": 15.91569219409092, "elevation_m": None},
    "VAG_PZ3": {"name": "Vaglio – Piezometro 3", "group": "PIEZOMETRI", "lat": 40.667574562013975, "lon": 15.91569219409092, "elevation_m": None},
    "VAG_PZ4": {"name": "Vaglio – Piezometro 4", "group": "PIEZOMETRI", "lat": 40.667574562013975, "lon": 15.91569219409092, "elevation_m": None},
}
STATION_NOTES = {
    "VAG_C1": "Sensori Aranet di umidità del terreno (grado di saturazione) a 12, 40 e 60 cm. Gruppo Aranet 'CHIESA'.",
    "VAG_C2": "Sensori Aranet di umidità del terreno (grado di saturazione) a 12, 40 e 70 cm. Gruppo Aranet 'CHIESA'.",
    "VAG_M1": "Sensori Aranet di umidità del terreno (grado di saturazione) a 12, 40 e 60 cm. Gruppo Aranet 'MUSEO'.",
    "VAG_M2": "Sensori Aranet di umidità del terreno (grado di saturazione) a 12, 20, 40 e 60 cm. Gruppo Aranet 'VILLA MUSEO'.",
    "VAG_M3": "Sensori Aranet di umidità del terreno (grado di saturazione) a 12, 40 e 60 cm. Gruppo Aranet 'VILLA MUSEO'.",
}
for k in ("VAG_PZ1", "VAG_PZ2", "VAG_PZ3", "VAG_PZ4"):
    STATION_NOTES[k] = ("Piezometro con trasduttore di pressione 4–20 mA collegato a nodo Aranet: livello dell'acqua sopra "
                        "il sensore (0–500 cm) e corrente del segnale. Gruppo Aranet 'PIEZOMETRI'.")
POSITION_NOTE = ("Coordinate del sito (le verticali dello stesso gruppo e i quattro piezometri condividono le stesse "
                 "coordinate; nel portale i marcatori sono affiancati). Quota da definire.")

def instrument_of(station_id):
    return f"{station_id}_ARANET"

def instrument_meta(station_id):
    if station_id.startswith("VAG_PZ"):
        return {"manufacturer": "Aranet (SAF Tehnika)",
                "type": "Trasduttore di livello 4–20 mA (fondo scala 500 cm) su nodo Aranet"}
    return {"manufacturer": "Aranet (SAF Tehnika)",
            "type": "Sensori Aranet di umidità del terreno: grado di saturazione (%)"}

# ----------------------------------------------------------------------------
# 2. GRANDEZZE
# ----------------------------------------------------------------------------
NEW_VARIABLES = {
    "sr": {"label_it": "Grado di saturazione del terreno", "label_en": "Soil degree of saturation",
           "unit": "%", "aggregation": "mean", "plot": "line",
           "notes": "Grado di saturazione Sr = volume d'acqua / volume dei vuoti, in %, misurato dai sensori Aranet. "
                    "Nei file sorgente la colonna si chiama 'Volumetric water content (%)', ma il dato è un grado di "
                    "saturazione (100 % = terreno saturo); non è confrontabile direttamente con il contenuto d'acqua "
                    "volumetrico dei TEROS 10 (m3/m3), che è Sr × porosità."},
    "gwl": {"label_it": "Livello piezometrico (acqua sopra il sensore)", "label_en": "Piezometric level above sensor",
            "unit": "cm", "aggregation": "mean", "plot": "line",
            "notes": "Altezza della colonna d'acqua sopra il trasduttore del piezometro, calcolata dal segnale 4–20 mA: "
                     "livello = 31,25 × (I − 4 mA), cioè 0–500 cm. 0 cm = nessuna acqua sopra il sensore. "
                     "Valori con corrente < 3,8 mA (segnale fuori scala, guasto o alimentazione insufficiente) sono errati."},
    "i_loop": {"label_it": "Corrente del sensore (4–20 mA)", "label_en": "Sensor loop current (4–20 mA)",
               "unit": "mA", "aggregation": "mean", "plot": "line",
               "notes": "Grandezza diagnostica del piezometro: 4 mA = livello 0, 20 mA = 500 cm. Sotto 3,8 mA il segnale "
                        "è fuori dall'intervallo valido (segnalato come sospetto)."},
}
COLUMN_VAR = {"Volumetric water content (%)": "sr", "Level (cm)": "gwl", "Current (mA)": "i_loop"}
CODE = {"sr": "SR", "gwl": "GWL", "i_loop": "ILOOP"}
DIGITS = {"sr": 1, "gwl": 2, "i_loop": 2}

# ----------------------------------------------------------------------------
# 3. NOME SENSORE -> STAZIONE e PROFONDITÀ
#    'C2A40' = Chiesa, verticale 2, profondità 40 cm;  'PIEZOMETRO 3' = piezometro 3
# ----------------------------------------------------------------------------
def classify(sensor_name):
    m = re.fullmatch(r"([CM])(\d)A(\d+)", sensor_name.strip())
    if m:
        return f"VAG_{m[1]}{m[2]}", int(m[3])
    m = re.fullmatch(r"PIEZOMETRO\s*(\d)", sensor_name.strip(), re.I)
    if m:
        return f"VAG_PZ{m[1]}", None
    return None, None


def local_to_utc1(t):
    """t: timestamp locali (Europe/Rome) nell'ordine del file. L'ora ambigua di ottobre è CEST finché il tempo
    non è tornato indietro, CET dopo il salto all'indietro."""
    t = pd.Series(pd.to_datetime(t).values)
    second_pass = (t < t.cummax()).values               # righe dopo il salto all'indietro di fine ora legale
    loc = t.dt.tz_localize("Europe/Rome", ambiguous=~second_pass, nonexistent="NaT")
    return loc.dt.tz_convert("Etc/GMT-1").dt.tz_localize(None)


def read_files():
    files = sorted(glob.glob(os.path.join(INPUT_DIR, "*.xlsx")))
    files = [p for p in files if re.search(r"Sensor_?data", os.path.basename(p))]
    seen, parts, used = {}, {}, {}
    for p in files:
        h = hashlib.md5(open(p, "rb").read()).hexdigest()
        name = re.sub(r"^[0-9a-f]{8}-", "", os.path.basename(p))
        if h in seen:
            print("duplicato identico scartato:", name, "=", seen[h]); continue
        seen[h] = name
        m = re.search(r"(\d{4}-\d{2}-\d{2})-(\d{4}-\d{2}-\d{2})", name)
        export_end = m[2] if m else "0000"
        wb = CalamineWorkbook.from_path(p)
        for sheet in wb.sheet_names:
            rows = wb.get_sheet_by_name(sheet).to_python()
            meta = {r[0]: r[1] for r in rows[:3] if r}
            hdr = rows[3] if len(rows) > 3 else []
            sid0, sname = str(meta.get("Sensor ID", "")).strip(), str(meta.get("Sensor Name", "")).strip()
            station, depth = classify(sname)
            if station is None:
                print("!! sensore non riconosciuto:", name, sheet, sname); continue
            data = rows[4:]
            if not data:
                continue
            t_utc = local_to_utc1([r[0] for r in data])
            for j, col in enumerate(hdr[1:], start=1):
                var = COLUMN_VAR.get(col)
                if var is None:
                    continue
                v = pd.to_numeric(pd.Series([r[j] if len(r) > j else None for r in data]).replace("", np.nan),
                                  errors="coerce")
                ok = v.notna().values & t_utc.notna().values
                if not ok.any():
                    continue
                d = pd.DataFrame({"time": t_utc[ok].dt.round("min").values, "value": v[ok].values})
                d["export_end"] = export_end
                key = (station, var, depth)
                parts.setdefault(key, []).append(d)
                used.setdefault(key, {"sensor_id": sid0, "sensor_name": sname, "group": meta.get("Sensor Group"),
                                      "sources": []})["sources"].append(
                    {"file": name, "sheet": sheet, "column": col, "n_values": int(ok.sum())})
        print("letto:", name)
    series = {}
    for key, ps in parts.items():
        d = pd.concat(ps)
        n_in = len(d)
        # a parità di istante vince l'esportazione più recente; poi un solo valore per minuto
        d = d.sort_values(["time", "export_end"], ascending=[True, False]).drop_duplicates("time", keep="first")
        series[key] = {"data": d.set_index("time")[["value"]], "dup": n_in - len(d), **used[key]}
    return series


# ----------------------------------------------------------------------------
# 4. CONTROLLO DI QUALITÀ
# ----------------------------------------------------------------------------
def qc(sid, var, d, current=None):
    """Restituisce flag e righe di log. current: serie della corrente (per i livelli dei piezometri)."""
    flag = np.zeros(len(d), dtype=np.int8)
    log = []

    def mark(mask, f, rule):
        mask = np.asarray(mask, dtype=bool) & (flag < f)
        if mask.any():
            flag[mask] = f
            t = d.index[mask]
            log.append({"series_id": sid, "rule": rule, "flag": f, "n": int(mask.sum()),
                        "first": t.min().strftime(TFMT), "last": t.max().strftime(TFMT)})

    v = d["value"]
    r = RULES["range_by_variable"].get(var)
    if r:
        mark((v < r["min"]) | (v > r["max"]), 2, f"fuori range [{r['min']}, {r['max']}]")
    ar = RULES.get("aranet", {})
    if var == "gwl" and current is not None:
        lim = ar.get("loop_current_min_mA", 3.8)
        i = current.reindex(d.index)
        mark((i < lim).values, 2, f"corrente < {lim} mA (segnale 4–20 mA fuori scala)")
        mark(i.isna().values, 1, "corrente non disponibile allo stesso istante")
    if var == "sr" and ar.get("sr_low_suspect") is not None:
        mark((v <= ar["sr_low_suspect"]).values, 1, f"grado di saturazione <= {ar['sr_low_suspect']} % (terreno completamente secco: probabile perdita di contatto)")
    if var == "i_loop":
        lim = ar.get("loop_current_min_mA", 3.8)
        mark((v < lim).values, 1, f"corrente < {lim} mA (segnale 4–20 mA fuori scala)")
    sp = ar.get("spike_by_variable", {}).get(var)
    if sp:
        # picco isolato: scarto da ENTRAMBI i valori adiacenti (entro max_gap_min) > threshold, adiacenti coerenti tra loro
        vv = v.where(flag < 2)
        dt_prev = d.index.to_series().diff().dt.total_seconds().div(60).values
        dt_next = (-d.index.to_series().diff(-1)).dt.total_seconds().div(60).values
        prev, nxt = vv.shift(1), vv.shift(-1)
        close = (dt_prev <= sp["max_gap_min"]) & (dt_next <= sp["max_gap_min"])
        iso_ = ((vv - prev).abs() > sp["threshold"]) & ((vv - nxt).abs() > sp["threshold"]) \
            & ((prev - nxt).abs() <= sp["neighbor_tolerance"])
        mark(iso_.values & close, 1, f"picco isolato > {sp['threshold']} rispetto ai valori adiacenti")
    for w in RULES.get("windows", []):
        if sid in w["series"]:
            m = (d.index >= pd.Timestamp(w["from"])) & (d.index <= pd.Timestamp(w["to"]))
            mark(m, w["flag"], w["reason"])
    return flag, log


# ----------------------------------------------------------------------------
# 5. SCRITTURA
# ----------------------------------------------------------------------------
def write_raw(sid, d, var):
    raw_dir = os.path.join(OUT_DIR, "data", "raw", sid)
    os.makedirs(raw_dir, exist_ok=True)
    for f in glob.glob(os.path.join(raw_dir, "*.csv")):
        os.remove(f)
    years = sorted(set(d.index.year))
    for y in years:
        dy = d[d.index.year == y]
        pd.DataFrame({"time": dy.index.strftime(TFMT), "value": dy["value"].round(DIGITS[var]).values,
                      "flag": dy["flag"].values}).to_csv(os.path.join(raw_dir, f"{y}.csv"), index=False)
    return years


def nominal_step(index):
    """Passo nominale in minuti per ogni istante: mediana mobile dei passi (gestisce i cambi 1 -> 5 -> 10 min)."""
    dt = index.to_series().diff().dt.total_seconds().div(60)
    return dt.rolling(61, center=True, min_periods=5).median().bfill().ffill().clip(lower=1)


def aggregate(d, freq, var):
    g = d["value"].where(d["flag"] < 2)
    rs = g.resample(freq, label="left")
    step = nominal_step(d.index)
    exp = (({"1h": 60, "1D": 1440}[freq]) / step.resample(freq, label="left").median())
    out = pd.DataFrame({"value": rs.mean(), "min": rs.min(), "max": rs.max(), "n": rs.count()})
    out["coverage"] = (out["n"] / exp.reindex(out.index)).clip(upper=1).round(3)
    out = out[out["n"] > 0].copy()
    for c in ("value", "min", "max"):
        out[c] = out[c].round(DIGITS[var] + (1 if c == "value" else 0))
    out["n"] = out["n"].astype(int)
    out.index = out.index.strftime("%Y-%m-%d" if freq == "1D" else TFMT)
    out.index.name = "time"
    return out


def iso(ts):
    return pd.Timestamp(ts).strftime("%Y-%m-%dT%H:%M+01:00")


def gaps_over_24h(index):
    t = pd.Series(index)
    dt = t.diff()
    return [{"from": iso(t[i - 1]), "to": iso(t[i]), "hours": round(dt[i].total_seconds() / 3600, 1)}
            for i in dt.index[dt > pd.Timedelta(hours=24)]]


def main():
    cat_path = os.path.join(OUT_DIR, "catalog.json")
    catalog = json.load(open(cat_path, encoding="utf-8"))
    old_aranet = {s["series_id"] for s in catalog["series"] if s["instrument_id"].endswith("_ARANET")}
    catalog["series"] = [s for s in catalog["series"] if s["series_id"] not in old_aranet]
    catalog["stations"] = [s for s in catalog["stations"] if s["station_id"] not in STATIONS]
    catalog["instruments"] = [i for i in catalog["instruments"] if i["station_id"] not in STATIONS]
    catalog["variables"].update(NEW_VARIABLES)

    series = read_files()
    currents = {k[0]: v["data"]["value"] for k, v in series.items() if k[1] == "i_loop"}
    log, out_series, stations_used = [], [], set()
    for (station, var, depth), s in sorted(series.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2] or 0)):
        sid = f"{station}_{CODE[var]}" + (f"_{depth:03d}" if depth else "")
        d = s["data"].copy()
        flag, lg = qc(sid, var, d, current=currents.get(station) if var == "gwl" else None)
        d["flag"] = flag
        log += lg
        if s["dup"]:
            log.append({"series_id": sid, "rule": "timestamp duplicati rimossi (sovrapposizione tra file o "
                        "arrotondamento al minuto)", "flag": None, "n": s["dup"], "first": None, "last": None})
        years = write_raw(sid, d, var)
        for rule, freq in (("1h", "1h"), ("1d", "1D")):
            aggregate(d, freq, var).to_csv(os.path.join(OUT_DIR, "data", "agg", f"{sid}_{rule}.csv"))
        steps = d.index.to_series().diff().dt.total_seconds().div(60)
        step_recent = float(steps[-5000:].median())
        notes = list(QC_NOTES.get(sid, [])) + list(QC_NOTES.get(station + "_*", []))
        if s["dup"]:
            notes.append(f"{s['dup']} timestamp duplicati (sovrapposizione tra esportazioni o arrotondamento al minuto): "
                         "a parità di istante si usa l'esportazione più recente.")
        valid = d[d.flag < 2]
        label = NEW_VARIABLES[var]["label_it"] + (f" {depth} cm" if depth else "") + f" – {STATIONS[station]['name']}"
        stations_used.add(station)
        out_series.append({
            "series_id": sid, "instrument_id": instrument_of(station), "station_id": station, "variable": var,
            "depth_m": depth / 100 if depth else None, "sensor_model": "Aranet", "logger_port": None,
            "sensor_serial": s["sensor_id"], "sensor_name": s["sensor_name"], "sensor_group": s["group"],
            "label": label, "unit": NEW_VARIABLES[var]["unit"], "aggregation": "mean",
            "step_min": step_recent,
            "start": iso(d.index.min()), "end": iso(d.index.max()), "n_values": int(len(d)),
            "min": float(d.value.min()), "max": float(d.value.max()),
            "valid_start": iso(valid.index.min()) if len(valid) else None,
            "valid_end": iso(valid.index.max()) if len(valid) else None,
            "status": "active", "gaps_over_24h": gaps_over_24h(d.index), "qc_notes": notes,
            "sources": s["sources"],
            "data": {"format": "csv: time,value,flag", "raw": f"data/raw/{sid}/{{year}}.csv", "years": years,
                     "agg_1h": f"data/agg/{sid}_1h.csv", "agg_1d": f"data/agg/{sid}_1d.csv"},
            "qc_summary": {"n_total": int(len(d)), "n_valid": int((d.flag == 0).sum()),
                           "n_suspect": int((d.flag == 1).sum()), "n_bad": int((d.flag == 2).sum()),
                           "duplicates_removed": int(s["dup"])},
        })
        print(f"{sid:18s} {s['sensor_name']:13s} n={len(d):7d} sosp={int((d.flag==1).sum()):6d} "
              f"err={int((d.flag==2).sum()):6d} dup={s['dup']:5d} passo={step_recent:g} min  "
              f"{d.index.min():%Y-%m-%d} -> {d.index.max():%Y-%m-%d}  anni={years}")

    for st in sorted(stations_used):
        catalog["stations"].append({"station_id": st, **STATIONS[st], **SITE, "device": "Aranet",
                                    "notes": STATION_NOTES[st] + " " + POSITION_NOTE})
        catalog["instruments"].append({"instrument_id": instrument_of(st), "station_id": st, **instrument_meta(st)})
    catalog["series"] += out_series
    catalog["generated"] = pd.Timestamp.now(tz="Etc/GMT-1").strftime("%Y-%m-%dT%H:%M:%S+01:00")
    catalog["conventions"]["aranet"] = (
        "Sensori Aranet (pipeline/ingest_aranet.py): gruppi CHIESA, MUSEO, VILLA MUSEO e PIEZOMETRI. Orari dei file in ora "
        "locale (CET/CEST) convertiti in UTC+1 e arrotondati al minuto. Nome sensore 'C2A40' = verticale C2, profondità 40 cm. "
        "Grado di saturazione (variabile sr, %) per i sensori nel terreno; livello (gwl, cm) e corrente (i_loop, mA) per i piezometri.")
    catalog["qc_rules"] = {k: v for k, v in RULES.items() if not k.startswith("_")}
    with open(cat_path, "w", encoding="utf-8") as fh:
        json.dump(catalog, fh, ensure_ascii=False, indent=2)

    # qc_log: sostituisce le righe delle serie Aranet
    qpath = os.path.join(OUT_DIR, "data", "qc_log.csv")
    old = pd.read_csv(qpath) if os.path.exists(qpath) else pd.DataFrame()
    if len(old):
        old = old[~old["series_id"].isin(old_aranet | {s["series_id"] for s in out_series})]
    q = pd.concat([old, pd.DataFrame(log)])
    q["flag"] = pd.to_numeric(q["flag"], errors="coerce").astype(float)
    q.to_csv(qpath, index=False)

    # series.csv: vista piatta di tutto il catalogo
    cols = ["series_id", "station_id", "instrument_id", "variable", "label", "unit", "depth_m", "sensor_model",
            "logger_port", "aggregation", "step_min", "start", "end", "n_values", "min", "max", "status"]
    flat = pd.DataFrame([{k: s.get(k) for k in cols} | {"derived_from": s.get("derived_from"),
                          "n_gaps_over_24h": len(s.get("gaps_over_24h") or [])} for s in catalog["series"]])
    flat.to_csv(os.path.join(OUT_DIR, "series.csv"), index=False, encoding="utf-8-sig")
    print(f"\nserie Aranet: {len(out_series)}, stazioni: {len(stations_used)}; righe QC: {len(log)}")


# Note di qualità emerse dall'analisi dei dati (orari UTC+1). Chiave '<STAZIONE>_*' = nota per tutte le serie della stazione.
QC_NOTES = {
    "VAG_C2_*": ["I sensori della verticale C2 hanno oscillazioni molto ampie anche nell'arco di un giorno (escursione giornaliera "
                 "mediana 16–36 punti %, contro 1–5 delle altre verticali) e cadute improvvise verso valori bassi: andamento "
                 "probabilmente dovuto al sensore (contatto o collegamento), da interpretare con cautela."],
    "VAG_C2_SR_012": ["Lunghi periodi con valori prossimi a 0 % (es. febbraio–aprile 2024), segnalati come sospetti (flag 1). "
                      "Il sensore non registra più dal 18 dicembre 2024 (foglio vuoto nelle esportazioni 2025–2026)."],
    "VAG_C1_SR_012": ["Registrazioni terminate il 5 giugno 2025 (foglio vuoto nelle esportazioni successive)."],
    "VAG_C1_SR_040": ["Dati solo da maggio a ottobre 2024 e da maggio a novembre 2025."],
    "VAG_M1_SR_012": ["Registrazioni regolari fino a gennaio 2025, poi sporadiche fino al 22 aprile 2025."],
    "VAG_M1_SR_040": ["Registrazioni regolari fino a febbraio 2025, poi sporadiche fino al 30 aprile 2025."],
    "VAG_M1_SR_060": ["Dal 22 giugno 2024 (ripresa dopo una lacuna) l'andamento cambia: valori più bassi (circa 55 %) e molto "
                      "rumorosi, con oscillazioni settimanali fino a 50–90 punti %; da interpretare con cautela."],
    "VAG_M3_SR_012": ["Registrazioni terminate a febbraio 2025 (sporadiche fino al 19 aprile 2025)."],
    "VAG_M3_SR_060": ["Dopo la lacuna di gennaio–marzo 2026 il valore riparte da circa 42 % (prima 93–100 %): salto non "
                      "spiegato da piogge, da verificare (possibile spostamento o sostituzione del sensore)."],
    "VAG_PZ1_GWL": ["Fino ad agosto 2024 livello ≈ 0 cm (corrente ≈ 4,0 mA: nessuna acqua sopra il sensore), con un'unica risalita "
                    "fino a 15 cm il 4 agosto 2024 pomeriggio, in coincidenza con un temporale (10,9 mm al pluviometro CFD). "
                    "Dal 13 settembre 2024 avaria: dati errati (flag 2)."],
    "VAG_PZ2_GWL": ["Corrente fuori dal campo 4–20 mA (1–8 mA con oscillazioni rapide) già dal 30 gennaio 2024: tutti i livelli "
                    "sono considerati errati (flag 2). La serie della corrente resta consultabile come diagnostica."],
    "VAG_PZ3_GWL": ["Unico piezometro con un segnale significativo: da febbraio a giugno 2024 livello fino a circa 60–84 cm "
                    "sopra il sensore, poi 0 cm da luglio a settembre 2024. Dal 19 settembre 2024 avaria: dati errati (flag 2)."],
    "VAG_PZ4_GWL": ["Livello ≈ 0 cm (nessuna acqua sopra il sensore) fino all'11 agosto 2024; dal 12 agosto 2024 avaria: dati "
                    "errati (flag 2). Registrazioni terminate il 12 settembre 2025."],
    "VAG_PZ1_ILOOP": ["Passo 1 minuto fino al 10 maggio 2024, poi 10 minuti."],
    "VAG_PZ3_ILOOP": ["Passo 1 minuto fino al 10 maggio 2024, poi 5 minuti."],
}
for _k in ("VAG_PZ1", "VAG_PZ2", "VAG_PZ3", "VAG_PZ4"):
    QC_NOTES.setdefault(_k + "_*", []).append(
        "Nel 2025 la corrente resta sempre sotto 1,5 mA (fuori dal campo 4–20 mA): i piezometri non forniscono dati validi.")
QC_NOTES["VAG_PZ1_GWL"].insert(0, "Passo 1 minuto fino al 10 maggio 2024, poi 10 minuti.")
QC_NOTES["VAG_PZ3_GWL"].insert(0, "Passo 1 minuto fino al 10 maggio 2024, poi 5 minuti.")
_COMMON = ("Lacune comuni a tutti i sensori Aranet (interruzione della trasmissione, non dei singoli sensori): 24–25 marzo 2024, "
           "13 ottobre – 5 dicembre 2024, 18–31 dicembre 2024 (periodo non esportato), 18 marzo – 4 aprile 2025, "
           "5 giugno – 31 agosto 2025.")
for _k in ("VAG_C1", "VAG_C2", "VAG_M1", "VAG_M2", "VAG_M3", "VAG_PZ1", "VAG_PZ2", "VAG_PZ3", "VAG_PZ4"):
    QC_NOTES.setdefault(_k + "_*", []).append(_COMMON)

if __name__ == "__main__":
    main()
