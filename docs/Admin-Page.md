# Die Einstellungsseite

`admin.py`, `adminplots.py`.

Ein Formular, gebaut aus dem, was Einstellungen deklariert: der Kern, jeder
Treiber, jeder Feed, jeder Export.

**Nichts hier weiß, was ein Ecowitt ist oder was ein Archivintervall bedeutet.**
Es rendert `Option`-Objekte und schreibt zurück, was herauskommt. Das ist der
ganze Entwurf: ein Treiber, der eine Einstellung dazubekommt, bekommt ein Feld,
und diese Datei ändert sich nicht. → [Configuration](Configuration)

## Starten

```bash
weewx-evo config set --config evo.toml admin.token <ein-anderes-token>
weewx-evo admin --config evo.toml
```

Dann `http://<host>:8080/<admin-token>/`.

Eigener Port, eigenes Token, absichtlich: ein Upload kann schlimmstenfalls einen
falschen Messwert schreiben, diese Seite kann das Archiv auf eine andere Datei
zeigen lassen. **Gleiches Token für beides wird verweigert.**
→ [Security](Security)

Von auswärts erreichen, ohne sie zu öffnen:

```bash
ssh -L 8080:localhost:8080 die-station
```

## Die Routen

| | |
|---|---|
| `GET /<token>/` | Die erste Seite |
| `GET /<token>/<schema>` | Ein Abschnitt: `core`, `drivers.ecowitt`, `feeds.json`, `export:<name>` |
| `GET /<token>/plot:<name>` | Ein Diagramm |
| `GET /<token>/new-plot` | Diagramm anlegen |
| `GET /<token>/import-plots` | Aus einer WeeWX-Skin importieren |
| `GET /<token>/new-export` | Export anlegen |
| `GET /<token>/schema.json` | Die ganze Deklaration als JSON |
| `POST /<token>/<schema>` | Speichern |
| `POST /<token>/<name>/test` | Ein Export-Ziel probieren |
| `POST /<token>/<name>/remove` | Löschen |

Nach jedem erfolgreichen Speichern wird **umgeleitet**, damit ein Neuladen nicht
noch einmal speichert.

## `Admin`

Was die Seiten tun, ohne das HTTP.

```python
admin = Admin(path, schemas, token, read_only=False,
              access=PRIVATE_ONLY, limits=limits)
```

| Methode | Bedeutung |
|---|---|
| `schemas()` | Alles Konfigurierbare, das es gibt |
| `refresh()` | Die Liste neu bauen. Nach allem, was hinzugefügt oder entfernt wurde |
| `config()`, `values(schema)` | |
| `save(schema, form)` | Prüfen und schreiben. Gibt zurück, was falsch war |
| `add_export(name, kind)` | |
| `remove_export(name)` | Aus der Konfiguration löschen. **Nichts am anderen Ende** |
| `test_export(name)` | Ein Ziel probieren und sagen, was passierte |
| `columns()` | Die Messwerte, für die das Archiv eine Spalte hat |

### Alles wird geprüft, bevor irgendetwas geschrieben wird

`save()` sammelt **alle** Fehler und schreibt erst danach. Ein Formular, das die
Hälfte anwendet, die es verstanden hat, und den Rest meldet, hinterlässt eine
Konfiguration, die niemand angefordert hat.

### `columns()` fragt die Datenbank

Nicht ein Schema. Eine Station, deren Treiber eigene Spalten angelegt hat, soll
sie zeichnen können, und nichts hier weiß etwas darüber.

### `MARKER = "__present__"`

Ein verstecktes Feld, das mitgeschickt wird, damit ein **Teil-POST** erkennbar
ist. Ohne das setzt ein Formular, das nur eine Gruppe schickt, alles andere auf
den Default zurück — im Browser fällt das nie auf, und `tools/adminpage.py`
prüft genau das.

`MAX_FORM = 1 << 18`. `NAME` erzwingt kleine Namen ohne Überraschungen:
`^[a-z][a-z0-9_-]{0,31}$`.

### `_form(content_type, body)` — auch mit Datei

