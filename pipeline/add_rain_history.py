"""
add_rain_history.py – aggiunge anni storici (es. 2015, 2016) del pluviometro CFD "Vaglio di Basilicata"
a un repository già costruito con build_vaglio.py, senza rielaborare gli anni già presenti.

Input   : INPUT_DIR  con i CSV mensili "… Intensità Pioggia … .csv" (stesso formato di build_vaglio.py) degli anni da
          aggiungere (HIST_START / HIST_END, di default 2015-01-01 00:00 → 2016-12-31 23:59 UTC+1).
Aggiorna: OUT_DIR/data/raw/VAG_CF_RAIN{,24H,CUM}/<anno>.csv   (nuovi anni)
          OUT_DIR/data/agg/VAG_CF_RAIN{,24H,CUM}_{10min,1h,1d}.csv   (righe storiche anteposte)
          OUT_DIR/catalog.json, series.csv, data/qc_log.csv
Stesse regole di build_vaglio.py (conversione mm/h → mm, ora locale → UTC+1, QC, cumulate): il modulo viene
importato e riusato. Lo script è idempotente (le righe storiche vengono sostituite a ogni esecuzione).

  INPUT_DIR=<cartella> OUT_DIR=<radice del repo> python pipeline/add_rain_history.py
"""
import importlib.util, json, os, sys, tempfile
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.environ.get("OUT_DIR", ".")
spec = importlib.util.spec_from_file_location("bv", os.path.join(HERE, "build_vaglio.py"))
bv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bv)

H0 = pd.Timestamp(os.environ.get("HIST_START", "2015-01-01 00:00"))
H1 = pd.Timestamp(os.environ.get("HIST_END", "2016-12-31 23:59"))
bv.RAIN_START, bv.RAIN_END = H0, H1
bv.INPUT_DIR = os.environ.get("INPUT_DIR", ".")
tmp = tempfile.mkdtemp()
bv.OUT_DIR = tmp

rain, files = bv.read_rain()
rain_d = rain.loc[rain["mmh"].notna(), ["mm", "flag"]].rename(columns={"mm": "value"})
r24, ytd, ysum = bv.derive_rain_series(rain)
series = {"VAG_CF_RAIN": ("rain", rain_d), "VAG_CF_RAIN24H": ("rain_24h", r24), "VAG_CF_RAINCUM": ("rain_cum", ytd)}

for sid, (var, d) in series.items():
    bv.write_raw(sid, d, var)
for rule, freq in (("10min", "10min"), ("1h", "1h"), ("1d", "1D")):
    bv.save_agg("VAG_CF_RAIN", bv.agg_rain(rain, freq), "rain", rule, instant=False)
    for sid in ("VAG_CF_RAIN24H", "VAG_CF_RAINCUM"):
        bv.save_agg_derived(sid, bv.agg_derived(series[sid][1], freq), series[sid][0], rule)

# --- unione con i dati esistenti (le righe < anno corrente più vecchio vengono sostituite)
def merge_csv(new_path, old_path):
    new = pd.read_csv(new_path, dtype=str, keep_default_na=False)
    old = pd.read_csv(old_path, dtype=str, keep_default_na=False) if os.path.exists(old_path) else new.iloc[0:0]
    old = old[~old["time"].isin(new["time"])]
    out = pd.concat([new, old], ignore_index=True).sort_values("time", kind="stable")
    out.to_csv(old_path, index=False)

for sid in series:
    for f in os.listdir(os.path.join(tmp, "data", "raw", sid)):                     # anni nuovi
        dst = os.path.join(OUT_DIR, "data", "raw", sid)
        os.makedirs(dst, exist_ok=True)
        merge_csv(os.path.join(tmp, "data", "raw", sid, f), os.path.join(dst, f))
    for rule in ("10min", "1h", "1d"):
        n = os.path.join(tmp, "data", "agg", f"{sid}_{rule}.csv")
        merge_csv(n, os.path.join(OUT_DIR, "data", "agg", f"{sid}_{rule}.csv"))

# --- indici completi per statistiche e lacune
def full_index(sid):
    d = os.path.join(OUT_DIR, "data", "raw", sid)
    return pd.concat([pd.read_csv(os.path.join(d, f), usecols=["time", "value", "flag"], parse_dates=["time"])
                      for f in sorted(os.listdir(d))], ignore_index=True)

