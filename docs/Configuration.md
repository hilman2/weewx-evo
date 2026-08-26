# Konfiguration

Das Wichtigste zuerst: **nichts liest die Konfigurationsdatei für sich.** Es
gibt eine `Settings`-Instanz je Prozess, und alles fragt sie.

Der Grund ist konkret: Löst jede Komponente selbst auf, kann eine Datei, die
zwischen zwei Auflösungen neu geschrieben wird, einem laufenden System zwei
verschiedene Konfigurationen geben. `cli.settings_for()` löst deshalb **einmal**
auf und merkt sich das Ergebnis.

## Die Reihenfolge

Fünf Orte, eine feste Rangfolge, stärkster zuerst:

| | Wo | Wofür |
|---|---|---|
| 1 | Kommandozeilenargument | Jemand hat es gerade getippt, für diesen Lauf |
| 2 | Umgebungsvariable | Wie ein Container konfiguriert wird |
| 3 | Konfigurationsdatei (TOML) | Was die Admin-Seite schreibt, was ein Mensch editiert |
| 4 | `weewx.conf` | Was beide Systeme teilen — Standort, Höhe, Archivintervall |
| 5 | Default aus dem Schema | |

Implementiert in `settings.Settings.get()` — `settings.py:108`. Jede Auflösung
merkt sich, woher der Wert kam; das ist, was `--explain` ausgibt.

Sichtbar machen:

```bash
weewx-evo serve --config evo.toml --explain
```

```
  station.name    'Kirchdorf an der Amper'   the configuration file
  interval        60                         $WEEWX_EVO_INTERVAL
  station.altitude 440.0                     weewx.conf
  grace           15                         default
```

## Umgebungsvariablen

Der Name entsteht aus dem Einstellungsnamen: Punkte zu Unterstrichen,
Großbuchstaben, Präfix `WEEWX_EVO_`.

| Einstellung | Variable |
|---|---|
| `token` | `WEEWX_EVO_TOKEN` |
| `station.altitude` | `WEEWX_EVO_STATION_ALTITUDE` |
| `admin.port` | `WEEWX_EVO_ADMIN_PORT` |
| `feeds.json.units` | `WEEWX_EVO_FEEDS_JSON_UNITS` |

### Aliase

Ein paar Namen gab es für Umgebungsvariablen, bevor es sie für Einstellungen
gab. Sie funktionieren weiter, mit dem Faktor, der ihre Einheit in die der
Einstellung überführt (`settings.ENV_ALIASES`):

| Alias | Einstellung | Faktor |
|---|---|---|
| `WEEWX_EVO_LIVE` | `live_db` | 1 |
| `WEEWX_EVO_ARCHIVE` | `archive_db` | 1 |
| `WEEWX_EVO_RETENTION_DAYS` | `retention` | 86400 |
| `WEEWX_EVO_RAW_MINUTES` | `raw_retention` | 60 |

Eine laufende Installation soll nicht kaputtgehen, weil ein Name ordentlicher
wurde. Der Tag, an dem jemand eine Variable umbenennt, ist der Tag, an dem er
herausfindet, an wie vielen Stellen sie benutzt wurde.

## Die Konfigurationsdatei

TOML, weil Python es ohne Abhängigkeit lesen kann und ein Mensch es editieren
kann, ohne etwas zu lernen. **Eine** Datei, und die Admin-Seite schreibt dieselbe
Datei, die ein Mensch schreiben würde.

Zwei Dinge, auf die `config.py` achtet — beide aus Konfigurationsdateien
gelernt, die im Feld schiefgegangen sind:

- **Die Datei wird neu geschrieben, nicht gepatcht.** Werte kommen aus dem
  Schema, Kommentare aus den `help`-Texten. Damit erklärt die Datei sich selbst,
  auch Jahre später, wenn niemand mehr weiß, warum etwas so eingestellt ist.
- **Geschrieben wird daneben und dann hineinbewegt** (`config.write()`), plus
  eine `.bak` der Vorversion. Ein abgebrochener Schreibvorgang kann keine Datei
  hinterlassen, die eine halbe Konfiguration ist.

Was in der Datei steht und kein Schema für sich hat, bleibt beim Neuschreiben
erhalten und wird als „unknown" ausgewiesen (`config._unknown`).

### Beispiel

```toml
# weewx-evo. Written by the settings page; safe to edit by hand.

interval = "5m"
token = "…"

[station]
name = "Kirchdorf an der Amper"
latitude = 48.4596
longitude = 11.6539
altitude = 440.0

[admin]
token = "…"
port = 8080

[drivers.ecowitt]
infer_unknown = "series"

[sources]
outTemp = "garten, dach"
"soil*" = "garten"
"*" = "dach, garten"

[exports.webhost]
kind = "ftp"
host = "ftp.example.org"
trigger = "feed"
```

## Eine Einstellung hinzufügen

Ins Schema, sonst nirgends. `options.py` für den Kern, `options()` am Treiber
für einen Treiber, `options()` am Feed für einen Feed:

```python
Option("infer_unknown", "Fields the catalog does not know",
       kind="choice", default="series",
       choices=(("off", "Drop them"), ("series", "…"), ("all", "…")),
       help="A reading put in the wrong column cannot be separated out afterwards.")
```

Daraus entstehen **von selbst**:

