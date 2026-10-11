"""
build_vaglio.py — genera dati standard, aggregati e catalog.json per il portale IoT_Vaglio.

Input  (INPUT_DIR):
  - file CSV 'Intensità Pioggia' del pluviometro di Vaglio di Basilicata (mm/h, passo 1 min, ora locale)
  - file xlsx 'Vaglio_Meter_S3_<anno>.xlsx' (sensori nel terreno: TEROS 10 e TEROS 21, passo 5 min)
Output (OUT_DIR):
  - data/raw/<serie>/<anno>.csv          time,value,flag   (dato originale)
  - data/agg/<serie>_10min.csv           solo pioggia
  - data/agg/<serie>_1h.csv, _1d.csv     aggregati
  - data/qc_log.csv                      valori segnalati
  - catalog.json, series.csv             metadati

RIFERIMENTO TEMPORALE: UTC+1 fisso (senza ora legale) per tutte le misure.
Il pluviometro è in ora locale (CET/CEST) e viene convertito; i file METER hanno già la colonna 'Time UTC+1'.

Esecuzione:
  INPUT_DIR=<cartella dei file> OUT_DIR=<radice del repo> python pipeline/build_vaglio.py
"""
import glob, hashlib, json, os, re
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd

INPUT_DIR = os.environ.get("INPUT_DIR", ".")
OUT_DIR = os.environ.get("OUT_DIR", ".")
HERE = os.path.dirname(os.path.abspath(__file__))
RULES = json.load(open(os.path.join(HERE, "qc_rules.json"), encoding="utf-8"))
TZ = timezone(timedelta(hours=1))
TFMT = "%Y-%m-%d %H:%M"
RAIN_START = pd.Timestamp("2023-01-01 00:00")
RAIN_END = pd.Timestamp("2026-09-30 22:59")   # 30/09/2026 23:59 ora locale CEST = 22:59 UTC+1


def dms(g, m, s):
    return round(g + m / 60 + s / 3600, 6)


STATIONS = {
    "VAG_CF": {
        "name": "Vaglio di Basilicata (pluviometro CFD)",
        "site": "Vaglio di Basilicata", "municipality": "Vaglio di Basilicata (PZ)",
        "lat": dms(40, 40, 10), "lon": dms(15, 54, 55), "elevation_m": 991,
        "owner": "Centro Funzionale Decentrato Basilicata – Regione Basilicata",
        "notes": "Pluviometro della rete regionale. Coordinate: 40°40'10\" N, 15°54'55\" E; altitudine 991 m s.l.m.",
    },
    "VAG_S3": {
        "name": "Vaglio – Nodo S3 (METER z6-18720)",
        "site": "Vaglio di Basilicata", "municipality": "Vaglio di Basilicata (PZ)",
        "lat": 40.6673775, "lon": 15.9168308, "elevation_m": 939,
        "owner": "Università di Salerno",
        "device": "METER z6-18720",
        "notes": "Nodo METER per il terreno (z6-18720): TEROS 10 (contenuto d'acqua), TEROS 21 (potenziale matriciale "
                 "e temperatura), profondità 12, 40 e 60 cm.",
    },
}

INSTRUMENTS = {
    "VAG_CF_RAIN": {"station_id": "VAG_CF", "manufacturer": "Centro Funzionale Decentrato Regione Basilicata",
                    "type": "Pluviometro"},
    "VAG_S3_METER": {"station_id": "VAG_S3", "manufacturer": "METER Group",
                     "type": "Datalogger METER z6-18720 con sensori TEROS 10 (contenuto d'acqua) e TEROS 21 (potenziale matriciale e temperatura nel terreno)"},
}

VARIABLES = {
    "rain": {"label_it": "Pioggia", "label_en": "Rainfall", "unit": "mm", "aggregation": "sum", "plot": "bar",
             "notes": "Altezza di pioggia caduta nell'intervallo che termina al timestamp."},
    "vwc": {"label_it": "Contenuto d'acqua del terreno", "label_en": "Soil water content (volumetric)",
            "unit": "m3/m3", "aggregation": "mean", "plot": "line"},
    "t_soil": {"label_it": "Temperatura del terreno", "label_en": "Soil temperature",
               "unit": "°C", "aggregation": "mean", "plot": "line"},
    "psi": {"label_it": "Potenziale matriciale del terreno", "label_en": "Soil matric potential",
            "unit": "kPa", "aggregation": "mean", "plot": "line",
            "notes": "Valori negativi = suzione. TEROS 21: accuratezza dichiarata tra -9 e -100 kPa; "
                     "valori > -9 kPa (prossimi alla saturazione) sono indicativi."},
}

