# Erste Schritte

## Voraussetzungen

Python 3.11 oder neuer. Sonst nichts — weewx-evo hat keine Abhängigkeiten
außerhalb der Standardbibliothek, und das ist Absicht: eine Wetterstation läuft
jahrelang, ohne dass jemand hinschaut, und jede Abhängigkeit ist etwas, das in
dieser Zeit kaputtgehen kann.

Optional, nur für schärfere Sonnenzeiten: `pyephem`. → [Sun](Sun)

## Installieren

```bash
git clone https://github.com/hilman2/weewx-evo
cd weewx-evo
pip install -e .
```

Danach gibt es das Kommando `weewx-evo`. Ohne Installation geht auch:

```bash
PYTHONPATH=src python -m weewx_evo.cli --help
```

## Der kürzeste Weg zu laufenden Daten

### 1. Ein Token setzen

Das Token ist ein Pfadsegment, das jeder Upload tragen muss. Es ist das
Einzige zwischen dem offenen Internet und der Messreihe — Hardware kann keine
Header senden, deshalb ist ein nicht erratbarer Pfad die praktische Antwort.

```bash
python -c "import secrets; print(secrets.token_hex(24))"
```

### 2. Konfigurationsdatei anlegen

```bash
weewx-evo config set --config evo.toml token <das-token-von-eben>
weewx-evo config set --config evo.toml station.name "Kirchdorf an der Amper"
weewx-evo config set --config evo.toml station.latitude 48.4596
weewx-evo config set --config evo.toml station.longitude 11.6539
weewx-evo config set --config evo.toml station.altitude 440
```

`config set` prüft jeden Wert gegen das Schema, das ihn besitzt. Ein Tippfehler
im Namen oder ein Breitengrad von 95 kommt sofort zurück, nicht beim Start.

Oder gleich alles auf einmal — die Datei ist TOML und für Menschen gedacht:

```toml
# evo.toml
token = "…"
interval = "5m"

[station]
name = "Kirchdorf an der Amper"
latitude = 48.4596
longitude = 11.6539
altitude = 440.0
```

### 3. Starten

```bash
weewx-evo serve --config evo.toml
```

Das startet Listener und Archiver in einem Prozess. Beim ersten Start entstehen
`data/live.sdb` und `data/weewx.sdb` — letztere mit demselben Schema, das WeeWX
für eine neue Datenbank anlegt (`wview_extended`, 113 Spalten).

### 4. Die Adresse herausfinden

```bash
weewx-evo url --config evo.toml --qr
```

Druckt die Upload-Adresse und die Live-Ansicht, beide samt Token, und auf Wunsch
einen QR-Code zum Abtippen ins Telefon. Das Token steht im Pfad, also ist eine
Adresse ohne es nutzlos und eine mit ihm der ganze Schlüssel — deshalb gibt es
dieses Kommando: die beiden gehören zusammen.

### 5. Die Konsole darauf zeigen lassen

Bei Ecowitt-Hardware: *Weather Services → Customized*, Protokoll „Ecowitt", Host
die IP des Rechners, Port 8000, Pfad `/<token>/ecowitt/`.

### 6. Nachsehen, ob etwas ankommt

Im Browser: `http://<host>:8000/<token>/live` — die Statusseite. Sie existiert
für genau eine Frage, die man beim Aufbau immer wieder stellt: *kommt was an?*
Ohne sie hieße die Antwort SSH, `docker exec` und eine handgeschriebene
SQL-Abfrage.

Auf der Kommandozeile:

```bash
weewx-evo status --config evo.toml
```

## Eine bestehende WeeWX-Datenbank benutzen

Das ist der eigentliche Fall. Zeigen Sie weewx-evo auf die vorhandene Datei:

```bash
weewx-evo config set --config evo.toml archive_db /etc/weewx/archive/weewx.sdb
```

Das Schema wird **aus der Datei gelesen**, nicht aus einer Liste im Code. Eine
Anlage mit eigenen Spalten behält sie. WeeWX kann dieselbe Datei danach
weiterbenutzen. → [WeeWX-Compatibility](WeeWX-Compatibility)