- das Formularfeld auf der Admin-Seite
- die Validierung (`Option.parse`)
- der Kommentar in der geschriebenen Datei
- die Zeile in `--explain`
- der Eintrag in `schema.json`

Es gibt keine zweite Stelle, an der eine Einstellung eingetragen werden muss.

## Das Deklarationsmodell

`options.py` hält drei Dinge:

| | |
|---|---|
| `Option` | Eine Einstellung: Name, Label, `kind`, Default, Hilfe, Grenzen, Auswahl |
| `Group` | Einstellungen, die zusammengehören — wird ein Abschnitt des Formulars |
| `Schema` | Alles, womit eine Komponente konfigurierbar ist |

### `kind`

Eines von `text secret int float bool choice path duration list`. Jedes ist ein
Parser, eine Prüfung und ein Formularfeld. Ein neues `kind` bedeutet: parsen,
prüfen und rendern beibringen — alle drei, an je einer Stelle.

`secret` ist `text`, das nie zurückgerendert wird: die Admin-Seite zeigt, *ob*
eines gesetzt ist, nicht *welches*. Ein Token, das einmal angezeigt wurde, ist
ein Token in einem Screenshot.

`duration` wird geschrieben, wie Menschen es sagen — `90`, `5m`, `2h`, `7d` —
und in Sekunden gehalten. `format_duration()` wählt beim Zurückschreiben die
größte Einheit, die ganz aufgeht: eine Retention als `604800` ist eine Zahl, die
niemand auf einen Blick prüfen kann.

### Weitere Felder an `Option`

| Feld | Wofür |
|---|---|
| `choices_from` | Auswahl, die von der Installation abhängt statt vom Code — `installed_drivers()`, `defined_feeds()`, `published_names()`. Eine **Funktion**, weil sich die Antwort zur Laufzeit ändert: einen Feed hinzuzufügen muss ihn in die Liste des Exports bringen, ohne Neustart |
| `suggestions` | Werte, die es wert sind, angeboten zu werden, ohne andere zu verbieten. Der Fall dafür ist `allow`: „private", „any" oder eine Liste von Netzen, die niemand aufzählen kann |
| `advanced` | Versteckt hinter einem Schalter statt weggelassen — eine versteckte Einstellung ist eine, die man durch Quelltextlesen findet |
| `restart` | Änderung wirkt erst nach Neustart |
| `required` | Leer ist ein Fehler, nicht `None` |
| `minimum` / `maximum` | Bereich, geprüft in `_check_range` |
| `unit`, `placeholder` | Nur Darstellung |

### Zwei Fallen

**Argumente haben keinen Default in argparse.** `default=None`, immer. argparse
kann „nicht angegeben" nicht von „auf den Default gesetzt" unterscheiden, und
ein Default hier schlägt die Konfigurationsdatei — dann tut die Admin-Seite
scheinbar nichts, ohne Fehlermeldung irgendwo. Der Kommentar dazu steht in
`cli.add_common()`, und `tools/settings_test.py` prüft genau das.

**Ein Treiber bekommt `view()`, nicht das Ganze.** Seine Ecke der Einstellungen
und sonst nichts:

```python
settings.view("drivers.ecowitt", schema)
```

Ein Treiber hat im Upload-Token nichts zu suchen, und der Weg das
sicherzustellen ist, es nicht herzugeben. Dieselbe Logik wie bei
[`ingest/state.py`](Drivers#treiber-zustand): das Schmale geben, dann ist das
Breite nicht erreichbar.

## Neu laden

```python
settings.reload()   # gibt zurück, ob sich etwas geändert hat
```

Das ist, was ein Settings-Dienst brächte, ohne den Dienst. Alles, was das Objekt
hält, sieht die neuen Werte; was ein `restart` verlangt, verlangt ihn weiter.

## weewx.conf

**Gelesen, nie geschrieben.** Zwei Programme, die eine Datei schreiben,
zerstören sich gegenseitig die Kommentare.

Die Datenbank ist geteilt — dieselbe Datei, dieselbe Bedeutung. Die
Konfiguration ist es nicht und soll es nicht sein. Was beide Systeme teilen
(Standort, Höhe, Archivintervall), darf trotzdem dort wohnen bleiben:

```bash
weewx-evo serve --weewx-conf /etc/weewx/weewx.conf
```

Oder dauerhaft als `weewx_conf` in der eigenen Datei. Alles, was hier gesetzt
ist, schlägt es. → [WeeWX-Compatibility](WeeWX-Compatibility)

## Kommandos

```bash
weewx-evo config show --config evo.toml            # kommentiert ausgeben
weewx-evo config show --config evo.toml --defaults # mit allen Defaults
weewx-evo config set  --config evo.toml <name> <wert>
weewx-evo config check --config evo.toml           # jeden Wert gegen sein Schema
weewx-evo config import /etc/weewx/weewx.conf [--write] [--overwrite]
```

→ [CLI-Reference](CLI-Reference), [Settings-Reference](Settings-Reference)

## Das Schema als JSON

```
GET http://<host>:8080/<admin-token>/schema.json
```

Dieselbe Deklaration als Daten — für einen Installer, einen Test oder eine
Admin-Seite, die jemandem besser gefällt als diese.

<!-- covers
src/weewx_evo/settings.py
src/weewx_evo/options.py
src/weewx_evo/config.py
tools/settings_test.py
-->
