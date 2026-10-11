# IoT_Vaglio – Portale dei dati di monitoraggio di Vaglio di Basilicata

**Portale:** https://michelecalvello.github.io/IoT_Vaglio/

Dati di monitoraggio a Vaglio di Basilicata (PZ):
- **pioggia** dal pluviometro della rete regionale (Centro Funzionale Decentrato Basilicata – Regione Basilicata),
  passo 1 minuto, dal 1 gennaio 2023 al 30 settembre 2026;
- **contenuto d'acqua volumetrico**, **potenziale matriciale** e **temperatura del terreno** dal nodo S3
  (datalogger METER z6-18720, sensori TEROS 10 e TEROS 21), profondità 12, 40 e 60 cm, passo 5 minuti,
  dall'8 agosto 2023 al 31 dicembre 2025.

Riferimento temporale unico: **UTC+1** (ora solare, senza ora legale).

## Portale

Stesso aspetto e stessi comandi del portale [IoT_CavaSA](https://michelecalvello.github.io/IoT_CavaSA/): tema chiaro/scuro (pulsante ◐),
mappa delle stazioni e elenco delle serie a sinistra; in alto barra con intervallo di date, scelte rapide (1 g, 7 g, 30 g, 1 anno, Tutto),
risoluzione (automatica, giornaliera, oraria, 10 minuti per la pioggia, dato originale) e modalità del grafico (pannelli o assi multipli);
statistiche nell'intervallo visibile, esportazione CSV e scheda dei metadati (ⓘ) per ogni serie. Lo stato è nell'URL e si può condividere.

## Stazioni

| Stazione | Descrizione | Coordinate | Quota |
|---|---|---|---|
| `VAG_CF` | Vaglio di Basilicata – pluviometro (rete CFD) | 40°40'10" N, 15°54'55" E (40.669444, 15.915278) | 991 m s.l.m. |
| `VAG_S3` | Vaglio – Nodo S3 (terreno), datalogger METER z6-18720, Università di Salerno | 40.6673775, 15.9168308 | 939 m s.l.m. |

## Pipeline

```bash
export INPUT_DIR=<cartella con i file sorgente>   OUT_DIR=.
python pipeline/build_vaglio.py    # data/ + catalog.json + series.csv + data/qc_log.csv
```

I file sorgente sono:
- CSV `… Intensità Pioggia … .csv` (mm/h, passo 1 minuto, ora locale CET/CEST), uno per mese;
- `Vaglio_Meter_S3_<anno>.xlsx` (colonna `Time UTC+1`, sensori TEROS 10 e TEROS 21).

Lo script:
- converte la pioggia da mm/h a mm per minuto (mm = mm/h ÷ 60) e da ora locale a UTC+1;
- scarta i file identici (stesso contenuto);
- gestisce il cambio d'ora: l'ora ripetuta di ottobre resta distinta in UTC+1, quella saltata di marzo non crea lacune;
- applica le regole di qualità in `pipeline/qc_rules.json` (intervalli validi, picchi isolati);
- calcola gli aggregati e le lacune > 24 ore.

Per aggiungere uno strumento o una profondità: aggiornare `METER_PORTS`, `STATIONS` o `INSTRUMENTS` in `pipeline/build_vaglio.py`,
poi rieseguire lo script.

## Struttura

```
index.html, assets/        portale statico (Plotly, Leaflet) – nessun backend
catalog.json               metadati: stazioni, strumenti, serie, percorsi dei file, riepilogo QC
series.csv                 vista piatta del catalogo (Excel)
pipeline/                  script di generazione e regole QC
data/raw/<serie>/<anno>.csv          time,value,flag                 dato originale (anche le serie derivate, a 1 minuto)
data/agg/<serie>_10min.csv           time,value,max,n,coverage       pioggia, aggregato a 10 minuti
data/agg/<serie>_1h.csv              time,value,[min],max,n,coverage aggregato orario
data/agg/<serie>_1d.csv              idem, giornaliero
data/qc_log.csv            elenco dei valori segnalati e regola applicata
```

- `time`: `YYYY-MM-DD HH:MM` in UTC+1.
- `flag`: 0 valido · 1 sospetto (incluso negli aggregati) · 2 errato (escluso dagli aggregati).
- Grandezze istantanee (contenuto d'acqua, potenziale): media, minimo e massimo; etichetta = inizio intervallo.
- Pioggia: somma; ogni dato è riferito all'intervallo che termina al timestamp, quindi l'etichetta indica l'inizio del periodo di cumulo
  (es. `2026-04-14 13:40` = dalle 13:41 alle 13:50).
- `coverage`: frazione di dati presenti rispetto ai minuti attesi (1 = completo). Con `coverage` < 1 i totali sono sottostimati.

## Serie

| Serie | Grandezza | Unità | Passo |
|---|---|---|---|
| `VAG_CF_RAIN` | Pioggia | mm | 1 min |
| `VAG_CF_RAIN24H` | Pioggia cumulata nelle ultime 24 ore (derivata da `VAG_CF_RAIN`) | mm | 1 min |
| `VAG_CF_RAINCUM` | Pioggia cumulata dal 1° gennaio (derivata da `VAG_CF_RAIN`) | mm | 1 min |
| `VAG_S3_VWC_012`, `_040`, `_060` | Contenuto d'acqua del terreno (TEROS 10) | m³/m³ | 5 min |
| `VAG_S3_PSI_012`, `_040`, `_060` | Potenziale matriciale del terreno (TEROS 21) | kPa | 5 min |
| `VAG_S3_TSOIL_012`, `_040`, `_060` | Temperatura del terreno (TEROS 21) | °C | 5 min |

## Serie derivate dalla pioggia

Calcolate dallo script a passo 1 minuto, come il dato originale; ogni dato di pioggia è riferito all'intervallo che termina al suo timestamp.

- **`VAG_CF_RAIN24H`** – pioggia caduta nelle 24 ore che terminano al timestamp (somma mobile di 1440 minuti). Prima finestra completa: 2023-01-01 23:59.
  Nei minuti senza dato di pioggia la serie non ha valore. A mezzanotte coincide con il totale giornaliero del giorno appena concluso;
  il massimo giornaliero degli aggregati è la massima pioggia in 24 ore (73,0 mm il 15 aprile 2026).
- **`VAG_CF_RAINCUM`** – pioggia cumulata dal 1 gennaio ore 00:00, azzerata ogni anno. Il dato delle 00:00 del 1 gennaio chiude l'anno precedente
  (totale annuo), la cumulata riparte da 0 con il dato successivo. Totali: 2023 746,7 mm; 2024 616,6 mm; 2025 584,6 mm; 2026 (al 30 settembre) 660,8 mm.
- **Dati mancanti e flag**: i minuti senza dato valgono 0 nella somma, quindi la cumulata è sottostimata. `flag` = 1 (tratteggio nel portale) quando
  nella finestra di 24 ore mancano più di 60 minuti di dato (3 episodi: 18 giugno 2025, 14 ottobre 2025, 3 febbraio 2026), oppure quando nell'anno
  mancano più di 24 ore (lacune > 60 minuti): finora mai. Le soglie sono in `pipeline/qc_rules.json` (blocco `cumulative`).
- **Aggregati** (10 minuti, 1 ora, 1 giorno): `value` = valore a fine intervallo (cumulata a fine intervallo), `min` e `max` = estremi nell'intervallo,
  `flag` = massimo del flag; `n` e `coverage` come per le altre serie.

## Note

- Dati del nodo S3 disponibili fino al 31 dicembre 2025; i file 2026 non sono ancora inclusi.
- Nei file METER alcuni timestamp sono duplicati nella sorgente con valori leggermente diversi: si mantiene il primo, come segnalato in `catalog.json`.

## Fonti dei dati

- Pluviometro di Vaglio di Basilicata: Centro Funzionale Decentrato Basilicata – Regione Basilicata.
- Nodo S3 (terreno): Università di Salerno.

## Visualizzare il portale in locale

`python -m http.server` nella radice del repo e aprire http://localhost:8000.