# mappa delle colonne METER: sensore -> (variabile, colonna dati, porta logger, profondità cm)
METER_PORTS = {
    1: ("T10", 12, ["vwc"]), 2: ("T10", 40, ["vwc"]), 3: ("T10", 60, ["vwc"]),
    4: ("T21", 12, ["psi", "t_soil"]), 5: ("T21", 40, ["psi", "t_soil"]), 6: ("T21", 60, ["psi", "t_soil"]),
}
SHORT = {"vwc": "VWC", "psi": "PSI", "t_soil": "TSOIL"}
METER_STEP_MIN = 5


def clean_name(name):
    """Toglie il prefisso esadecimale aggiunto dal caricamento dei file (es. '78de54a5-')."""
    return re.sub(r"^[0-9a-f]{8}-", "", name)


def sid_of(station, var, depth_cm=None):
    code = "RAIN" if var == "rain" else SHORT[var]
    return f"{station}_{code}" + (f"_{depth_cm:03d}" if depth_cm else "")


def iso(ts):
    return pd.Timestamp(ts).strftime("%Y-%m-%dT%H:%M+01:00")


# ----------------------------------------------------------------------------
# 1. PIOGGIA (pluviometro, mm/h -> mm per minuto, ora locale -> UTC+1)
# ----------------------------------------------------------------------------
def read_rain():
    files = sorted(p for p in glob.glob(os.path.join(INPUT_DIR, "*.csv"))
                   if "Pioggia" in os.path.basename(p) and "Incrementi" not in os.path.basename(p))
    seen, rows, used = {}, [], []
    for p in files:
        raw = open(p, "rb").read()
        h = hashlib.md5(raw).hexdigest()
        if h in seen:
            print("duplicato identico scartato:", os.path.basename(p))
            continue
        seen[h] = p
        lines = raw.decode("utf-8-sig").splitlines()
        if len(lines) < 3 or not lines[1].startswith("Giorno Ora"):
            print("!! formato non riconosciuto:", os.path.basename(p))
            continue
        used.append(clean_name(os.path.basename(p)))
        for line in lines[2:]:
            parts = line.split(";")
            if len(parts) != 3 or parts[2].strip('"') != "mm/h":
                continue                                   # righe 'nessun dato disponibile' ignorate
            try:
                t = pd.to_datetime(parts[0], format="%d/%m/%Y %H:%M:%S")
                v = float(parts[1].strip('"').replace(",", "."))
            except ValueError:
                continue
            rows.append((t, v))
    df = pd.DataFrame(rows, columns=["time", "mmh"])
    occ = df.groupby("time").cumcount()                   # ora ambigua di fine ora legale: 1a occorrenza = CEST
    loc = df.time.dt.tz_localize("Europe/Rome", ambiguous=(occ == 0).values, nonexistent="NaT")
    df["t"] = loc.dt.tz_convert("Etc/GMT-1").dt.tz_localize(None)
    d = df.dropna(subset=["t"]).drop_duplicates("t").set_index("t").sort_index()
    grid = pd.date_range(RAIN_START, RAIN_END, freq="1min")
    d = d.reindex(grid)
    v = d["mmh"]
    p, n = v.shift(1), v.shift(-1)
    iso_mask = ((v - p).abs() > RULES["spike_by_series"]["VAG_CF_RAIN"]["threshold"]) \
        & ((v - n).abs() > RULES["spike_by_series"]["VAG_CF_RAIN"]["threshold"]) \
        & ((p - n).abs() <= RULES["spike_by_series"]["VAG_CF_RAIN"]["neighbor_tolerance"])
    d["mm"] = d["mmh"] / 60.0
    d["flag"] = 0
    d.loc[d["mm"] > RULES["range_by_variable"]["rain"]["max"], "flag"] = 2
    d.loc[iso_mask & d["mmh"].notna(), "flag"] = 1
    print(f"pioggia: file usati {len(used)}, minuti attesi {len(grid)}, mancanti {int(d.mmh.isna().sum())}, "
          f"picchi isolati {int((d.flag == 1).sum())}")
    return d, used