CAT = os.path.join(OUT_DIR, "catalog.json")
cat = json.load(open(CAT, encoding="utf-8"))
by = {s["series_id"]: s for s in cat["series"]}
tot = lambda y: f"{y['year']}: {y['total_mm']:.1f} mm" + ("" if y["complete"] else " (incompleto)")
for sid, (var, _) in series.items():
    s = by[sid]
    f = full_index(sid)
    t = f["time"]
    s["start"], s["end"] = bv.iso(t.min()), bv.iso(t.max())
    s["n_values"] = int(len(f))
    s["min"], s["max"] = float(f.value.min()), (round(float(f.value.max()), 2) if sid != "VAG_CF_RAIN" else float(f.value.max()))
    s["gaps_over_24h"] = bv.gaps_over_24h(pd.DatetimeIndex(t))
    s["data"]["years"] = sorted(int(y) for y in set(t.dt.year))
    s["qc_summary"] = {"n_total": int(len(f)), "n_valid": int((f.flag == 0).sum()), "n_suspect": int((f.flag == 1).sum()),
                       "n_bad": int((f.flag == 2).sum()) if sid == "VAG_CF_RAIN" else 0, "duplicates_removed": 0}
    if sid == "VAG_CF_RAIN":
        old_src = [x for x in s["sources"] if x["file"] not in {bv.clean_name(os.path.basename(p)) for p in files}]
        s["sources"] = [{"file": x, "column": "Valore (mm/h, convertito in mm per minuto)"} for x in files] + old_src
        s["qc_notes"] = [n for n in s["qc_notes"] if not n.startswith("Dati storici")] + [
            "Dati storici 2015–2016 aggiunti con pipeline/add_rain_history.py: nel 2015 i dati partono dal 6 luglio 15:07 (UTC+1) "
            "(gennaio–giugno senza dato) e novembre 2015 è assente (il file sorgente contiene solo valori negativi datati "
            "11/10/2026, scartati); fra il 2016 e il 2023 non ci sono dati."]
    elif sid == "VAG_CF_RAIN24H":
        s["qc_notes"] = [("Dati 2015–2016: dalla prima misura (2015-07-06 15:07 UTC+1) le finestre con più di 60 minuti mancanti hanno flag 1. "
                          "Dati dal 2023: prima finestra completa 2023-01-01 23:59. Nei minuti senza dato di pioggia la serie non ha valore.")
                         if n.startswith("Prima finestra") else n for n in s["qc_notes"]]
    else:
        old_years = [y for y in s["cumulative_years"] if y["year"] not in {y2["year"] for y2 in ysum}]
        s["cumulative_years"] = sorted(ysum + old_years, key=lambda y: y["year"])
        totals = "; ".join(tot(y) for y in s["cumulative_years"])
        s["qc_notes"] = [("Totali: " + totals + ". Il 2026 arriva al 30 settembre.") if n.startswith("Totali:") else n
                         for n in s["qc_notes"]]

# qc_log: sostituisce le righe dei picchi storici
logp = os.path.join(OUT_DIR, "data", "qc_log.csv")
log = pd.read_csv(logp)
is_hist = (log.series_id == "VAG_CF_RAIN") & (log["first"].fillna("").str[:4].isin([str(y) for y in range(H0.year, H1.year + 1)]))
log = log[~is_hist]
fl = rain[(rain.flag > 0) & rain.mmh.notna()]
new = [{"series_id": "VAG_CF_RAIN", "rule": "picco isolato > 20 mm/h", "flag": int(r.flag), "n": 1,
        "first": t.strftime(bv.TFMT), "last": t.strftime(bv.TFMT)} for t, r in fl.iterrows()]
pd.concat([log, pd.DataFrame(new)], ignore_index=True).to_csv(logp, index=False)

cat["catalog_version"] = "0.4"
cat["generated"] = pd.Timestamp.now(tz=bv.TZ).isoformat(timespec="seconds")
with open(CAT, "w", encoding="utf-8") as fh:
    json.dump(cat, fh, ensure_ascii=False, indent=2)

flat_path = os.path.join(OUT_DIR, "series.csv")
flat = pd.read_csv(flat_path, encoding="utf-8-sig")
for sid in series:
    s = by[sid]
    i = flat.index[flat.series_id == sid][0]
    for k in ("start", "end", "n_values", "min", "max"):
        flat.at[i, k] = s[k]
    flat.at[i, "n_gaps_over_24h"] = len(s["gaps_over_24h"])
flat.to_csv(flat_path, index=False, encoding="utf-8-sig")
print("ok:", {sid: (by[sid]["start"], by[sid]["n_values"]) for sid in series}, "picchi isolati:", len(new))
