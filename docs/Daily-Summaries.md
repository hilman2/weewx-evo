# Tagesstatistiken

`db/daily.py`. Die `archive_day_*`-Tabellen.

> **`archive_day_*` ist ein Cache.** Jede Zahl darin ist aus der
> `archive`-Tabelle ableitbar, und dieses Modul ist die Ableitung.

Diese Eigenschaft ist es wert, geschützt zu werden: sie bedeutet, dass ein
Absturz, ein verspätetes Paket oder eine korrigierte Kalibrierung eine
Neuberechnung kosten und sonst nichts.

Eine Einschränkung, und sie ist der Grund für die [Live-Tabelle](Database-Live):
Mit `loop_hilo = true` gehen zusätzlich LOOP-Extreme ein, die **nicht** in der
Archivtabelle stehen. Ein Neuaufbau aus dem Archiv allein ist deshalb korrekt,
aber stumpfer. → [Aggregation](Aggregation#was-der-differenztest-prüft)

## Eine Tabelle je Messgröße

```
archive_day_outTemp      dateTime, min, mintime, max, maxtime,
                         sum, count, wsum, sumtime
archive_day_wind         … dazu xsum, ysum, dirsumtime,
                         squaresum, wsquaresum, max_dir
archive_day__metadata    lastUpdate, Version, Treiberzustand
```

`dateTime` ist der Beginn des lokalen Tages (`start_of_archive_day`) und der
Primärschlüssel. **Tage sind lokale Tage**, nicht Blöcke von 86400 Sekunden.

## Die Gewichtung

Das ist der Teil, der nicht driften darf.

```python
def weight_of(record) -> float:
    """60 * interval — Sekunden, für die dieser Satz steht."""
```

Jeder Satz trägt `60 * interval` Sekunden Gewicht bei. WeeWX benutzt das ab
Tagesstatistik-Version 2.0; Version 1.0 gewichtete jeden Satz gleich, was der
Fehler ist, für dessen Reparatur `patch_sums` existiert.

Genau deshalb mitteln alte und neue Sätze korrekt zusammen, wenn sich das
Archivintervall einer Anlage geändert hat.

`IntervalError` wird geworfen, wenn ein `interval` sich nicht in ein Gewicht
verwandeln lässt. `build(..., on_bad_interval="skip")` lässt solche Sätze aus,
statt die ganze Ableitung scheitern zu lassen.

## Die Funktionen

| | |
|---|---|
| `weight_of(record)` | Das Gewicht eines Satzes |
| `day_accumulator(sod_ts, unit_system, policy)` | Ein Akkumulator über genau einen Archivtag |
| `build(records, policy, on_bad_interval="skip")` | Archivsätze in je einen Akkumulator pro Tag falten |
| `read_day(conn, schema, obs_type, sod_ts)` | Eine gespeicherte Tageszeile lesen |
| `read_records(conn, schema, start, stop)` | Archivsätze in Zeitreihenfolge, ohne die NULL-Spalten |

### `build` ist ein Generator

Sätze müssen in aufsteigender Zeitreihenfolge kommen — dieselbe Reihenfolge, die
der Primärschlüssel der Archivtabelle liefert. Jeder Tag wird ausgegeben, sobald
er vollständig ist, damit ein Jahrzehnt Daten nicht als Ganzes in den Speicher
muss.

### `read_records` lässt NULLs weg

Das ist keine Optimierung, sondern korrekt: Der Akkumulator unterscheidet
„kein Wert" von „Wert `None`". Ein auf alle 134 Spalten aufgefüllter Satz würde
Tagesstatistik-Zeilen für Sensoren erzeugen, die diese Station nie hatte —
Zeilen voller Nullen für Messwerte, die es nie gab.

## Wann welcher Weg

| Situation | Was passiert |
|---|---|
| Ein neuer Archivsatz | `ArchiveStore._apply_daily()` faltet ihn in seinen Tag |
| Danach, mit `loop_hilo` | `Archiver._sharpen_day()` legt die LOOP-Extreme darüber |
| `rebuild <von> <bis>` | `rebuild_day()` je betroffenem Tag, dann erneut geschärft |
| Ein Satz wird ersetzt | `_unapply_daily()`, dann `_apply_daily()` — **nur die Summen** kommen heraus |

Extreme sind nicht umkehrbar. Ein Maximum erinnert sich nicht daran, was der
zweithöchste Wert war. Wer Extreme korrigieren muss, braucht `rebuild_day`.

## Wofür sie im Betrieb gut sind

`series.py` beantwortet ein Aggregat aus den Tagesstatistiken, wann immer die
Spanne auf ganze lokale Tage fällt: ein Monat Tagesmaxima sind 30 Zeilen über
den Primärschlüssel statt ein Monat Archivsätze.

Und es sind die *besseren* Extreme — aus den Live-Paketen aufgenommen, also ist
eine Bö zwischen zwei Archivsätzen darin. → [Series](Series)

<!-- covers
src/weewx_evo/db/daily.py
-->
