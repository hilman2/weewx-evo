# Diagramme

`plots.py`, `adminplots.py`, `plots.toml`.

## Plot-Definitionen gehören weewx-evo, nicht einem Renderer

Bei WeeWX stehen sie in `[ImageGenerator]` in einer **Skin**. Diagramme sind
dort eine Eigenschaft des Zeichners. Zwei Zeichner bedeuten zwei Kopien
derselben Liste — und der JSON-Generator existiert nur, weil er die
Konfiguration des Bild-Generators hinter dessen Rücken mitliest.

Hier kommt die Definition zuerst, die Renderer sind Abnehmer.

| Datei | Was |
|---|---|
| `plots.py` | Das Modell (`Plot`, `Line`, `PlotSet`), Lesen und Schreiben von `plots.toml`, und der Importer |
| `plots.toml` | Eigene Datei neben der Konfiguration |
| `adminplots.py` | Die Seiten dafür — der einzige handgeschriebene Teil der Admin-Oberfläche |

**Warum eine eigene Datei:** Einstellungen sind ein paar Dutzend benannte Werte;
das hier ist eine Liste vieler gleichartiger Sätze mit Listen darin. Und ein aus
einer alten Skin importierter Satz ist etwas, das man diffen und weitergeben
können will.

## Das Modell

### `Line` — ein Messwert in einem Diagramm

| Feld | Bedeutung |
|---|---|
| `obs` | Der Messwert |
| `label` | Wie er in der Legende heißt |
| `kind` | `line` · `bar` · `vector` |
| `color`, `fill_color` | |
| `width` | |
| `aggregate` | `avg` `min` `max` `sum` … oder leer für die Sätze selbst |
| `interval` | Eimergröße: Sekunden oder `hour` `day` `week` `month` `year` |
| `marker`, `marker_size` | |
| `gap_fraction` | Ab welchem Abstand eine Lücke eine Lücke ist |
| `rotate` | |
| `binding` | |

`resolved(position)` gibt dieselbe Linie mit den Farben zurück, die WeeWX ihr
gegeben hätte — `LINE_COLORS` und `FILL_COLORS`, in derselben Reihenfolge.

### `Plot` — ein Diagramm

