# CLI-Referenz

Ein Programm, `weewx-evo`, definiert in `cli.py`. Drei Dienste und ein paar
Operationen auf den Datenbanken. Jeder Dienst läuft allein oder alle in einem
Prozess, weil sie über die Datenbank reden und nie miteinander.

```
weewx-evo [--log-level LEVEL] <kommando> …
```

`--log-level` gilt global, Default `INFO`, auch über `WEEWX_EVO_LOG_LEVEL`.

## Gemeinsame Argumente

`add_common()` hängt diese an fast jedes Kommando:

| Argument | Bedeutung |
|---|---|
| `--config PATH` | Die TOML-Konfiguration. Auch `WEEWX_EVO_CONFIG` |
| `--live PATH` | Die Live-Paketdatenbank |
| `--archive PATH` | Die WeeWX-Archivdatenbank |
| `--interval SPEC` | Archivintervall, z. B. `5m` |
| `--table NAME` | Die Archivtabelle |
| `--sources PATH` | TOML mit `[sources]`. Auch `WEEWX_EVO_SOURCES` |
| `--weewx-conf PATH` | Eine `weewx.conf` zum Zurückfallen. Auch `WEEWX_EVO_WEEWX_CONF` |
| `--driver-dir PATH` | Wo fremde Treiber liegen |

**Keines davon hat einen argparse-Default.** Das ist keine Nachlässigkeit:
argparse kann „nicht angegeben" nicht von „auf den Default gesetzt"
unterscheiden, und ein Default hier schlüge die Konfigurationsdatei. Die
Defaults leben im Schema. → [Configuration](Configuration)

## Dienste

### `serve`

Listener und Archiver in einem Prozess. Für eine kleine Maschine. Sie reden
trotzdem nur über die Datenbank; sie später zu trennen ist eine Änderung an den
Unit-Dateien, nicht am Code.

```bash
weewx-evo serve --config evo.toml
weewx-evo serve --config evo.toml --explain
```

Zusätzlich zu `add_common`, `add_listen_args` und `add_archive_args`:

| Argument | Bedeutung |
|---|---|
| `--explain` | Jede Einstellung und ihre Herkunft drucken, dann aufhören |

`serve` startet außerdem, was konfiguriert ist: die Admin-Seite (wenn
`admin.token` gesetzt ist), den Web-Server (wenn `web.enabled`), den Feed-Runner
und den Export-Runner.

### `listen`

Nur der Listener. Öffnet das Archiv nie — das ist der Punkt.

```bash
weewx-evo listen --config evo.toml
```

`add_listen_args()`:

| Argument | Bedeutung |
|---|---|
| `--host` | Bindeadresse |
| `--port` | HTTP-Port |
| `--udp-port` | `0` schaltet den UDP-Listener ab |
| `--token` | Das Pfadsegment. Ohne es kann jeder schreiben |
| `--driver` | Treiber für Uploads, deren Pfad keinen nennt |
| `--rate` | Anfragen je Sekunde und Adresse. Eine Konsole sendet im schnellsten Fall 0.5. `0` schaltet ab |
| `--behind-proxy` | Ratelimit dem Proxy überlassen |
| `--allow` | Wer eine Antwort bekommt: `private` (Default), `any`, oder eine Liste |

### `archive`

Nur der Archiver. Hält keine Treiber, hört auf nichts.

```bash
weewx-evo archive --config evo.toml --spool /data/packets
```

`add_archive_args()`:

| Argument | Bedeutung |
|---|---|
| `--grace` | Wie lange nach Intervallende gewartet wird |
| `--poll` | Wie oft nachgesehen wird, in Sekunden |
| `--retention-days` | Wie lange Pakete bleiben, in Tagen |
| `--spool PATH` | Pakete vor dem Verwerfen als gzip-NDJSON schreiben |
| `--raw-minutes` | Wie lange die Rohuploads bleiben. `0` behält keine |

### `web`

