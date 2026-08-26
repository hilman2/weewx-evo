# Zeitreihen

`series.py`. Das Äquivalent zu `weewx.xtypes.get_series()` und die Grundlage
jedes Feeds.

Jeder Feed will dasselbe: einen Messwert, über eine Spanne, in irgendeiner
Auflösung. Die heutige Temperatur alle fünf Minuten. Den Regen dieses Monats je
Tag. Ein Jahrzehnt Jahresmaxima. Ohne das kann ein Feed nur den letzten Wert
melden.

## `Series`

```python
@dataclass
class Series:
    obs_type: str
    time: list[float]
    values: list[Any]
    start: list[float]
    stop: list[float]
    aggregate: str | None
    interval: int | str | None
    directions: list[Any] | None
```

**Zwei parallele Arrays statt einer Liste von Paaren**: rund 30 % kleiner,
sobald es JSON ist, und die Form, die jede Diagrammbibliothek will.

`start` und `stop` begrenzen jeden Punkt. Ein Aggregat gehört zu einer Spanne,
nicht zu einem Moment — ein Tagesbalken, der auf seinen Zeitstempel gezeichnet
wird, sitzt an der falschen Stelle des Diagramms.

| Methode | Bedeutung |
|---|---|
| `empty()` | Ob es etwas zu zeichnen gibt. Eine Reihe aus lauter Nulls hat es nicht |
| `rounded(places=3)` | Werte an Ort und Stelle runden. **Zeitstempel nie** |

## `Reader`

```python
reader = Reader(connection, table="archive")
s = reader.series("outTemp", start, stop, aggregate="max", interval="day")
```

Hält eine Verbindung und sonst nichts — **keinen Cache**, also auch nichts, was
veralten könnte, während der Archiver in dieselbe Datei schreibt.

| Methode | Bedeutung |
|---|---|
| `columns()` | Die Messwerte, für die die Archivtabelle eine Spalte hat |
| `has_daily(obs_type)` | Ob es eine Tagesstatistik-Tabelle dafür gibt |
| `span()` | Erster und letzter Satz |
| `series(obs_type, start, stop, aggregate=None, interval=None)` | Die Hauptsache |
| `aggregate(obs_type, start, stop, how)` | **Eine** Zahl für eine Spanne |
| `vector(obs_type, start, stop, how)` | Ein Windvektor als `(Betrag, Richtung)` |
| `buckets(start, stop, interval)` | In welche Eimer eine Spanne zerfällt |

Ohne `aggregate` kommen die Archivsätze selbst. Mit einem wird die Spanne in
Eimer geschnitten und jeder auf eine Zahl reduziert.

## Die zwei Wege zu einem Aggregat

Die Wahl zwischen ihnen ist der größte Teil dieser Datei.

### 1. Aus den Tagesstatistiken

`archive_day_outTemp` hält Minimum, Maximum, Summe und gewichtete Summe für
jeden Tag. **Ein Monat Tagesmaxima sind 30 Zeilen über den Primärschlüssel**
statt ein Monat Archivsätze.

Und es sind die *besseren* Extreme: aus den Live-Paketen aufgenommen, also ist
eine Bö zwischen zwei Archivsätzen darin.

Voraussetzung: die Spanne fällt auf ganze lokale Tage. `is_midnight(ts)` ist
genau diese Frage — die Tagesstatistiken sind danach indiziert, also ist es die
Frage, ob sie überhaupt antworten können.

### 2. Aus der Archivtabelle

Alles, was nicht auf Tage fällt.

### `_NOT_THERE`

`_from_daily()` gibt entweder einen Wert, `None` oder das Sentinel `_NOT_THERE`
zurück. Der Unterschied ist wichtig:

| | |
|---|---|
| `_NOT_THERE` | Die Statistiken **können** nicht antworten → die Sätze fragen |
| `None` | Die Antwort **ist** nichts |

## Tage sind Tage

Ein Tagesaggregat bekommt Eimer auf **lokaler Mitternacht**, nicht Eimer von
86400 Sekunden ab dem Beginn der Anfrage. Monate und Jahre genauso.

Ein Tag ist nicht immer 86400 Sekunden. Deshalb wird in Ortszeit gelaufen und
nicht addiert:

| | |
|---|---|
| `FIXED = {"hour": 3600, "week": 604800}` | Feste Längen |
| `CALENDAR = ("day", "month", "year")` | Kalendereinheiten |
| `_floor(ts, unit)` | Beginn des Tages, Monats oder Jahres |
| `_step(ts, unit, count=1)` | Um ganze Einheiten vorwärts, in Ortszeit |
| `_fixed(start, stop, interval)` | Feste Eimer, **in Ortszeit gestuft** |

`_fixed` stuft ebenfalls in Ortszeit statt Sekunden zu addieren. Das hält die
Grenzen über einen Sommerzeitwechsel hinweg auf derselben Uhrzeit — was WeeWX
tut und was ein Diagramm braucht, das an Stundenmarken ausgerichtet ist.

`buckets()` nimmt nur Kalendereinheiten, die **innerhalb** der Spanne beginnen:
eine Anfrage, die um neun Uhr morgens anfängt, bekommt keinen Tageseimer, der
Mitternacht anfängt und nur zu einem Viertel abgedeckt ist.

## Die Aggregate

```python
AGGREGATES = ("avg", "min", "max", "sum", "count", "first", "last",
              "firsttime", "lasttime", "mintime", "maxtime", "rms",
              "vecavg", "vecdir", …)
```

Dazu die Änderungsaggregate über `_change()`: wie viel ein Messwert über eine
Spanne wanderte und wie schnell.

**Der Ausgangspunkt ist der Satz *bei oder vor* dem Beginn der Spanne**, nicht
der erste darin. Ein Zähler, der bei 4 kWh stand, als die Woche begann, hat in
dieser Woche nicht 4 kWh geliefert.

## Wind

```python
VECTORS = {"windvec": ("windSpeed", "windDir"),
           "windgustvec": ("windGust", "windGustDir")}
WIND = {"max": "windGust", "maxtime": "windGust"}
```

Der Vektorpfad ist vom skalaren getrennt, weil das Mitteln eine **andere
Operation** ist. Das Mittel aus einer Stunde Nordwind und einer Stunde Südwind
ist nicht ein frischer Wind, sondern Windstille — und genau das kommt heraus,
wenn man die Komponenten addiert statt der Beträge.

| | |
|---|---|
| `_vector(magnitude, bearing)` | Eine Windmessung als Vektor, oder nichts |
| `_bearing(x, y)` | Die Richtung einer Vektorsumme, in Kompassgrad |

Eine Geschwindigkeit ohne Richtung **ist kein Vektor**: es gibt keinen Pfeil zu
zeichnen und keine Möglichkeit, ihn zu einem anderen zu addieren. WeeWX wirft
solche weg, und das hier auch. Eine Geschwindigkeit von null ist die Ausnahme.

`vector(obs_type, start, stop, how)`: `avg` und `sum` addieren die Messungen als
Vektoren. Jedes andere Aggregat wählt **eine** Messung — die stärkste, die
erste — und meldet deren Richtung.

## Eine bewusste Abweichung

**Ein Mittelwert ist hier immer mit `interval` gewichtet.**

WeeWX gewichtet in den Tagesstatistiken so, benutzt aber ein schlichtes `AVG()`
auf der Archivtabelle. In einer Datenbank, deren Archivintervall sich geändert
hat, widerspricht WeeWX also **sich selbst** — je nachdem, welchen der beiden
Wege eine Anfrage nimmt.

Gemessen: `tools/seriestest.py`, 94 Vergleiche, 19 957 Punkte, 0 Fehler,
8 bekannte Abweichungen (genau diese).

## Prüfen

```bash
python tools/seriestest.py reference/weewx.sdb
```

Fragt WeeWX und weewx-evo nach derselben Reihe und vergleicht. `weewx.xtypes.
get_series` ist, worauf jeder WeeWX-Bericht steht, und `weewx_evo.series` ist,
worauf jeder Feed hier steht. Weichen die zwei ab, zeigt ein von weewx-evo
gezeichnetes Diagramm eine andere Woche Wetter als dasselbe Diagramm von WeeWX —
und das ist die eine Sache, die dieses Projekt nicht darf.

Der Test braucht ein installiertes WeeWX und eine echte Datenbank.
→ [Testing](Testing)

<!-- covers
src/weewx_evo/series.py
tools/seriestest.py
-->
