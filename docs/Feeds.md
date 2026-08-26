# Feeds

`feeds/`, `feedrunner.py`.

Ein Treiber bringt Messwerte herein. Ein **Feed** macht etwas daraus — eine CSV,
ein JSON-Dokument, ein Diagramm, eine ganze Webseite, einen Monatsbericht. Ein
**[Export](Exports)** nimmt, was ein Feed erzeugt hat, und bringt es woandershin.

```
feed   → ein Verzeichnis voller Dateien
export → dieses Verzeichnis, irgendwohin geschickt
```

**Das Verzeichnis ist die ganze Schnittstelle.** Genauso wie die Live-Tabelle
zwischen Listener und Archiver. Ein Feed, drei Exports. Oder drei Feeds in ein
Verzeichnis und ein Export. Keiner weiß vom anderen.

Bei WeeWX rendert eine „Skin" Dateien *und* der FTP-Upload wird im selben
Abschnitt konfiguriert. Eine Seite für zwei Ziele heißt dort: den Renderer
zweimal laufen lassen.

## Ein Ordner je Feed

Wie Treiber unter `ingest/plugins/`:

```
feeds/
  jsongenerator/     die Zeitreihen, auf denen alles andere steht
  diagnostic/        zeichnet, was tatsächlich auf der Platte liegt
    vendor/          eigenes uPlot, MIT, 51 KB
```

Ein Feed, der Templates, Stylesheets oder ein JS-Bundle bekommt, hält die neben
seinem Code statt in einem gemeinsamen Haufen; ein gelöschter Feed nimmt seine
Assets mit.

## Die Schnittstelle

```python
class Feed(Protocol):
    trigger: str    # "record" | "packet" | "schedule"

    def produce(self, archive, into: Path) -> Produced:
        ...

    @staticmethod
    def options():   # die Admin-Seite baut daraus ein Formular
        ...
```

```python
@dataclass
class Produced:
    directory: Path
    files: list[Path]
    note: str
```

**Die Dateiliste zählt für die Exports.** Ein Export, der weiß, welche Dateien
sich geändert haben, schickt die; einer, der es nicht weiß, schickt jedes Mal
alles. Über eine Mobilfunkverbindung ist das der Unterschied.

`archive` ist eine **nur lesende** Sicht: ein Feed berichtet Geschichte, er
schreibt sie nicht. Was er wirft, wird geloggt und hält nichts auf.

## Die Registry

| | |
|---|---|
| `TRIGGERS` | `("record", "packet", "schedule")` |
| `ENTRY_POINT_GROUP` | `"weewx_evo.feeds"` |
| `BUNDLED` | Was mitgeliefert wird, als `(name, modul, klasse, beschreibung)` |
| `DESCRIPTIONS` | Was jeder in ein paar Worten ist |
| `load()` | Die Feeds hereinholen |
| `names()` | Die Feeds, die es gibt |
| `get(name)` | |
| `describe(name)` | Eine Zeile über einen Feed, für ein Formular, das ihn anbietet |
| `register(name, feed, description="")` | |

`names()` ist eine **Funktion**, damit die Auswahlliste eines Exports sich von
selbst füllt, sobald ein Feed erscheint. Der Export muss es nicht erfahren, und
niemand muss etwas neu starten.

`BUNDLED` ist **hier benannt**, statt durch Ablaufen des Verzeichnisses gefunden
zu werden: ein halbfertiger Feed im Ordner soll nicht in einem Formular
auftauchen. Das ist der Unterschied zu den Treibern, wo jedes Unterverzeichnis
probiert wird.

`load()` meldet einen kaputten Feed, wird aber **nie fatal** — dieselbe
Anordnung wie bei den Treibern. Eine Station, deren Diagnoseseite kaputt ist,
soll ihre Zeitreihen weiter schreiben.

`DESCRIPTIONS` existiert für die Auswahlliste: sie wäre sonst eine Liste von
Namen, und `"json"` sagt nicht, was drin ist.

## Der Feed-Runner

`feedrunner.py`. Fährt die Feeds der Reihe nach auf einem **eigenen Thread**.

Hundert Diagramme sind eine knappe Sekunde Lesen und Schreiben. Dort erledigt,
wo der Archiver läuft, ist das eine Sekunde, in der er nicht archiviert — jedes
Intervall, für immer.

Also dieselbe Anordnung wie bei den Exports: **der Archiver setzt ein Flag und
kehrt zurück**, und die Arbeit passiert hier.

**Ein Thread für alle Feeds, nicht einer je Feed.** Sie sind geordnet: die
Diagnoseseite zeichnet, was der JSON-Feed geschrieben hat.