Nur die Feeds ausliefern. Getrennt von `serve` aus demselben Grund wie `listen`:
eine Maschine, die nur Seiten zeigt, muss nicht die sein, die sie aufzeichnet.

```bash
weewx-evo web --config evo.toml --port 8081
```

| Argument | Bedeutung |
|---|---|
| `--host`, `--port` | |
| `--allow` | Wer eine Antwort bekommt (Default `private`) |

→ [Web-Server](Web-Server)

### `admin`

Die Einstellungsseite. Eigener Port und eigenes Token, absichtlich: ein
Upload-Endpunkt kann schlimmstenfalls einen falschen Messwert schreiben, dieser
hier kann das Archiv woandershin zeigen lassen.

```bash
weewx-evo admin --config evo.toml
```

| Argument | Bedeutung |
|---|---|
| `--config PATH` | Die Datei, die diese Seite editiert |
| `--host`, `--port` | Default `0.0.0.0:8080` |
| `--allow` | `private` (Default), `any`, oder eine Liste |
| `--token` | Das eigene Token, nie das Upload-Token |
| `--rate` | Anfragen je Sekunde und Adresse (Default 5) |
| `--behind-proxy` | Ratelimit dem Proxy überlassen |
| `--read-only` | Einstellungen zeigen, Speichern verweigern |

→ [Admin-Page](Admin-Page)

## Auf den Datenbanken

### `catchup`

Jedes Intervall bauen, das die Live-Tabelle abdeckt. Nach einer Ausfallzeit oder
beim ersten Start gegen eine gefüllte Live-Datei.

```bash
weewx-evo catchup --config evo.toml
weewx-evo catchup --config evo.toml --replace
```

| Argument | Bedeutung |
|---|---|
| `--replace` | Bereits vorhandene Sätze überschreiben |

### `rebuild`

Eine Zeitspanne noch einmal rechnen und ersetzen. Danach werden die
Tagesstatistiken jedes betroffenen Tages aus der Archivtabelle neu aufgebaut und
anschließend wieder aus den Paketen geschärft.

```bash
weewx-evo rebuild 1755000000 1755086400
```

| Argument | Bedeutung |
|---|---|
| `start` | Unix-Zeitstempel, exklusiv |
| `stop` | Unix-Zeitstempel, inklusiv |

→ [Archiver](Archiver)

### `columns`

Messwerte, für die das Archiv keine Spalte hat.

```bash
weewx-evo columns --config evo.toml
weewx-evo columns --config evo.toml --add
```

| Argument | Bedeutung |
|---|---|
| `--add` | Die fehlenden Spalten anlegen. **Vorher die Datenbank sichern** |

Das Standardschema hat 113 Spalten, Ecowitt-Hardware kann das Vierfache füllen.
Wohin ein Messwert gehört, ist eine Entscheidung — `python -m
weewx_evo.ingest.plugins.ecowitt` sagt genauer, wohin.

### `status`

Was in den beiden Datenbanken steht.

```bash
weewx-evo status --config evo.toml
```

### `url`

Die Adressen der Live-Ansicht und des Upload-Endpunkts, mit Token.

```bash
weewx-evo url --config evo.toml
weewx-evo url --config evo.toml --qr
```

| Argument | Bedeutung |
|---|---|
| `--config PATH` | |
| `--token`, `--port` | Überschreiben, was in der Konfiguration steht |
| `--driver NAME` | Welchen Treiber die Upload-Adresse nennen soll |
| `--public URL` | Die Außenadresse, z. B. hinter einem Reverse Proxy. Auch `WEEWX_EVO_PUBLIC_URL` |
| `--qr` | Zusätzlich einen QR-Code im Terminal |

Das Token ist ein Pfadsegment, also ist eine Adresse ohne es nutzlos und eine
mit ihm der ganze Schlüssel. Genau deshalb gibt es dieses Kommando: die beiden
sind immer zusammen.