**Vorher sichern.** Nicht kopieren, sondern:

```bash
sqlite3 weewx.sdb "VACUUM INTO 'backup.sdb'"
```

`cp` auf eine Datenbank, die nebenher beschrieben wird, ergibt zusammen mit
einem halb kopierten WAL einen zerrissenen Zustand.

### Die Einstellungen aus weewx.conf übernehmen

```bash
weewx-evo config import /etc/weewx/weewx.conf --config evo.toml
weewx-evo config import /etc/weewx/weewx.conf --config evo.toml --write
```

Ohne `--write` wird nur berichtet. Der Bericht nennt auch, was **nicht**
übernommen wurde und warum — Schweigen liest sich wie „verloren".
→ [WeeWX-Compatibility](WeeWX-Compatibility)

### Die Diagramme aus einer Skin übernehmen

```bash
weewx-evo plots import /etc/weewx/skins/Seasons/skin.conf
weewx-evo plots import /etc/weewx/skins/Seasons/skin.conf --write
```

→ [Plots](Plots)

## Was keine Spalte hat, wird gemeldet

Ein Messwert überlebt das Archivintervall nur, wenn die Tabelle eine Spalte für
ihn hat. Das Standardschema hat 113, Ecowitt-Hardware füllt das Vierfache.

```bash
weewx-evo columns --config evo.toml
```

```
44 field(s) arriving, 8 with nowhere to live.

  dayRain           2831 packet(s), e.g. 0.012      -> REAL
  lightning_num     2831 packet(s), e.g. 0.0        -> INTEGER
  ...
```

Angelegt wird nichts von allein: wohin ein Messwert gehört, ist eine
Entscheidung, und die falsche mischt zwei Sensoren in eine Spalte, die danach
niemand mehr trennt. `--add` legt an — **vorher sichern**.

## Die Einstellungsseite

```bash
weewx-evo config set --config evo.toml admin.token <ein-anderes-token>
weewx-evo admin --config evo.toml
```

Dann `http://<host>:8080/<admin-token>/`. Eigener Port, eigenes Token: ein
Upload kann schlimmstenfalls einen falschen Messwert schreiben, die Admin-Seite
kann das Archiv auf eine andere Datei zeigen lassen. Gleiches Token für beides
wird verweigert. → [Admin-Page](Admin-Page), [Security](Security)

Von außen erreichbar machen, ohne sie zu öffnen:

```bash
ssh -L 8080:localhost:8080 die-station
```

## Woher ein Wert kommt

```bash
weewx-evo serve --config evo.toml --explain
```

```
  station.name    'Kirchdorf an der Amper'   the configuration file
  interval        60                         $WEEWX_EVO_INTERVAL
  station.altitude 440.0                     weewx.conf
  grace           15                         default
```

Eine Zeile je Einstellung, mit ihrer Herkunft. Danach hört das Programm auf.
→ [Configuration](Configuration)

## Eine eigene Seite im lokalen Netz

Drei Zeilen, und die Diagramme sind im Browser:

```toml
[exports.site]
kind = "local"
directory = "data/site"
source = "json"

[web]
enabled = true
default = "site"
```

Ein [`local`-Export](Exports#ein-verzeichnis-auf-dieser-maschine) legt hin, was
der [JSON-Feed](Feeds) erzeugt hat, und der eingebaute
[Web-Server](Web-Server) liefert es unter `http://<host>:8081/` aus. Der Name
des Exports **ist** die Adresse — niemand muss denselben Pfad zweimal
aufschreiben.

## Nächste Schritte

- Diagramme und JSON erzeugen → [Plots](Plots), [Feeds](Feeds)
- Auf einen Webhost schieben → [Exports](Exports)
- Im Container betreiben → [Deployment](Deployment)
- Einen zweiten Sensor dazunehmen → [Multiple-Sources](Multiple-Sources)

<!-- covers
README.md
-->