Gewöhnliche Einstellungen kommen urlencodiert. Der [Plot-Importer](Plots)
braucht zusätzlich eine **Datei**, also multipart — und `cgi.FieldStorage` wurde
in Python 3.13 entfernt. Der E-Mail-Parser macht dieselbe Arbeit und ist nicht
weggegangen.

Eine Datei kommt als ihr Text unter ihrem eigenen Feldnamen zurück. Nichts hier
behandelt etwas anderes als Text, und eine `skin.conf` ist Text.

**Ein leer gelassenes Datei-Feld postet trotzdem**, ohne Dateinamen und ohne
Inhalt. Es darf das Feld nicht schlagen, das jemand tatsächlich ausgefüllt hat.

## Wie ein Feld entsteht

```python
def field(option: Option, value: Any, error: str = "") -> str
def group_html(group: Group, values, errors) -> str
def page(admin, active, errors=None, message="", form=None) -> bytes
```

`kind` entscheidet:

| `kind` | Feld |
|---|---|
| `text`, `path` | `<input type="text">` |
| `secret` | `<input type="password">`, **nie zurückgerendert** |
| `int`, `float` | `<input type="number">` mit `min`/`max` |
| `bool` | Checkbox |
| `choice` | `<select>`, gefüllt aus `choices` + `choices_from()` |
| `duration` | Zahl plus Einheit (`split_duration`) |
| `list` | Kommagetrennt |

`suggestions` wird ein `<datalist>`: die drei üblichen Antworten sind ein Klick
weit weg, eine ungewöhnliche kann getippt werden.

`advanced` liegt hinter einem Schalter — **versteckt, nicht weggelassen**. Eine
weggelassene Einstellung ist eine, die man durch Quelltextlesen findet, was
schlimmer ist als eine lange Seite.

`restart` wird markiert, damit klar ist, was ein Speichern nicht sofort bewirkt.

## Ein Export anlegen

`new_export_page()` fragt **zwei Felder**: Name und Art. Alles andere wird auf
der Seite ausgefüllt, die danach erscheint.

Nach einem Host und einem Passwort zu fragen, bevor klar ist, wovon geredet
wird, ist ein Formular, das jemand ausfüllt, ohne zu wissen, was er ausfüllt.

`export_kinds()` wird **gefragt, nicht aufgezählt**.

## Die Diagramm-Seiten

`adminplots.py`. Der einzige handgeschriebene Teil.

Ein Plot passt nicht in den Formulargenerator: eine Einstellung ist **ein**
benannter Wert, ein Plot ist ein Satz mit einer Liste von Sätzen darin, und es
gibt hundert davon.

Was diese Seiten besser können müssen als ein Texteditor, sonst hat es keinen
Sinn: sehen, welche Messwerte die Datenbank überhaupt hat, ohne nachzuschlagen —
und einen Satz aus einer WeeWX-Skin herüberholen, ohne ihn abzutippen.

→ [Plots](Plots#die-admin-seiten)

## `schema.json`

```
GET /<token>/schema.json
```

Die ganze Deklaration als JSON. Eine **zweite Schnittstelle zu derselben
Deklaration** — für einen Installer, einen Test oder eine Admin-Seite, die
jemandem besser gefällt als diese.

## `--read-only`

Zeigt die Einstellungen und verweigert das Speichern. Für einen Blick auf eine
Anlage, die man nicht anfassen will.

## Prüfen

```bash
python tools/adminpage.py
```

Rendert die Seite, speichert durch sie hindurch und bricht sie absichtlich. Was
dabei wirklich geprüft wird, ist die Kette **Deklaration → Formular →
Validierung → Datei**, für jede Art von Einstellung, die es gibt.

Nichts außerhalb eines Temp-Verzeichnisses wird angefasst.

Die Fälle, die etwas gefunden haben:

- Ein **Teil-POST**, der alles andere auf Default zurücksetzt.
- Ein **Roundtrip**, bei dem `"5m"` als String zurückkommt statt als 300.

→ [Testing](Testing)

<!-- covers
src/weewx_evo/admin.py
tools/adminpage.py
-->
