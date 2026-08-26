# Treiber

`ingest/drivers.py`, `ingest/envelope.py`, `ingest/parsers.py`,
`ingest/state.py`, `ingest/plugins/`, `ingest/userdrivers.py`.

## Der Schnitt

**Der Kern besitzt den Socket.** Threads, Shutdown, Body-Limits, IPv6, die
Token-Prüfung und das Schreiben in die Live-Tabelle. Das ist für jedes Protokoll
dasselbe, es ist die Stelle, an der Push-Treiber schiefgehen, und es einmal zu
machen heißt, es einmal zu machen.

**Der Treiber besitzt alles andere.** Parsen, Feldnamen, Einheiten, welchem
Gerät er überhaupt antwortet, und **was dieses Gerät zurückhören muss**.

## Die Schnittstelle

```python
class Driver(Protocol):
    def packets(self, body: bytes, meta: dict) -> list[Packet]:
        ...
```

`meta` trägt `received` (Ankunftszeit, unix) und `source` (die Peer-Adresse).

**Eine leere Liste zurückzugeben ist normal und kein Fehler**: Konsolen senden
Probeanfragen, Heartbeats und Uploads ohne Messwerte darin.

### `BaseDriver`

Für einen Treiber, der nur parsen muss. Defaults für alles andere.

```python
from weewx_evo.ingest.drivers import BaseDriver

class MyDriver(BaseDriver):
    response = (b'{"ok":true}', "application/json")

    def packets(self, body, meta):
        return [...]
```

| Attribut / Methode | Bedeutung |
|---|---|
| `response` | `(bytes, content_type)` — was das Gerät hören will |
| `packets(body, meta)` | Der Kern der Sache |
| `status()` | Was auf `/status` erscheinen soll. Optional |
| `close()` | Freigeben, was gehalten wird. Optional |
| `options()` | Die Einstellungen dieses Treibers, als `Group`-Liste. Optional |
| `redact(raw)` | Der Upload mit dem Geheimen entfernt. Optional |

Weitere optionale Haken, die die Ecowitt-Implementierung zeigt:
`hardware_name()`, `unit_groups()`, `missing_columns(known)`.

### `options()` deklariert die Einstellungen

Ein Treiber, der eine Einstellung dazubekommt, bekommt ein Formularfeld,
Validierung und einen Kommentar in der geschriebenen Datei — ohne dass sich
irgendwo sonst etwas ändert.

```python
@staticmethod
def options():
    from weewx_evo.options import Group, Option
    return [
        Group("Console", "Which hardware this driver answers to.", (
            Option("passkey", "Console PASSKEY", kind="secret", …),
        ), prefix="drivers.mine"),
    ]
```

→ [Configuration](Configuration)

### Die Deklaration wird angewandt, nicht nur dokumentiert

Ein Treiber sagt `kind="duration"` und bekäme dann den String `"4h"` gereicht,
weil das ist, was in der Konfigurationsdatei steht. **Dass jeder Treiber seine
Werte noch einmal selbst parst, ist genau das, was das Options-Schema verhindern
soll** — und einer, der es vergisst, bekommt beim Start ein `ValueError`,
abgefangen, und läuft danach still auf seinem Default.

`drivers._parsed()` wendet deshalb die Deklaration des Treibers **einmal** an,
bevor er gebaut wird. Was das Schema nicht verstehen kann, wird verworfen statt
weitergereicht: der Treiber fällt auf seinen eigenen Default zurück und die
Station zeichnet weiter auf. **Laut gesagt**, weil die Einstellung dann nicht
tut, was derjenige denkt, der sie geschrieben hat.

## Die Registry

`drivers.Registry` hält **Instanzen, keine Klassen**: ein Treiber hält
Konfiguration und Zustand — welchen Konsolen er antwortet, welche Feldabbildung
zu welcher gehört — und das muss zwischen zwei Uploads überleben.

| Methode | Bedeutung |
|---|---|
| `register(name, driver, replace=False)` | Eine fertige Instanz |
| `register_factory(name, factory, aliases=())` | Etwas, das gebaut wird, sobald seine Konfiguration bekannt ist |
| `configure(name, options)` | Die Factory mit ihren Optionen bauen und installieren |
| `_parsed(factory, options)` | Die Optionen in der Form, die der Treiber deklariert hat |
| `get(name)`, `known(name)`, `names()` | |
| `canonical_names()` | Namen, die kein Alias eines anderen Treibers sind |
| `aliases_of(name)` | |
| `load()` | Holen, was installiert ist |
| `close()` | |