Der QR-Code ist handgerollt statt als Abhängigkeit — das ist eine Bequemlichkeit
in einem Kommando, und eine Wetterstation, die jahrelang läuft, sollte dafür
kein Paket dazubekommen.

## `config`

```bash
weewx-evo config show   [--config PATH] [--defaults]
weewx-evo config set    [--config PATH] <name> <wert>
weewx-evo config check  [--config PATH]
weewx-evo config import <weewx.conf> [--config PATH] [--write] [--overwrite]
```

| | |
|---|---|
| `show` | Die Konfiguration, wie sie ist, kommentiert. `--defaults` füllt jeden Default auf, um zu sehen, was es gibt |
| `set` | Einen Wert setzen, geprüft gegen das Schema, das ihn besitzt |
| `check` | Jeden Wert gegen sein Schema prüfen und sagen, was falsch ist |
| `import` | Eine `weewx.conf` lesen und übernehmen. Ohne `--write` wird nur berichtet. `--overwrite` ersetzt auch, was hier schon gesetzt ist |

→ [Configuration](Configuration), [WeeWX-Compatibility](WeeWX-Compatibility)

## `driver`

```bash
weewx-evo driver list
weewx-evo driver install <quelle> [--name NAME] [--force]
weewx-evo driver remove <name>
```

Die Quelle ist eine Git-URL, eine Zip-URL, eine `.zip`-Datei oder ein
Verzeichnis. Bei der Installation wird **nichts ausgeführt und nichts
importiert** — ein Treiber ist Code, der später als der Dienst läuft, und die
Entscheidung, ihn zu installieren, kommt vor dem ersten Ausführen.

`install` liest den Code und meldet, wonach er greift: `sqlite3`, `subprocess`,
`socket`. Ein Hinweis, keine Garantie.

Diese Unterkommandos nehmen `--driver-dir` und `--archive` (letzteres nur, um
das Default-Treiberverzeichnis zu finden), aber kein `--config`. Ein blankes
`weewx-evo driver list` funktioniert dadurch weiter.

→ [Drivers](Drivers)

## `plots`

```bash
weewx-evo plots list   [--plots PATH]
weewx-evo plots show   <name> [--plots PATH]
weewx-evo plots import <skin.conf> [--write] [--replace] [--plots PATH]
weewx-evo plots remove <name> [--plots PATH]
weewx-evo plots run    [--into DIR] [--no-page] [--plots PATH]
```

| | |
|---|---|
| `list` | Welche Diagramme es gibt |
| `show` | Eines vollständig |
| `import` | Die Diagramme aus einer WeeWX-Skin holen. Gelesen, berichtet, und erst auf `--write` behalten. `--replace` fängt bei null an, statt zu ergänzen |
| `remove` | Eines löschen |
| `run` | Das JSON jetzt erzeugen und sagen, was herauskam. `--no-page` lässt die Diagnoseseite weg |

Ein Import, der stillschweigend einen mühsam eingestellten Satz Diagramme
ersetzt, wäre schlimmer als gar kein Import.

→ [Plots](Plots)

## `export`

```bash
weewx-evo export list  [--config PATH]
weewx-evo export check [name] [--config PATH]
weewx-evo export run   [name] [--source DIR] [--all]
```

| | |
|---|---|
| `list` | Was verfügbar und was konfiguriert ist |
| `check` | Das Ziel probieren, ohne etwas zu senden. Ein falsches Passwort oder ein falscher Pfad sofort zurück ist viel wert |
| `run` | Senden. `--all` sendet alles, nicht nur Geändertes. `--source` überschreibt das Quellverzeichnis |

→ [Exports](Exports)

## Exit-Codes

`0` bei Erfolg. Ein Fehler wird als Zeile auf stdout berichtet und gibt einen
Wert ungleich null zurück — Kommandos, die etwas prüfen (`config check`,
`export check`), geben ungleich null zurück, wenn etwas nicht stimmt, damit sie
in einem Skript brauchbar sind.

<!-- covers
src/weewx_evo/cli.py
-->
