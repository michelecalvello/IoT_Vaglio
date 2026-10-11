# IoT_Vaglio – Portale dei dati di monitoraggio di Vaglio di Basilicata

**Portale:** https://michelecalvello.github.io/IoT_Vaglio/

Dati di monitoraggio a Vaglio di Basilicata (PZ):
- **pioggia** dal pluviometro della rete regionale (Centro Funzionale Decentrato Basilicata – Regione Basilicata),
  passo 1 minuto, dal 1 gennaio 2023 al 30 settembre 2026;
- **contenuto d'acqua volumetrico**, **potenziale matriciale** e **temperatura del terreno** dal nodo S3
  (datalogger METER z6-18720, sensori TEROS 10 e TEROS 21), profondità 12, 40 e 60 cm, passo 5 minuti,
  dall'8 agosto 2023 al 31 dicembre 2025;
- **prodotti a griglia da Google Earth Engine**: contenuto d'acqua del terreno, pioggia e temperatura dell'aria di **ERA5-Land**
  (pixel 0,1°, passo 1 ora) e contenuto d'acqua del terreno di **SMAP L4** (pixel ~9 km, medie su 3 ore),
  dal 1 gennaio 2023 al 30 settembre 2026.

Riferimento temporale unico: **UTC+1** (ora solare, senza ora legale).

## Portale

