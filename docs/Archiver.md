# Archiver

`archiver.py` ist der Dienst, der WeeWX' `StdArchive` ersetzt.

Der Unterschied ist nicht, *was* er rechnet, sondern **woher er es nimmt**.
WeeWX akkumuliert im Speicher, während Pakete ankommen, und schreibt das
Ergebnis einmal am Intervallende. Ein Neustart mittendrin verliert das Intervall,
und ein verspätetes Paket hat nirgendwo hin. Hier liegen die Pakete schon in der
Live-Tabelle, also ist ein Archivsatz eine Funktion einer Zeitspanne — und diese
Funktion kann jederzeit, beliebig oft und in beliebiger Reihenfolge ausgeführt
werden, mit demselben Ergebnis.

## `Built`

Ein ausgerechnetes Intervall, bevor es geschrieben wird.

| Feld | Bedeutung |
|---|---|
| `stop` | Ende des Intervalls, der Zeitstempel des Satzes |
| `seconds` | Länge des Intervalls |
| `record` | Der Archivsatz als `dict` |
| `accumulator` | Der Akkumulator dahinter, für das Schärfen der Tageswerte |
| `packets` | Wie viele Pakete hineingeflossen sind |
| `from_hardware` | Ob die Konsole selbst einen Archivsatz geliefert hat |
| `provenance` | Welches Feld von welcher Quelle kam → [Multiple-Sources](Multiple-Sources) |

## Der Weg eines Intervalls

```python
archiver = Archiver(live, archive, interval_seconds=300,
                    policy=DEFAULT_POLICY, loop_hilo=True, sources=policy)
built = archiver.build(stop)
archiver.store(built)
```

### `build(stop, seconds=None)`

1. Pakete aus `(stop - seconds, stop]` holen
2. Über `sources.apply()` je Feld die gewinnende Quelle bestimmen
3. Einen `Accumulator` füttern
4. Einen Satz herausziehen, `derive` anwenden

Gibt `None` zurück, wenn kein Paket in das Intervall fiel. **Eine Lücke in den
Daten ist eine Lücke im Archiv** — einen Satz dafür zu erfinden wäre eine
Behauptung über Wetter, das niemand gemessen hat.

### `store(built, replace=False)`

Die Reihenfolge zählt:

1. Der Satz geht **zuerst** hinein und trägt die Summen.
2. Der Akkumulator wird **danach** eingefaltet und rührt nur Extreme an.

Umgekehrt käme jede Summe doppelt.

### `_sharpen_day(built)`

Das ist WeeWX' `_updateHiLo`. Nur Extreme bewegen sich: die Summen des
Akkumulators haben den Tag schon über den Archivsatz erreicht.

Damit landen die LOOP-Extreme in `archive_day_*` — eine Bö zwischen zwei
Archivsätzen bleibt erhalten. Abschaltbar über `loop_hilo = false`, dann sind
die Tagesextreme exakt aus dem Archiv allein reproduzierbar.

## Betriebsarten

### `process_due(now=None, grace=15, replace=False)`

Baut und speichert jedes Intervall, das geschlossen hat. Gibt zurück, wie viele.

**Jederzeit aufrufbar und jederzeit unterbrechbar**: ein Intervall wird erst aus
`pending` gestrichen, wenn sein Satz in der Datenbank steht.

`grace` hält ein Intervall ein paar Sekunden nach seinem Ende zurück, damit ein
bloß langsames Paket nicht dazu führt, dass der Satz zweimal gerechnet wird.

### `catch_up(since=None, until=None, replace=False)`

Baut jedes Intervall, das die Live-Tabelle abdeckt. Beim Start, nach einer
Ausfallzeit und im Differenztest. Anders als `process_due` ignoriert das die
`pending`-Liste und arbeitet direkt an den Paketen.

```bash
weewx-evo catchup
```

### `rebuild(start, stop)`

Rechnet jedes Intervall in `(start, stop]` neu und ersetzt, was da ist.
Anschließend werden die Tagesstatistiken jedes betroffenen Tages aus der
Archivtabelle neu aufgebaut und danach wieder aus den Paketen geschärft.

```bash
weewx-evo rebuild <von> <bis>
```

Das ist, was eine Korrektur möglich macht: Kalibrierung ändern, neu bauen, und
die Statistik folgt. Voraussetzung ist, dass die Rohpakete noch in der Retention
liegen. → [Database-Live](Database-Live)

### `run(grace=15, poll=5.0, stop_when=None)`

Die Schleife. Eine schlichte Sleep-Schleife, kein Scheduler: die Arbeit ist
idempotent und die Intervallgrenzen kommen aus den Paketen, also ändert ein
Tick, der zu spät kommt oder ausfällt, nichts.

## Was der Archiver sonst noch anstößt

Nach jedem geschriebenen Satz:

- `feedrunner.Runner.record_written()` — setzt ein Flag und kehrt zurück.
  → [Feeds](Feeds)
- `exports.runner.Runner.record_written()` — dito. → [Exports](Exports)

Beides setzt nur Flags. **Nichts an einem Upload oder einem Diagramm passiert
auf dem Thread des Archivers**, weil das eine Sekunde je Intervall wäre, in der
er nicht archiviert.

Außerdem läuft hier die Retention: `LiveStore.prune()` wirft Pakete weg, die
älter sind als die Aufbewahrungszeit, und schreibt sie vorher als gzip-NDJSON
weg, wenn `spool` gesetzt ist.

> Retention gehört zum **Archiver**, nicht zum Listener. Pakete dürfen erst
> fallen, wenn sie in einem Satz stehen, und nur diese Seite weiß das.

## Ein Archivsatz von der Hardware

Manche Konsolen liefern selbst Archivsätze (`kind = "archive"`). Dann wird der
Akkumulator nicht verworfen, sondern über `Accumulator.augment()` gelegt: der
Satz der Konsole behält seine hardwaregerechneten Felder und gewinnt die dazu,
die sie nicht liefert. `from_hardware` merkt sich, dass es so war.

<!-- covers
src/weewx_evo/archiver.py
tools/roundtrip.py
-->