`aliases` sind andere Namen für denselben Treiber — ein zweites Protokoll, das
er auch liest. Ecowitt hat `wunderground` als Alias. Einen zu konfigurieren
konfiguriert alle: **zwei Instanzen desselben Treibers würden je eine Station
adoptieren und je einen eigenen Zustand führen.** Deshalb gibt
`canonical_names()` nur die echten zurück.

`load()` meldet einen kaputten Treiber, wird aber **nie fatal**. Ein Paket, das
sich nicht importieren lässt, darf den Listener nicht mitnehmen: die anderen
Protokolle haben weiter Messwerte, die ankommen.

## Woher Treiber kommen

### 1. Mitgeliefert — `ingest/plugins/`

Unsere. Ein Unterordner je Treiber, jedes ein Paket mit einem
`load(registry)`. **Nichts wird von Hand aufgezählt**: jedes Unterverzeichnis
wird probiert, also heißt einen Treiber hinzuzufügen, ein Verzeichnis
hinzuzufügen.

```python
# ingest/plugins/__init__.py
def bundled() -> list[str]  # die Treiberpakete in diesem Verzeichnis
def load(registry) -> list[str]  # jedes registrieren, Namen zurück
```

Dass wichtige Treiber hier liegen, ist eine Entscheidung über **Pflege**, nicht
über Kopplung: ein Treiber im Repo hängt an derselben Schnittstelle wie einer
von außen und ließe sich herausziehen, ohne dass der Kern es merkt.

### 2. Installiert — `<datenverzeichnis>/drivers/`

Fremde. Sie liegen **außerhalb** des Pakets, damit ein Upgrade sie nicht anfasst
und nichts darin für unseres gehalten wird.

```bash
weewx-evo driver install https://github.com/jemand/weewx-evo-acurite
weewx-evo driver install ./treiber.zip
weewx-evo driver install ./ein-verzeichnis
weewx-evo driver list
weewx-evo driver remove acurite
```

`userdrivers.py`:

| Funktion | Bedeutung |
|---|---|
| `directory(configured, archive)` | Wo sie liegen. `--driver-dir`, dann `driver_dir`, dann neben dem Archiv. Auch `WEEWX_EVO_DRIVER_DIR` |
| `installed(where)` | Was installiert ist, als `(Name, Herkunft)` |
| `load(registry, where)` | Jeden registrieren |
| `install(source, where, name, force)` | Aus Git-URL, Zip oder Verzeichnis |
| `remove(name, where)` | |
| `inspect_source(package)` | Wonach der Code greift, als `{Hinweis: [Dateien]}` |

Beim Installieren wird **nichts ausgeführt und nichts importiert**. Ein Treiber
ist Code, der später als Dienst läuft, und die Entscheidung, ihn zu
installieren, kommt vor dem ersten Ausführen. Auch `_is_driver()` prüft durch
Lesen, nicht durch Importieren.

`_find_package()` sucht das Paket oben, eine Ebene tiefer (ein Zip wickelt meist
alles in ein nach dem Release benanntes Verzeichnis), sowie unter `src/` und
`bin/user/`.

Die Herkunft steht in `.origin` neben dem Paket.

### 3. Als Entry Point

```toml
[project.entry-points."weewx_evo.drivers"]
mine = "my_package:MyDriver"
```

## Kann ein Treiber Amok laufen?

**Im Prozess: nein, nicht verhinderbar.** Ein Treiber ist Python im selben
Interpreter, `import sqlite3` genügt, und keine Schnittstelle hindert Code
daran, sie zu umgehen. WeeWX hat dieselbe Eigenschaft.

Die Zwischenschicht ist deshalb ein **Vertrag, kein Käfig**. Damit ist das
Richtige einfach und das Falsche eine sichtbare, absichtliche Handlung.

Durchgesetzt wird es außerhalb des Prozesses:

| Mittel | Wirkung |
|---|---|
| `listen` und `archive` getrennt (`deploy/split.yml`) | Der Listener öffnet das Archiv nie. Ein Treiber darin **hat die Datei nicht** |
| Eigener Benutzer ohne Schreibrecht aufs Archiv | Macht die Frage gegenstandslos |
| `driver install` liest den Code | Meldet `sqlite3`, `subprocess`, `socket`. Ein Hinweis, keine Garantie |