| Feld | Bedeutung |
|---|---|
| `name` | Auch der Dateiname |
| `span` | Die **Gruppe**: `day` `week` `month` `year`. Für das Manifest und die Admin-Seite |
| `time_length` | Was tatsächlich entscheidet, wie weit zurück es reicht |
| `lines` | |
| `title` | |
| `show_daynight` | Nacht schattieren → [Sun](Sun) |
| `yscale` | `[ymin, ymax, ystep]` |
| `skip_if_empty` | Eine **Zeitspanne**, kein Boolean. Siehe [unten](#zwei-fallen-im-importer) |

`drawn()` gibt die Linien mit aufgefüllten Farben. `uses()` sagt, welche
Messwerte dieses Diagramm braucht.

### `PlotSet` — die Diagramme, die es gibt

Plus `labels`: wie die Messwerte darin heißen.

| Methode | Bedeutung |
|---|---|
| `get`, `add`, `remove` | |
| `by_span()` | Gruppiert, in der Reihenfolge, in der die Gruppen zuerst auftraten |
| `spans()` | Wie lang jede Gruppe abdeckt, fürs Manifest. Genommen vom längsten Diagramm der Gruppe, weil das die Gruppe ist |
| `uses()` | Alle benötigten Messwerte |

## `plots.toml`

```toml
# The charts weewx-evo produces.
#
# Each [[plot]] is one chart; each [[plot.line]] is one reading in it.
# 'span' groups plots for the manifest and for the admin page;
# 'time_length' is what actually decides how far back it reaches.

[labels]
extraTemp3 = "Gewächshaus"

[[plot]]
name = "daytempdew"
span = "day"
time_length = "27h"
show_daynight = true
ymin = 10
ymax = 25

  [[plot.line]]
  obs = "outTemp"
  label = "Außentemperatur"

  [[plot.line]]
  obs = "dewpoint"

[[plot]]
name = "monthrain"
span = "month"
time_length = "30d"

  [[plot.line]]
  obs = "rain"
  kind = "bar"
  aggregate = "sum"
  interval = "day"
```

| Funktion | Bedeutung |
|---|---|
| `load(path)` | Lesen. Eine Datei, die nicht da ist, heißt keine Diagramme, kein Fehler |
| `from_dict(raw)` | Aus schon geparstem TOML |
| `save(path, plots, note)` | Schreiben, mit `.bak` der Vorversion |
| `render(plots, note)` | Als TOML-Text, den jemand editieren kann |

`save()` schreibt **daneben und bewegt hinein**, wie die Konfiguration: diese
Datei entscheidet, was eine Seite zeigt, und ein abgebrochener Schreibvorgang
darf keine halbe hinterlassen.

`labels` steht in derselben Datei, weil ein Name, den jemand vor acht Jahren
vergeben hat („Gewächshaus" für `extraTemp3`), zusammen mit den Diagrammen
umziehen soll.

## Der Importer

**Kein Beiwerk.** Wenn die Definitionen eigenständig werden, ist er der ganze
Rest der Brücke zu 15 Jahren gepflegter Konfigurationen.

```bash
weewx-evo plots import /etc/weewx/skins/Seasons/skin.conf
weewx-evo plots import /etc/weewx/skins/Seasons/skin.conf --write
weewx-evo plots import … --write --replace
```

Liest, berichtet, schreibt erst auf `--write`. Nennt, was es liegen ließ, statt
so zu tun, als hätte es das verstanden.

```python
@dataclass
class Imported:
    plots: PlotSet
    drawing: set[str]   # Optionen, die ein *Bild* beschreiben
    unknown: set[str]   # Optionen, die hier niemand versteht
    empty: list[str]    # Abschnitte, die nach Plots aussahen und nichts hielten
```

`_is_drawing(key)` entscheidet, was ein *Bild* beschreibt und hier keinen Sinn
hat. Drei Wege:

- `IMAGE_ONLY` — die namentliche Liste: `image_width`, `image_height`,
  `anti_alias`, `chart_background_color`, `chart_gridline_color` …
- `DRAWING_PREFIXES` — `image_`, `chart_`, `rose_`, `daynight_`,
  `axis_label_`, `top_label_`, `bottom_label_`, `unit_label_`, `x_label_`,
  `y_label_`
- alles mit `_font` darin oder auf `_color` endend

**Eine Ausnahme:** `rose_label`. Wie die Windrose beschriftet ist, ist *Text*,
und ein Diagramm im Browser braucht ihn genauso wie ein PNG.

Was so aussortiert wird, wird **benannt**, nicht still verworfen.

| Funktion | Bedeutung |
|---|---|
| `from_image_generator(section, labels)` | Plots aus einem `[ImageGenerator]` |
| `labels_from(conf)` | `[Labels] [[Generic]]` — es lohnt sich, das für sich mitzunehmen |
| `_line_from(name, options)` | Ein `[[[[outTemp]]]]`-Unterabschnitt |
| `_color(value)` | Eine WeeWX-Farbe, wie CSS sie versteht |

Die Struktur bei WeeWX ist drei Ebenen tief: eine Gruppe (`[[day_images]]`), ein
Plot (`[[[daytempdew]]]`), eine Linie (`[[[[outTemp]]]]`). Optionen erben nach
unten.

`_line_from` nimmt den Abschnittsnamen als Messwert, außer `data_type` sagt
etwas anderes — so zeichnet WeeWX denselben Messwert zweimal in einem Diagramm
mit zwei Aggregationen.

`_color()` muss drei Schreibweisen können: `#RRGGBB`, `0xBBGGRR` und englische
Namen. Die erste und die letzte sind schon CSS; **die mittlere ist
byte-vertauscht** und muss umgedreht werden — genau die Art Detail, die ein
Diagramm plausibel falsch färbt.

`_holds_plots()` unterscheidet einen Abschnitt, der Plots definiert, von einem,
der bloß Einstellungen hält: eine Gruppe wie `[[day_images]]` hat
Unterabschnitte, die selbst Unterabschnitte haben. Ein Einstellungsblock wie
`[[Archive]]` trägt Skalare.

### Zwei Fallen im Importer

Beide echt gewesen.

#### WeeWX' Suffixe sind nicht unsere

Dort ist `M` eine **Minute** und `m` ein **Monat**. Hier ist `m` wie überall
sonst Minuten.

Eine Datei, die für WeeWX geschrieben wurde, wird nach **WeeWX' Regeln** gelesen
(`_weewx_span`) — und **nichts wird je mit einem mehrdeutigen Suffix
zurückgeschrieben**: `_normalise()` macht aus `1w` das Wort `week`, nie aus
einem Monat `1m`.

```python
_WEEWX_SUFFIX = {"M": 60, "h": 3600, "d": 86400,
                 "w": 604800, "m": NOMINAL["month"], "y": NOMINAL["year"]}
```

Unlesbares gibt den Default zurück statt einer Vermutung — ein falsch geratenes
Intervall ist ein Diagramm, das plausibel und falsch aussieht.

#### `skip_if_empty = year` ist eine Zeitspanne, kein Boolean

Als Boolean gelesen schreibt der Seasons-Satz **100 Dateien statt 71** — 29 davon
nur Nullen für Sensoren, die diese Station nie hatte.

`_span_name()` liest es richtig. `true` wird als „die eigene Spanne des Plots"
gelesen, was die einzige Lesart ist, die etwas bewirkt.

## Die Admin-Seiten

`adminplots.py`. **Der einzige handgeschriebene Teil der Admin-Oberfläche.**

Ein Plot passt nicht in den Formulargenerator, den der Rest der Einstellungen
benutzt, und ihn hineinzuzwingen wäre schlimmer, als das hier zu schreiben: eine
Einstellung ist **ein** benannter Wert, ein Plot ist ein Satz mit einer Liste
von Sätzen darin, und es gibt hundert davon.

| Funktion | Bedeutung |
|---|---|
| `path_for(admin)` | Wo `plots.toml` liegt: neben der Konfiguration |
| `load(admin)`, `store(admin, charts, note)` | |
| `add(admin, name, span, obs)` | Ein neues Diagramm mit einem Messwert. Alles andere auf der nächsten Seite |
| `remove(admin, name)` | |
| `save(admin, name, form, columns)` | Alles über ein Diagramm, aus seinem Formular |
| `bring_over(admin, source, replace, text="", origin=…)` | Import aus einer Skin — aus einer hochgeladenen Datei, aus eingefügtem Text oder aus einem Pfad |
| `nav(admin, active)` | Die Diagramme in der Seitenleiste, so gruppiert wie sie gruppiert sind |
| `edit`, `new`, `importer` | Die drei Seiten |

Die Auswahllisten stehen oben in der Datei: `KINDS`, `USEFUL` (Aggregate),
`INTERVALS`, `LENGTHS`, `EMPTY`. Sie sind in Klartext beschriftet — `"27h", "a
day and the night before it"` — weil eine Auswahl, die Sekunden anzeigt, eine
ist, bei der jemand rechnen muss.

`columns` kommt aus der **Datenbank**, nicht aus einem Schema: eine Station,
deren Treiber eigene Spalten angelegt hat, soll sie zeichnen können.

### Drei Wege in den Importer, und die Reihenfolge zählt

1. **Eine Datei hochladen.** Der einzige, der von überall funktioniert: die
   Skin liegt auf der Maschine, an der jemand sitzt, nicht unbedingt auf der,
   auf der das hier läuft. In einem Container gibt es von hier aus **gar keinen
   Pfad**, der die Skin erreicht.
2. **Den Text einfügen.** Die ganze Datei oder nur der `[ImageGenerator]`-Teil.
3. **Ein Pfad auf dieser Maschine.** Der am wenigsten nützliche der drei, und
   deshalb zuletzt angeboten. Wer einen Pfad hat, hat meist auch eine Shell —
   und dann ist `weewx-evo plots import` das Passendere.

Die hochgeladene Datei wird gelesen und **nicht behalten**.

## Kommandos

```bash
weewx-evo plots list
weewx-evo plots show <name>
weewx-evo plots import <skin.conf> [--write] [--replace]
weewx-evo plots remove <name>
weewx-evo plots run [--into DIR] [--no-page]
```

→ [CLI-Reference](CLI-Reference#plots), [Feeds](Feeds)

<!-- covers
src/weewx_evo/plots.py
src/weewx_evo/adminplots.py
-->