```python
runner = Runner(feeds, archive_path)
runner.start()
runner.record_written()    # vom Archiver, kehrt sofort zurück
```

| Methode | Bedeutung |
|---|---|
| `record_written()` | Setzt ein Flag und kehrt zurück |
| `run_once()` | Jeden Feed, in Reihenfolge. Gibt zurück, was passierte |
| `status()` | Für eine Statusseite |
| `start()`, `stop()` | |

`SETTLE = 2.0` — zwei Sekunden nach dem Flag, damit mehrere Sätze in schneller
Folge einen Lauf ergeben und nicht drei.

Nach dem Lauf ruft er `exports.runner.Runner.feed_produced(name, files)`. Das
ist der Auslöser `feed`. → [Exports](Exports)

Die Reihenfolge kommt aus `cli.build_feeds()`: JSON zuerst, weil die
Diagnoseseite zeichnet, was er geschrieben hat. **Das ist die einzige
Abhängigkeit zwischen zwei Feeds überhaupt**, und sie steht dort statt in einem
der beiden.

## Der JSON-Feed

`feeds/jsongenerator/`. Der Feed, der mitgeliefert wird und nicht entfernbar
ist, weil alles andere darauf steht.

Ein Diagramm im Browser, eine aus einem Template gerenderte Seite, ein Export
auf einen statischen Host, ein Bildgenerator, wenn je einer geschrieben wird —
alle wollen dasselbe: einen Messwert über eine Spanne in einer Auflösung, mit
seiner Einheit und seiner Beschriftung.

> Diese Neuerfindung ist nicht hypothetisch. Jede JavaScript-Skin für WeeWX —
> Belchertown, wdc, jas und der Rest — trägt ihre eigene Kopie derselben Idee,
> ihr eigenes Diagramm-Konfigurationsformat und ihre eigenen Fehler darin. Keine
> teilt etwas. Das hier existiert, damit eine Skin eine Skin sein kann.

### Was es schreibt

```
<ziel>/daytempdew.json
<ziel>/weekrain.json
<ziel>/index.json          das Manifest
```

Das Manifest sagt, was es gibt, damit ein Client seine Seite anlegen kann, bevor
er etwas holt — und nie nach einem Sensor fragt, den diese Station nicht hat.

### Die Form

```json
{
  "name": "daytempdew",
  "format": 1,
  "generated": 1755950000,
  "start": 1755863600, "stop": 1755950000,
  "asked": [1755863600, 1755950000],
  "unit": "degree_C", "unit_label": "°C",
  "yscale": [10, 25, 5],
  "daynight": {"first": "night", "transitions": [], "twilight": []},
  "series": [
    {"obs_type": "outTemp", "label": "Außentemperatur",
     "plot_type": "line", "color": "#4282b4",
     "time": [], "values": []}
  ]
}
```

`format` steht in jeder Datei, damit ein Client weiß, ob er sie versteht.
Erhöht **nur**, wenn sich die Form so ändert, dass ein Leser bricht — nicht,
wenn ein Schlüssel dazukommt.

`start`/`stop` sind, was die Daten **abdecken**, `asked` ist, was angefragt
wurde. Der Unterschied: ein Eimer wird gezeichnet als das, was er abdeckt, und
der letzte eines Tagesdiagramms deckt den ganzen heutigen Tag ab — er endet also
an morgigem Mitternacht, nach dem Moment, in dem die Datei geschrieben wurde.
Ohne das fällt der letzte Balken vom Rand des Diagramms.

### Ein Diagramm, eine Einheit

Die erste Linie, die eine hat, entscheidet. WeeWX weigert sich rundheraus, zwei
Einheiten zusammen zu zeichnen. Hier wird die erste gemeldet und der Rest bleibt
**an den Linien**, damit ein Client die Uneinigkeit wenigstens sehen kann,
statt gesagt zu bekommen, das Diagramm sei unmöglich.

### Was weggelassen wird

| | |
|---|---|
| Ein Plot, in dem jede Linie leer zurückkam | Wird gar nicht geschrieben. Der ausgelieferte Satz deckt Sensoren ab, die die meisten Stationen nicht haben, und hundert Dateien voller Nulls helfen niemandem |
| Punkte, die nichts tragen | `_drop_empty()`. Ein Sensor, der alle zehn Minuten meldet, füllt einen Archivsatz von zehn, der Rest hält `null` für ihn. So gesendet zeichnet ein Client eine Linie, die zur Hälfte kaputt aussieht |
| Echte Lücken | Bleiben sichtbar. `GAP_FACTOR = 3.0`: dreimal der übliche Abstand ist eine Lücke, nicht der Rhythmus. **Aus den Messwerten selbst beurteilt**, weil zehn Minuten für eine Station, die alle acht Sekunden meldet, ein Ausfall sind und für eine, die alle zehn Minuten meldet, der Normalfall |