`NOTABLE` in `userdrivers.py` ist diese Liste. Sie sieht nicht durch
Verschleierung hindurch und kann keine Absicht beurteilen — sie fängt den
ehrlichen Fehler und die faule Abkürzung.

→ [Security](Security), [Deployment](Deployment)

## Treiber-Zustand

`ingest/state.py`. Ein Treiber muss sich manchmal etwas über Neustarts hinweg
merken. weewx-ecowitt merkt sich, welche Konsole er adoptiert hat — sonst wird
die nächste Konsole, die hochlädt, zur Station, und zwei Sensoren landen in
einer Spalte.

Das Naheliegende wäre, ihm den `ArchiveStore` zu geben. Das ist **zu viel**: er
könnte dann Sätze schreiben, Spalten anlegen und Historie löschen.

```python
class State(Protocol):
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str) -> None: ...
    def delete(self, key: str) -> None: ...
```

Drei Methoden auf Strings. Sonst nichts.

| Implementierung | Wo es liegt |
|---|---|
| `ArchiveState` | Die `metadata`-Tabelle des Archivs. Der richtige Ort: sie sitzt bei den Messwerten, die der Zustand schützt, ist in jedem Backup davon und zieht mit ihnen um |
| `FileState` | Eine JSON-Datei — für den Listener allein und für Tests. Schlechter (eine neu aufgesetzte Maschine verliert sie), aber besser als nichts |
| `NoState` | Merkt sich nur innerhalb des Prozesses |

`for_driver(name, archive=None, path=None)` wählt die beste verfügbare
Absicherung.

Dieselbe Logik wie bei `Settings.view()`: **das Schmale geben, dann ist das
Breite nicht erreichbar.**

## Der Umschlag — der einzige Treiber im Kern

`ingest/envelope.py`. Das ist der **Vertrag, kein Protokoll**: die Form, die ein
Treiber übergibt, wenn er fertig ist, und das einzige Format, das der Kern
selbst versteht.

```json
{"dateTime": 1787734265, "usUnits": 1, "source": "vantage-1",
 "kind": "loop", "interval": null, "data": {"outTemp": 21.4}}
```

Ein Objekt oder eine Liste davon. `data` darf auch flach im Objekt selbst
liegen, was das ist, was die meisten Absender tun. `RESERVED` nennt die
Schlüssel, die dann nicht als Messwerte gelesen werden.

Erreichbar unter `/<token>/json/`, per UDP, und über `listener.push()`.

## `parsers.py`

Die ältere, funktionsbasierte Registry: ein Parser bekommt Bytes und gibt Pakete
zurück. Sie fasst keine Datenbank an, öffnet keinen Socket und weiß nicht, wie
spät es ist, außer die Nutzlast sagt es.

Genau das macht ein Protokoll gegen eine gespeicherte Aufzeichnung testbar — und
Aufzeichnungen sind hier die einzige ehrliche Prüfung, weil Konsolen nicht das
senden, was ihre Dokumentation sagt.

`parse_json` ist derselbe Umschlag wie oben. Neue Treiber sollten `Driver` /
`BaseDriver` implementieren; `parsers` bleibt für den funktionsbasierten Weg.

## Einen Treiber schreiben

```python
"""A driver for a station that posts one line of numbers."""

from weewx_evo.db.live import Packet
from weewx_evo.ingest.drivers import BaseDriver


class LineDriver(BaseDriver):
    response = (b"OK\n", "text/plain")

    def packets(self, body: bytes, meta: dict) -> list[Packet]:
        temp, humidity = body.decode().split(",")
        return [Packet(
            dateTime=int(meta["received"]),
            usUnits=1,
            data={"outTemp": float(temp), "outHumidity": float(humidity)},
            source="line",
            kind="loop",
        )]


def load(registry):
    registry.register("line", LineDriver())
```

`tools/driverinstall.py` baut genau so ein Paket auf der Platte auf,
installiert es, lädt es und nimmt einen Upload damit entgegen — der Test dafür,
dass ein fremder Treiber an derselben Schnittstelle hängt wie ein
mitgelieferter.

→ [Driver-Ecowitt](Driver-Ecowitt), [Testing](Testing)

<!-- covers
src/weewx_evo/ingest/drivers.py
src/weewx_evo/ingest/envelope.py
src/weewx_evo/ingest/parsers.py
src/weewx_evo/ingest/state.py
src/weewx_evo/ingest/userdrivers.py
src/weewx_evo/ingest/plugins/__init__.py
tools/driverinstall.py
-->