Stesso aspetto e stessi comandi del portale [IoT_CavaSA](https://michelecalvello.github.io/IoT_CavaSA/): tema chiaro/scuro (pulsante ◐),
mappa delle stazioni e elenco delle serie a sinistra; in alto barra con intervallo di date, scelte rapide (1 g, 7 g, 30 g, 1 anno, Tutto),
risoluzione (automatica, giornaliera, oraria, 10 minuti per la pioggia, dato originale) e modalità del grafico (pannelli o assi multipli);
statistiche nell'intervallo visibile, esportazione CSV e scheda dei metadati (ⓘ) per ogni serie. Lo stato è nell'URL e si può condividere.
I pixel ERA5-Land e SMAP L4 sono mostrati in mappa con colori propri (legenda sotto la mappa) e nell'elenco come stazioni «pixel».

## Stazioni

| Stazione | Descrizione | Coordinate | Quota |
|---|---|---|---|
| `VAG_CF` | Vaglio di Basilicata – pluviometro (rete CFD) | 40°40'10" N, 15°54'55" E (40.669444, 15.915278) | 991 m s.l.m. |
| `VAG_S3` | Vaglio – Nodo S3 (terreno), datalogger METER z6-18720, Università di Salerno | 40.6673775, 15.9168308 | 939 m s.l.m. |
| `ERA5_E159_N407` | ERA5-Land · 15.9°E 40.7°N – pixel 0,1° (~9 km), prodotto a griglia | 40.7, 15.9 (centro pixel) | n.d. |
| `SMAP_E1594_N4070` | SMAP L4 · 15.94°E 40.70°N – pixel ~9 km, prodotto a griglia | 40.6994, 15.9371 (indicativa) | n.d. |

## Pipeline

```bash
export INPUT_DIR=<cartella con i file sorgente>   OUT_DIR=.
python pipeline/build_vaglio.py       # data/ + catalog.json + series.csv + data/qc_log.csv
python pipeline/ingest_gee.py         # prodotti a griglia da Google Earth Engine (ERA5-Land, SMAP L4)
python pipeline/derive_cumulative.py  # pioggia cumulata dal 1 gennaio dei prodotti a griglia
```

`build_vaglio.py` rigenera `catalog.json`, `series.csv` e `data/qc_log.csv` da zero: dopo ogni sua esecuzione vanno rieseguiti
anche `ingest_gee.py` (con i CSV GEE in `INPUT_DIR`) e `derive_cumulative.py`. I file dei pixel in `data/raw` e `data/agg` non vengono cancellati.

I file sorgente sono:
- CSV `… Intensità Pioggia … .csv` (mm/h, passo 1 minuto, ora locale CET/CEST), uno per mese;
- `Vaglio_Meter_S3_<anno>.xlsx` (colonna `Time UTC+1`, sensori TEROS 10 e TEROS 21);
- `Vaglio_ERA5Land[_<anno>].csv` e `Vaglio_SMAP_L4[_<anno>].csv`, esportati da Google Earth Engine (letti da `ingest_gee.py`).

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
| `ERA5_E159_N407_VWC_007`, `_028` | Contenuto d'acqua del terreno ERA5-Land, strati 0–7 e 7–28 cm | m³/m³ | 1 h |
| `ERA5_E159_N407_RAIN` | Pioggia ERA5-Land (convertita da m a mm) | mm | 1 h |
| `ERA5_E159_N407_RAINCUM` | Pioggia cumulata dal 1° gennaio (derivata da `ERA5_E159_N407_RAIN`) | mm | 1 h |
| `ERA5_E159_N407_TAIR` | Temperatura dell'aria a 2 m ERA5-Land (convertita da K a °C) | °C | 1 h |
| `SMAP_E1594_N4070_VWC_005`, `_100`, `_PRF` | Contenuto d'acqua del terreno SMAP L4, strati 0–5 cm, 0–100 cm e profilo intero | m³/m³ | 3 h |

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
- **`ERA5_E159_N407_RAINCUM`** – stessa definizione per la pioggia ERA5-Land (passo 1 ora, calcolata da `derive_cumulative.py`, aggregati orari e giornalieri).
  Totali: 2023 888,2 mm; 2024 603,6 mm; 2025 658,4 mm; 2026 (al 30 settembre) 508,8 mm; nessun dato mancante, quindi nessun `flag` 1.

## Prodotti a griglia (Google Earth Engine): ERA5-Land e SMAP L4

`ingest_gee.py` legge i CSV esportati da GEE in `INPUT_DIR` (`Vaglio_ERA5Land[_<anno>].csv`, `Vaglio_SMAP_L4[_<anno>].csv`)
e crea una **stazione «griglia»** (`kind: "grid"`) per ogni pixel distinto, con le stesse convenzioni di IoT_CavaSA.
- **ERA5-Land** (0,1°, orario): stazione `ERA5_E<lon×10>_N<lat×10>`, coordinate agganciate al centro pixel. Serie: `VWC_007` (strato 0–7 cm),
  `VWC_028` (7–28 cm), `RAIN` (m → mm), `TAIR` (K → °C, variabile `t_air`).
- **SMAP L4** (~9 km, medie su 3 h, etichetta a metà intervallo): stazione `SMAP_E<lon×100>_N<lat×100>`. Serie: `VWC_005` (0–5 cm),
  `VWC_100` (0–100 cm), `VWC_PRF` (intero profilo fino al substrato).
- Per le serie a strati il codice a 3 cifre è la profondità inferiore dello strato in cm; lo strato esatto è in `layer_label`.
- I valori sono medie di pixel di ~9 km, non misure puntuali: il confronto con i sensori in situ è indicativo.

**Tempo.** GEE fornisce UTC; si aggiunge 1 ora per ottenere UTC+1 (il dato UTC delle 23:00 del 31/12 passa all'anno successivo, perciò i file iniziano il
1 gennaio 2023 alle 01:00 per ERA5-Land e alle 02:30 per SMAP L4 e terminano il 1 ottobre 2026 alle 00:00 e il 30 settembre alle 23:30).
Verifica per Vaglio: il massimo giornaliero della temperatura ERA5-Land cade alle 13:00 dell'ora originale in estate e in inverno
(mezzogiorno solare a Vaglio ≈ 10:56 UTC), quindi il CSV è in UTC.

**Pioggia ERA5-Land.** Riferita all'ora che termina al timestamp (convenzione ECMWF), come la pioggia dei pluviometri. Confronto con il pluviometro CFD a passo 1 minuto:
la correlazione oraria è massima con la finestra del pluviometro che termina al timestamp ERA5 (r ≈ 0,34–0,36 tra −45 e +15 min) e cala con la finestra che parte
dal timestamp (r = 0,29 a +60 min); con un pixel di ~9 km la convenzione non è distinguibile al di sotto di ±1 h. I valori negativi di arrotondamento (565, < 0,0001 mm) sono azzerati.

**Pixel ERA5-Land.** Nel CSV la longitudine del punto di campionamento compare come 15.900896 e 15.901720 (due esportazioni, scarto ~70 m): è lo stesso pixel
0,1° e la serie è unica, senza discontinuità alla giunzione (11 gennaio 2024).

**Controllo di qualità.** Intervalli validi in `qc_rules.json` (`vwc` 0–0,65 m³/m³, `rain` 0–50 mm, `t_air` −30–50 °C): nessun valore fuori range, nessun valore sospetto.
SMAP L4 ha 5 interruzioni rispetto ai 3 h nominali (ottobre–novembre 2025, la più lunga di 18 h), nessuna supera 24 h; ERA5-Land è continuo.

**Confronto con il nodo S3** (medie giornaliere, 8 agosto 2023 – 31 dicembre 2025, circa 870 giorni; scarto = prodotto − sensore; scritto anche nelle note di ogni serie):

| Prodotto e strato | r con S3 a 12 cm | scarto (m³/m³) | r con la media 12/40/60 cm | scarto (m³/m³) |
|---|---|---|---|---|
| ERA5-Land 0–7 cm | 0,82 | −0,036 | 0,82 | −0,028 |
| ERA5-Land 7–28 cm | 0,86 | −0,047 | 0,87 | −0,039 |
| SMAP L4 0–5 cm | 0,81 | −0,152 | 0,81 | −0,144 |
| SMAP L4 0–100 cm | 0,78 | −0,101 | 0,79 | −0,093 |
| SMAP L4 profilo intero | 0,77 | −0,104 | 0,78 | −0,096 |

Entrambi i prodotti seguono la dinamica misurata (r 0,77–0,87) ma sono più secchi dei sensori; lo scarto di SMAP L4 (da −0,09 a −0,15 m³/m³) è molto maggiore di quello di ERA5-Land (da −0,03 a −0,05 m³/m³).
La pioggia giornaliera ERA5-Land confrontata con il pluviometro CFD (1366 giorni comuni) dà r = 0,69 e totali simili (2657 mm contro 2599 mm), ma con scarti annui da −23 % a +19 %
(2023: 888 contro 747 mm; 2026 al 30 settembre: 509 contro 661 mm).

**Incrementale.** Per aggiungere un periodo basta passare il nuovo CSV: i dati già in `data/raw` si uniscono e, a parità di istante, vince il dato nuovo.
`REPLACE_PRODUCTS=ERA5,SMAP` sostituisce invece tutti i dati del prodotto (nuova esportazione con altri punti). Poi rieseguire `derive_cumulative.py`.

## Note

- Dati del nodo S3 disponibili fino al 31 dicembre 2025; i file 2026 non sono ancora inclusi.
- Gli aggregati dei prodotti a griglia sono orari e giornalieri (non a 10 minuti): scegliendo «10 minuti» il portale usa l'aggregato orario.
- Nei file METER alcuni timestamp sono duplicati nella sorgente con valori leggermente diversi: si mantiene il primo, come segnalato in `catalog.json`.

## Fonti dei dati

- Pluviometro di Vaglio di Basilicata: Centro Funzionale Decentrato Basilicata – Regione Basilicata.
- Nodo S3 (terreno): Università di Salerno.
- ERA5-Land: ECMWF – Copernicus Climate Change Service (collezione GEE `ECMWF/ERA5_LAND/HOURLY`); SMAP L4: NASA GMAO (collezione GEE `NASA/SMAP/SPL4SMGP`); entrambi scaricati da Google Earth Engine.

## Visualizzare il portale in locale

`python -m http.server` nella radice del repo e aprire http://localhost:8000.
