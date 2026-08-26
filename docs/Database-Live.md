# Die Live-Datenbank

`db/live.py`. Jedes Paket, das je ankam, eine Weile aufbewahrt. Das ist der
Speicher, der WeeWX' In-Memory-Akkumulator ersetzt.

Ein Paket wird hier geschrieben, sobald es ankommt, und sonst passiert nichts
damit. Archivsätze werden **danach** aus dieser Tabelle gerechnet — genau das
macht sie reproduzierbar: dieselben Pakete ergeben immer denselben Satz, ob
jetzt aggregiert, nach einem Neustart oder eine Woche später.

Eigene Datei, damit Größe und Retention nichts mit dem Archiv zu tun haben. Die
Archivdatenbank bleibt klein und sicherbar.

## Größe

Gemessen an einer Konsole mit einem Paket alle 8 s: rund **11 MB pro Tag**, also
etwa 80 MB bei sieben Tagen Retention. Eine Vantage mit einem LOOP-Paket alle
2 s ist das Vierfache.

## Das Schema

```sql
CREATE TABLE IF NOT EXISTS packet (
    seq       INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    dateTime  INTEGER NOT NULL,
    …
);
```

| Spalte | Bedeutung |
|---|---|
| `seq` | Fortlaufend, der Primärschlüssel |
| `dateTime` | Der Messzeitpunkt, wie das Paket ihn nennt |
| `usUnits` | Einheitensystem, `1` / `16` / `17` → [Units](Units) |
| `data` | Die Messwerte als JSON |
| `source` | Von welcher Station → [Multiple-Sources](Multiple-Sources) |
| `kind` | `loop` oder `archive` |
| `interval` | Wenn das Paket eine Spanne trägt |
| `received` | Ankunftszeit, unabhängig vom Messzeitpunkt |
| `raw` | Der Upload, wie er vom Draht kam — nur eine Weile |

Dazu eine `meta`-Tabelle und eine `pending`-Liste.

## `Packet`

Ein Messwert, wie er ankam, bevor irgendetwas damit gemacht wurde.

```python
Packet(dateTime=1787734265, usUnits=1, data={"outTemp": 21.4},
       source="garten", kind="loop", interval=None,
       received=1787734266, raw=None)
```

| Methode | Bedeutung |
|---|---|
| `digest()` | Ein kurzer Hash der Nutzlast, damit eine erneute Übertragung kein neues Paket ist |
| `record()` | Das Paket als Beobachtungssatz, fertig für den Akkumulator |

## `LiveStore`

```python
store = LiveStore("data/live.sdb", interval_seconds=300, keep_raw_seconds=3600)
```

### Schreiben

| Methode | Bedeutung |
|---|---|
| `add(packet)` | Ein Paket. Gibt `False` zurück, wenn es schon da war |
| `add_all(packets)` | Viele in einer Transaktion. Gibt zurück, wie viele neu waren |

**Idempotent auf `(source, kind, dateTime, payload)`.** Eine Konsole, die einen
Upload wiederholt, wird nicht doppelt gezählt. Das ist keine Kür: Ecowitt-Geräte
wiederholen, wenn die Antwort ausbleibt, und ein doppelt gezähltes Paket
verschiebt jeden gewichteten Mittelwert des Intervalls.

### Lesen

| Methode | Bedeutung |
|---|---|
| `packets(start, stop, kind=None, with_raw=False)` | Jedes Paket in `(start, stop]`, in Zeitreihenfolge |
| `raw_of(seq)` | Ein Paket samt Rohupload, wenn noch vorhanden |
| `span()` | Erster und letzter Zeitstempel |
| `count()` | |

`with_raw` ist **standardmäßig aus**: der Archiver läuft über tausende Pakete
und hat keine Verwendung dafür, und die Spalte ist die große.

### Intervalle

| Methode | Bedeutung |
|---|---|
| `mark_pending(ts, seconds=None)` | Merken, dass das Intervall um `ts` gerechnet werden muss |
| `clear_pending(stop)` | |
| `due(now=None, grace=15)` | Intervalle, die geschlossen haben, ältestes zuerst |

`interval_stop(ts, seconds)` (Modulfunktion) sagt, zu welchem Intervall ein
Zeitstempel gehört. Intervalle sind **am Anfang halboffen**: ein Paket genau auf
einer Grenze schließt das Intervall, das dort endet, statt das nächste zu
öffnen. Dieselbe Konvention wie im [Accumulator](Aggregation).

`grace` hält ein Intervall nach seinem Ende ein paar Sekunden zurück, damit ein
bloß langsames Paket nicht dazu führt, dass ein Satz zweimal gerechnet wird.

### Aufräumen

| Methode | Bedeutung |
|---|---|
| `forget_raw(before)` | Die Rohuploads verwerfen, die Pakete bleiben |
| `prune(before, archive_dir=None)` | Pakete älter als `before` wegwerfen, optional vorher wegschreiben |

`forget_raw` geht nach **Ankunftszeit**, nicht nach Messzeit: ein spät
angekommenes Paket soll seinen Rohupload noch eine Weile behalten dürfen.

`prune` mit `archive_dir` schreibt jeden Tag, der die Tabelle verlässt, vorher
als gzip-NDJSON weg (`_spool`). Nichts wird gelöscht, bevor die Datei
geschrieben ist.

```bash
weewx-evo archive --spool /data/packets
```

### Verbindungen

`conn()` öffnet **je Thread** eine eigene Verbindung beim ersten Zugriff.
SQLite-Verbindungen sind thread-gebunden — das war ein echter Fehler, der im
Browser nie aufgefallen wäre, und ist jetzt Teil des Designs.
→ [Testing](Testing)

### Migration

`_migrate()` bringt eine ältere Datei auf den Stand, **nur additiv**. Diese
Datei ist ein Cache mit ein paar Tagen darin, eine schiefgegangene Migration
kostete also wenig — aber die Pakete sind das, woraus ein Satz reproduzierbar
ist, also wird trotzdem nichts weggenommen.

## Warum das die Live-Tabelle rechtfertigt

Der messbare Fall steht im [Testing](Testing)-Kapitel: In einer echten Datenbank
stand ein `outTemp`-Minimum von 17,6 °F und ein Maximum von 96,8 °F, acht
Minuten auseinander, spätabends im August. Beides Müll aus einer Umbauphase —
und beides steht dauerhaft in der Statistik, weil die LOOP-Pakete fort sind.
`weectl database rebuild-daily` würde es entfernen und dabei jedes **echte**
LOOP-Extrem des gesamten Zeitraums mitnehmen.

Solange die Pakete hier liegen, ist beides trennbar.

<!-- covers
src/weewx_evo/db/live.py
-->