`gap_fraction` aus der Plot-Definition — WeeWX' eigenes festes Maß — schlägt das
weiterhin, aber **nur auf einer unaggregierten Reihe**. Auf einer aggregierten
*ist* der Eimer der Abstand, und ein Bruchteil der Diagrammbreite sagt dort
nichts.
| Sensoren, die es nie gab | `_exists()`. Der Unterschied zwischen einem Messwert, der heute fehlt, und einem, den es nie gab. WeeWX' `skip_if_empty = year` sagt genau das |

### `_same()` — nicht neu schreiben, was gleich ist

Ein Jahr Tagesmittel sagt um zehn nach dasselbe wie um zehn. Verglichen wird
**alles außer dem Zeitstempel**. Das zählt, wenn ein Export alles Geänderte
schickt.

Abschaltbar über `feeds.json.rewrite_unchanged`.

### `_write()` — daneben und hineinbewegt

Ein Client, der abfragt, während geschrieben wird, soll die alte Datei bekommen,
nicht die halbe neue.

### Vektoren

`_components(magnitudes, directions, places)` zerlegt eine Vektorreihe in „wie
weit östlich" und „wie weit nördlich". Ein Diagramm, das Pfeile zeichnet,
skaliert und verschiebt die Komponenten; sie mitzugeben spart, sie am anderen
Ende aus Betrag und Richtung wieder aufzubauen — und spart, es falsch zu machen.

### Einstellungen

→ [Settings-Reference](Settings-Reference#feed-json)

```bash
weewx-evo plots run --into data/public_html
```

## Der Diagnose-Feed

`feeds/diagnostic/`. **Bewusst dumm.**

Er liest die Plot-Definitionen nicht, weiß nicht, wie ein Diagramm aussehen
soll, und hat nichts zu konfigurieren. Er läuft ein Verzeichnis ab, nimmt jede
JSON-Datei, die eine Reihe enthält, zeichnet sie, und listet alles, was falsch
aussieht.

**Das ist der ganze Punkt.** Jeder andere Feed rendert, was er *meinte*. Dieser
rendert, was **tatsächlich auf der Platte liegt** — und beantwortet damit die
Frage, die sonst einen Nachmittag kostet: *liegt es an den Daten oder am
Template?*

| Methode | Bedeutung |
|---|---|
| `read()` | Jede JSON-Datei im Quellverzeichnis, untersucht |
| `_examine(entry, payload)` | Herausziehen, was zeichenbar ist, und notieren, was nicht |
| `render(found, now)` | Die Seite |
| `_thinned(charts)` | Dieselben Diagramme, heruntergesampelt auf etwas, das ein Browser zeichnen kann |

`draw_limit = 400` Punkte je Reihe. **Die Daten in der Seite bleiben ganz** —
nur das Gezeichnete wird ausgedünnt. Hunderttausend Punkte sind so oder so ein
schwarzes Rechteck.

`BIG = 2_000_000` — ab dieser Dateigröße wird gewarnt.

Das uPlot in `vendor/` (MIT, 51 KB) liegt beim Feed, nicht in einem gemeinsamen
Haufen: eine Diagnoseseite, die ein CDN braucht, funktioniert genau dann nicht,
wenn man sie braucht.

### Einstellungen

| Name | Default | |
|---|---|---|
| `feeds.diagnostic.enabled` | `true` | Eine einzelne, in sich geschlossene HTML-Datei |
| `feeds.diagnostic.source` | `json` | Welches Verzeichnis gezeichnet wird |
| `feeds.diagnostic.points` | `400` (50–20000) | Punkte je Reihe im Diagramm |

## Einen Feed schreiben

```python
from pathlib import Path
from weewx_evo.feeds import Produced


class CsvFeed:
    trigger = "record"

    def produce(self, archive, into: Path) -> Produced:
        target = into / "latest.csv"
        target.write_text(…)
        return Produced(directory=into, files=[target], note="1 file")

    @staticmethod
    def options():
        return [...]
```

Registrieren über `feeds.register(name, feed, description)` oder als Entry Point
unter `weewx_evo.feeds`. Ein Feed, den wir pflegen, kommt zusätzlich in
`BUNDLED`.

<!-- covers
src/weewx_evo/feeds/__init__.py
src/weewx_evo/feeds/jsongenerator/__init__.py
src/weewx_evo/feeds/diagnostic/__init__.py
src/weewx_evo/feeds/diagnostic/vendor/LICENSE
src/weewx_evo/feedrunner.py
-->
