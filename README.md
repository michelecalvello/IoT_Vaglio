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
data/raw/<serie>/<anno>.csv          time,value,flag                 dato originale
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
| `VAG_S3_VWC_012`, `_040`, `_060` | Contenuto d'acqua del terreno (TEROS 10) | m³/m³ | 5 min |
| `VAG_S3_PSI_012`, `_040`, `_060` | Potenziale matriciale del terreno (TEROS 21) | kPa | 5 min |
| `VAG_S3_TSOIL_012`, `_040`, `_060` | Temperatura del terreno (TEROS 21) | °C | 5 min |

## Note

- Dati del nodo S3 disponibili fino al 31 dicembre 2025; i file 2026 non sono ancora inclusi.
- Nei file METER alcuni timestamp sono duplicati nella sorgente con valori leggermente diversi: si mantiene il primo, come segnalato in `catalog.json`.

## Fonti dei dati

- Pluviometro di Vaglio di Basilicata: Centro Funzionale Decentrato Basilicata – Regione Basilicata.
- Nodo S3 (terreno): Università di Salerno.

## Visualizzare il portale in locale

`python -m http.server` nella radice del repo e aprire http://localhost:8000.