# ----------------------------------------------------------------------------
# 2. TERRENO (METER xlsx: contenuto d'acqua e potenziale matriciale)
# ----------------------------------------------------------------------------
def read_soil():
    acc, used = {}, []
    for p in sorted(glob.glob(os.path.join(INPUT_DIR, "*Meter*.xlsx"))):
        name = clean_name(os.path.basename(p))
        used.append(name)
        x = pd.read_excel(p, sheet_name=None, engine="openpyxl")
        for sheet, df in x.items():
            m = re.match(r"Port(\d)-(\d+)cm-(T10|T21)$", sheet)
            if not m:
                continue
            port = int(m[1])
            if port not in METER_PORTS:
                continue
            sensor, depth, variables = METER_PORTS[port]
            base = f"Port{port}-{sensor}-{depth}cm"
            for var in variables:
                col = {"vwc": base, "psi": base + "(kPa)", "t_soil": base + "(°C)"}[var]
                if col not in df.columns:
                    print("!! colonna non trovata:", name, sheet, col)
                    continue
                t = pd.to_datetime(df["Time UTC+1"], errors="coerce")
                v = pd.to_numeric(df[col], errors="coerce")
                ok = t.notna() & v.notna()
                sid = sid_of("VAG_S3", var, depth)
                acc.setdefault(sid, {"var": var, "depth": depth, "port": port, "sensor": sensor,
                                     "parts": [], "files": set()})
                acc[sid]["parts"].append(pd.DataFrame({"time": t[ok], "value": v[ok]}))
                acc[sid]["files"].add(name)
    out = {}
    for sid, s in acc.items():
        d = pd.concat(s["parts"]).sort_values("time")
        n_dup = int(d.time.duplicated().sum())
        d = d.drop_duplicates("time").set_index("time")
        d["flag"] = 0
        r = RULES["range_by_variable"][s["var"]]
        bad = (d.value < r["min"]) | (d.value > r["max"])
        d.loc[bad, "flag"] = 2
        s.update({"data": d, "dup": n_dup, "files": sorted(s["files"])})
        out[sid] = s
        print(f"{sid}: campioni {len(d)}, duplicati rimossi {n_dup}, fuori range {int(bad.sum())}")
    return out, used


# ----------------------------------------------------------------------------
# 3. SCRITTURA: dati originali, aggregati, metadati
# ----------------------------------------------------------------------------
def fmt_val(x, var):
    return x.round({"vwc": 4, "psi": 2, "t_soil": 2, "rain": 4}[var])


def write_raw(sid, d, var):
    raw_dir = os.path.join(OUT_DIR, "data", "raw", sid)
    os.makedirs(raw_dir, exist_ok=True)
    years = sorted(set(d.index.year))
    for y in years:
        dy = d[d.index.year == y]
        out = pd.DataFrame({"time": dy.index.strftime(TFMT), "value": fmt_val(dy["value"], var).values,
                            "flag": dy["flag"].values})
        out.to_csv(os.path.join(raw_dir, f"{y}.csv"), index=False)
    return years


def agg_instant(d, freq, step_min, grid_index):
    g = d["value"].where(d["flag"] < 2)
    rs = g.resample(freq, label="left")
    exp = pd.Series(1, index=grid_index).resample(freq, label="left").sum()
    out = pd.DataFrame({"value": rs.mean(), "min": rs.min(), "max": rs.max(), "n": rs.count()})
    out["coverage"] = (out["n"] / exp.reindex(out.index)).clip(upper=1).round(3)
    out = out[out["n"] > 0]
    return out


def agg_rain(d, freq):
    g = d["mm"].where(d["flag"] < 2)
    rs = g.resample(freq, closed="right", label="left")
    exp = pd.Series(1, index=d.index).resample(freq, closed="right", label="left").sum()
    out = pd.DataFrame({"value": rs.sum(min_count=1), "max": rs.max(), "n": rs.count()})
    out["coverage"] = (out["n"] / exp.reindex(out.index)).clip(upper=1).round(3)
    out = out[(out["n"] > 0) & (out.index >= RAIN_START)]
    return out


