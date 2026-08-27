# weewx-evo

Ein Neubau des WeeWX-Kerns. Python, ohne Abhängigkeiten außerhalb der
Standardbibliothek, ab 3.11.

## Die eine Regel

> Eine bestehende WeeWX-Datenbank bleibt lesbar und schreibbar — **für WeeWX
> selbst**. Nicht „importierbar": dieselbe Datei, dieselbe Bedeutung, und
> WeeWX 5 kann sie danach weiterbenutzen.

Alles andere in diesem Projekt ist verhandelbar. Das hier nicht. Wer eine Zeile
in [`aggregate.py`](Aggregation), [`db/archive.py`](Database-Archive) oder
[`db/daily.py`](Daily-Summaries) ändert, führt vorher und nachher
`python tools/difftest.py reference/weewx.sdb` aus — siehe [Testing](Testing).

Praktisch folgen daraus drei Dinge:

| | |
|---|---|
| **Das Schema kommt aus der Datei** | Nie aus einer Liste im Code. Eine Anlage mit eigenen Spalten behält sie. → [Database-Archive](Database-Archive) |
| **Die Arithmetik ist abgeschrieben** | `aggregate.py` ist eine Transkription von `weewx.accum`, Schritt für Schritt. Eine „sauberere" Formel, die anders rundet, ist hier eine falsche Formel. → [Aggregation](Aggregation) |
| **`archive_day_*` ist ein Cache** | Alles darin ist aus `archive` ableitbar, und `rebuild_day` ist die Ableitung. → [Daily-Summaries](Daily-Summaries) |

## Der Schnitt

```
Quellen (Push oder Pull, je eigener Prozess)
  └─ Listener: HTTP + UDP, Token, Treiber-Plugins
      └─ live: jedes Paket, mit Herkunft, N Tage
          └─ Archiver: deterministisch je Zeitspanne
              └─ archive (WeeWX-kompatibel, PK dateTime)
                  └─ archive_day_* (Cache)
                      └─ series → Feeds → Exports
```

Die Komponenten reden **ausschließlich über die Datenbank**, nie miteinander.
Deshalb laufen sie als drei systemd-Units oder als ein Prozess, ohne
Codeänderung. Das ist keine Zierde, sondern die Eigenschaft, die
`deploy/split.yml` möglich macht. → [Architecture](Architecture)

## Wo anfangen

**Ich will es laufen lassen** → [Getting-Started](Getting-Started) ·
[CLI-Reference](CLI-Reference) · [Deployment](Deployment)

**Ich will verstehen, wie es aufgebaut ist** → [Architecture](Architecture) ·
[WeeWX-Compatibility](WeeWX-Compatibility) · [Glossary](Glossary)

**Ich will etwas ändern** → [Contributing](Contributing) · [Testing](Testing) ·
[Index](Index) (welche Datei zu welcher Seite gehört, samt Veraltungs-Markierung)

**Ich suche eine Funktion** → [API-Index](API-Index)

## Lizenz

**GPL-3.0-or-later.** Der Ecowitt-Treiber geht über
[weewx-ecowitt](https://github.com/hilman2/weewx-ecowitt) auf den
`ecowittcustom`-Treiber von Werner Krenn zurück, der wiederum auf den
`interceptor` von Matthew Wall — beide GPLv3, und das ist der Grund.

Das uPlot in `feeds/diagnostic/vendor/` ist MIT und hat seine eigene
Lizenzdatei daneben liegen.

## Die Seiten

### Aufnahme

| Seite | Worum es geht |
|---|---|
| [Ingest-Listener](Ingest-Listener) | HTTP + UDP, Token, Ratelimit, Statusseite |
| [Drivers](Drivers) | Die Treiber-Schnittstelle, mitgelieferte und fremde Treiber |
| [Driver-Ecowitt](Driver-Ecowitt) | Der Ecowitt-Treiber, vollständig |
| [Uploads](Uploads) | Die Messwerte an einen Wetterdienst |
| [MQTT](MQTT) | Der eigene Client, und was ihn nötig macht |
| [Forecast](Forecast) | Vorhersage und Warnungen, vier Quellen |
| [Plugins](Plugins) | Was nicht im Kern liegt, und der Katalog dafür |
| [Multiple-Sources](Multiple-Sources) | Mehrere Stationen, eine Messreihe |

### Verarbeitung und Speicherung

| Seite | Worum es geht |
|---|---|
| [Database-Live](Database-Live) | Die Live-Tabelle: jedes Paket, N Tage lang |
| [Archiver](Archiver) | Archivsätze aus Zeitspannen |
| [Aggregation](Aggregation) | Die Arithmetik — Transkription von `weewx.accum` |
| [Database-Archive](Database-Archive) | Die WeeWX-Datenbank, lesend und schreibend |
| [Daily-Summaries](Daily-Summaries) | `archive_day_*` als ableitbarer Cache |
| [Derived-Readings](Derived-Readings) | Taupunkt, Windchill, Regen-Delta |

### Ausgabe

| Seite | Worum es geht |
|---|---|
| [Series](Series) | Zeitreihen aus dem Archiv — die Grundlage jedes Feeds |
| [Units](Units) | Einheiten, Gruppen, Umrechnung, Zielsystem |
| [Sun](Sun) | Sonnenstand, Auf- und Untergang, Dämmerung |
| [Plots](Plots) | Plot-Definitionen und `plots.toml` |
| [Feeds](Feeds) | Was erzeugt wird — JSON-Feed, Diagnoseseite |
| [Exports](Exports) | Wie es woandershin kommt — FTP, rsync |
| [Web-Server](Web-Server) | Die Feeds lokal ausliefern |

### Betrieb

| Seite | Worum es geht |
|---|---|
| [Configuration](Configuration) | Die Rangfolge, das Option-Schema, `--explain` |
| [Settings-Reference](Settings-Reference) | Jede Kern-Einstellung, vollständig |
| [CLI-Reference](CLI-Reference) | Jedes Kommando, jedes Flag |
| [Admin-Page](Admin-Page) | Die Einstellungsseite |
| [Security](Security) | Tokens, Netzgrenze, Ratelimit |
| [Deployment](Deployment) | Docker, Caddy, der geteilte Betrieb |
| [Testing](Testing) | Die Werkzeuge in `tools/` und was jedes prüft |
| [WeeWX-Compatibility](WeeWX-Compatibility) | Was geteilt wird, was nicht, `weewx.conf` |
| [Contributing](Contributing) | Schreibstil, Konventionen, Fallen |

<!-- covers
README.md
CLAUDE.md
src/weewx_evo/__init__.py
src/weewx_evo/db/__init__.py
src/weewx_evo/ingest/__init__.py
pyproject.toml
LICENSE
-->