def save_agg(sid, a, var, rule, instant=True):
    cols = ["value", "min", "max", "n", "coverage"] if instant else ["value", "max", "n", "coverage"]
    a = a[[c for c in cols if c in a]].copy()
    for c in ("value", "min", "max"):
        if c in a:
            a[c] = fmt_val(a[c], var)
    a["n"] = a["n"].astype(int)
    fmt = "%Y-%m-%d" if rule == "1d" else TFMT
    a.index = a.index.strftime(fmt)
    a.index.name = "time"
    path = os.path.join(OUT_DIR, "data", "agg", f"{sid}_{rule}.csv")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    a.to_csv(path)


def gaps_over_24h(index):
    t = pd.Series(index)
    dt = t.diff()
    return [{"from": iso(t[i - 1]), "to": iso(t[i]), "hours": round(dt[i].total_seconds() / 3600, 1)}
            for i in dt.index[dt > pd.Timedelta(hours=24)]]


def main():
    os.makedirs(os.path.join(OUT_DIR, "data"), exist_ok=True)
    log, catalog_series, source_files = [], [], []

    # --- pioggia
    rain, rain_files = read_rain()
    sid = "VAG_CF_RAIN"
    rain_d = rain.loc[rain["mmh"].notna(), ["mm", "flag"]].rename(columns={"mm": "value"})
    years = write_raw(sid, rain_d, "rain")
    for rule, freq in (("10min", "10min"), ("1h", "1h"), ("1d", "1D")):
        save_agg(sid, agg_rain(rain, freq), "rain", rule, instant=False)
    flagged = rain[(rain.flag > 0) & rain.mmh.notna()]
    for t, r in flagged.iterrows():
        log.append({"series_id": sid, "rule": "picco isolato > 20 mm/h", "flag": int(r.flag),
                    "n": 1, "first": t.strftime(TFMT), "last": t.strftime(TFMT)})
    catalog_series.append({
        "series_id": sid, "instrument_id": "VAG_CF_RAIN", "station_id": "VAG_CF", "variable": "rain",
        "depth_m": None, "sensor_model": None, "logger_port": None,
        "label": "Pioggia – Vaglio di Basilicata (pluviometro CFD)", "unit": "mm", "aggregation": "sum",
        "step_min": 1.0, "start": iso(rain_d.index.min()), "end": iso(rain_d.index.max()),
        "n_values": int(len(rain_d)), "min": float(rain_d.value.min()), "max": float(rain_d.value.max()),
        "status": "active", "gaps_over_24h": gaps_over_24h(rain_d.index), "qc_notes": [
            "Lacune di minuti senza dato: nelle aggregazioni sono indicate in n e coverage, non sono zero.",
            "Picchi isolati segnalati con flag 1 (inclusi nei totali)."],
        "sources": [{"file": f, "column": "Valore (mm/h, convertito in mm per minuto)"} for f in rain_files],
        "data": {"format": "csv: time,value,flag", "raw": f"data/raw/{sid}/{{year}}.csv", "years": years,
                 "agg_10min": f"data/agg/{sid}_10min.csv", "agg_1h": f"data/agg/{sid}_1h.csv",
                 "agg_1d": f"data/agg/{sid}_1d.csv"},
        "qc_summary": {"n_total": int(len(rain_d)), "n_valid": int((rain_d.flag == 0).sum()),
                       "n_suspect": int((rain_d.flag == 1).sum()), "n_bad": int((rain_d.flag == 2).sum()),
                       "duplicates_removed": 0},
    })

    # --- terreno
    soil, soil_files = read_soil()
    for sid, s in sorted(soil.items()):
        d = s["data"]
        var = s["var"]
        years = write_raw(sid, d, var)
        grid = pd.date_range(d.index.min(), d.index.max(), freq=f"{METER_STEP_MIN}min")
        agg_src = d.reindex(grid)
        agg_src["flag"] = agg_src["flag"].fillna(0)
        for rule, freq in (("1h", "1h"), ("1d", "1D")):
            a = agg_instant(agg_src, freq, METER_STEP_MIN, grid)
            save_agg(sid, a, var, rule, instant=True)
        for t, r in d[d.flag == 2].iterrows():
            log.append({"series_id": sid, "rule": "fuori range", "flag": 2, "n": 1,
                        "first": t.strftime(TFMT), "last": t.strftime(TFMT)})
        catalog_series.append({
            "series_id": sid, "instrument_id": "VAG_S3_METER", "station_id": "VAG_S3", "variable": var,
            "depth_m": s["depth"] / 100, "sensor_model": "TEROS 10" if s["sensor"] == "T10" else "TEROS 21",
            "logger_port": s["port"],
            "label": f"{VARIABLES[var]['label_it']} {s['depth']} cm – Vaglio – Nodo S3",
            "unit": VARIABLES[var]["unit"], "aggregation": "mean", "step_min": float(METER_STEP_MIN),
            "start": iso(d.index.min()), "end": iso(d.index.max()),
            "n_values": int(len(d)), "min": float(d.value.min()), "max": float(d.value.max()),
            "status": "active", "gaps_over_24h": gaps_over_24h(d.index),
            "qc_notes": ([f"{s['dup']} timestamp duplicati nei file sorgente: mantenuto il primo valore."]
                         if s["dup"] else []),
            "sources": [{"file": f} for f in s["files"]],
            "data": {"format": "csv: time,value,flag", "raw": f"data/raw/{sid}/{{year}}.csv", "years": years,
                     "agg_1h": f"data/agg/{sid}_1h.csv", "agg_1d": f"data/agg/{sid}_1d.csv"},
            "qc_summary": {"n_total": int(len(d)), "n_valid": int((d.flag == 0).sum()),
                           "n_suspect": 0, "n_bad": int((d.flag == 2).sum()),
                           "duplicates_removed": s["dup"]},
        })
        if s["dup"]:
            log.append({"series_id": sid, "rule": "timestamp duplicati rimossi", "flag": None,
                        "n": s["dup"], "first": None, "last": None})

    # --- catalogo
    pd.DataFrame(log).to_csv(os.path.join(OUT_DIR, "data", "qc_log.csv"), index=False)
    catalog = {
        "catalog_version": "0.1",
        "generated": datetime.now(TZ).isoformat(timespec="seconds"),
        "conventions": {
            "time_reference": "UTC+1 fisso (ora solare italiana, senza ora legale) per tutte le misure. "
                              "Timestamp in ISO 8601 con offset '+01:00'. Il pluviometro è convertito da ora locale "
                              "(CET/CEST); i file METER usano la colonna 'Time UTC+1'.",
            "series_id": "<STAZIONE>_<GRANDEZZA>[_<PROFONDITÀ cm, 3 cifre>]",
            "depth_m": "Profondità nel terreno sotto il piano campagna, positiva verso il basso, in metri.",
            "coordinates": "WGS84 (EPSG:4326), gradi decimali.",
            "data_format": "File CSV con intestazione. Dati originali: time,value,flag (un file per serie e per anno). "
                           "Aggregati: time,value,[min],max,n,coverage. time = 'YYYY-MM-DD HH:MM' in UTC+1. "
                           "flag: 0 valido, 1 sospetto, 2 errato. Aggregati calcolati sui soli flag < 2.",
            "aggregation_labels": "Grandezze istantanee: etichetta = inizio intervallo. Pioggia: ogni dato è riferito "
                                  "all'intervallo che termina al timestamp; l'etichetta indica l'inizio del periodo di cumulo.",
        },
        "variables": VARIABLES,
        "stations": [{"station_id": k, **v} for k, v in STATIONS.items()],
        "instruments": [{"instrument_id": k, **v} for k, v in INSTRUMENTS.items()],
        "series": catalog_series,
        "qc_rules": {k: v for k, v in RULES.items() if not k.startswith("_")},
    }
    with open(os.path.join(OUT_DIR, "catalog.json"), "w", encoding="utf-8") as fh:
        json.dump(catalog, fh, ensure_ascii=False, indent=2)
    flat = pd.DataFrame([{k: s[k] for k in ("series_id", "station_id", "instrument_id", "variable", "label",
                                             "unit", "depth_m", "sensor_model", "logger_port", "aggregation",
                                             "step_min", "start", "end", "n_values", "min", "max", "status")}
                         | {"n_gaps_over_24h": len(s["gaps_over_24h"])} for s in catalog_series])
    flat.to_csv(os.path.join(OUT_DIR, "series.csv"), index=False, encoding="utf-8-sig")
    print(flat[["series_id", "unit", "start", "end", "n_values", "n_gaps_over_24h"]].to_string(index=False))


if __name__ == "__main__":
    main()
