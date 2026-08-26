# Architektur

## Der Datenfluss

```
   Hardware / andere Stationen
        │  HTTP POST · HTTP GET (Wunderground) · UDP
        ▼
┌───────────────────────────────────────────────────────┐
│ Listener            ingest/listener.py                │
│  Socket, Threads, Body-Limit, Token, Netzgrenze,      │
│  Ratelimit — der Kern.                                │
│         │ body: bytes, meta: dict                     │
│         ▼                                             │
│  Treiber            ingest/drivers.py, plugins/       │
│  Parsen, Feldnamen, Einheiten, Antwort ans Gerät      │
└─────────┬─────────────────────────────────────────────┘
          │ list[Packet]
          ▼
   ┌──────────────┐   db/live.py
   │ live.sdb     │   append-only, idempotent, Retention N Tage
   │  packet      │   inkl. Herkunft (source) und Rohbody
   └──────┬───────┘
          │  packets(start, stop)
          ▼
┌───────────────────────────────────────────────────────┐
│ Archiver            archiver.py                       │
│  1. Pakete des Intervalls holen                       │
│  2. sources.py: welche Quelle gewinnt je Feld         │
│  3. aggregate.py: Accumulator füttern                 │
│  4. derive.py: Taupunkt, Windchill, Regen-Delta       │
│  5. Satz schreiben, dann Tagesextreme schärfen        │
└─────────┬─────────────────────────────────────────────┘
          │ dict (ein Archivsatz)
          ▼
   ┌──────────────┐   db/archive.py
   │ weewx.sdb    │   archive        ← WeeWX-kompatibel, PK dateTime
   │              │   archive_day_*  ← Cache, aus archive ableitbar
   └──────┬───────┘
          │  series.Reader
          ▼
   ┌──────────────┐   feeds/ + feedrunner.py
   │ Feeds        │   jsongenerator → JSON-Zeitreihen
   │              │   diagnostic    → HTML-Diagnoseseite
   └──────┬───────┘
          │  ein Verzeichnis
          ├───────────────► webserver.py (lokal ausliefern)
          ▼
   ┌──────────────┐   exports/
   │ Exports      │   ftp.py · rsync.py, je eigener Thread
   └──────────────┘
```

## Die Kernregel der Kopplung

Die Komponenten reden **ausschließlich über die Datenbank**, nie miteinander.
Es gibt keinen Kanal zwischen Listener und Archiver, absichtlich.

Was das kauft:

- **Ein Prozess oder drei**, ohne Codeänderung. `weewx-evo serve` startet beide;
  `listen` und `archive` starten je einen. Das ist der Unterschied zwischen
  `deploy/compose.yml` und `deploy/split.yml` — und sonst nichts.
- **Ein Neustart mitten im Archivintervall kostet nichts.** Es gibt keinen
  In-Memory-Akkumulator, der ihn nicht überlebt: die Pakete liegen schon in der
  Live-Tabelle.
- **Ein verspätetes Push-Paket landet im richtigen Intervall.** Es wird nach
  seinem eigenen Zeitstempel eingeordnet, nicht nach seiner Ankunft.
- **Rückwirkend korrigierbar.** Solange die Rohdaten in der Retention liegen,
  lässt sich eine falsche Kalibrierung mit `weewx-evo rebuild` herausrechnen.
- **Ein Treiber kann nicht ins Archiv schreiben**, wenn der Listener die Datei
  gar nicht gemountet hat. → [Security](Security), [Deployment](Deployment)

Jede Stufe ist aus der vorherigen reproduzierbar. Es gibt keinen flüchtigen
Zustand, aus dem sich eine Zahl herleitet.

## Kern und Treiber

**Der Kern besitzt den Socket.** Threads, Shutdown, Body-Limits, Token-Prüfung,
Netzgrenze, Rate-Limit, Schreiben in die Live-Tabelle. Das ist für jedes
Protokoll dasselbe, und es ist die Stelle, an der Push-Treiber schiefgehen.

**Der Treiber besitzt alles andere.** Parsen, Feldnamen, Einheiten, welchem
Gerät er antwortet, und **was das Gerät zurückhören muss**. Er liefert ein
fertiges Paket. Der Kern schaut nicht hinein.

```python
class MyDriver:
    response = (b'{"ok":true}', "application/json")   # was das Gerät hören will

    def packets(self, body: bytes, meta: dict) -> list[Packet]:
        ...
```

Der Kern kennt kein Wetterprotokoll. Wer in `listener.py` oder `archiver.py`
etwas über Ecowitt schreiben will: es gehört in den Treiber.
→ [Drivers](Drivers)

## Feeds und Exports

Zwei verschiedene Dinge, und WeeWX trennt sie nicht:

- **Feed** = *was* erzeugt wird. Eine CSV, ein JSON-Dokument, ein Diagramm,
  eine ganze Webseite, ein Monatsbericht. Schreibt in ein Verzeichnis.
- **Export** = *wie* es woandershin kommt. FTP, rsync, Kopie auf eine
  eingehängte Freigabe.

Das Verzeichnis ist die ganze Schnittstelle dazwischen — genauso wie die
Live-Tabelle zwischen Listener und Archiver. Ein Feed, drei Exports. Oder drei
Feeds in ein Verzeichnis und ein Export. Keiner weiß vom anderen.

Bei WeeWX konfiguriert man den FTP-Upload *innerhalb* der Skin-Sektion. Zwei
Ziele bedeuten dort, den Renderer zweimal laufen zu lassen.

→ [Feeds](Feeds), [Exports](Exports)

## Threads

Drei Stellen laufen nebenläufig, jede aus einem benannten Grund:

| Thread | Wo | Warum |
|---|---|---|
| HTTP-Handler | `listener.HttpListener` (`ThreadingHTTPServer`) | Eine langsame Konsole darf die anderen nicht blockieren |
| Feed-Runner | `feedrunner.Runner`, **ein** Thread für alle Feeds | 100 Diagramme sind eine knappe Sekunde, und eine Sekunde dort ist eine Sekunde, in der der Archiver nicht archiviert. Ein Thread, weil Feeds geordnet sind |
| Export-Runner | `exports/runner.Runner`, **ein Thread je Export** | Ein FTP-Host, der nicht mehr antwortet, hängt 30 s im `connect` — und darf dabei weder den Archiver noch den anderen Export aufhalten |

Ein Export kann sich dadurch auch nicht selbst überlappen: der Thread steckt in
`send()` und liest seinen eigenen Auslöser nicht. Was währenddessen feuert, wird
gemerkt und danach **einmal** ausgeführt.

SQLite-Verbindungen sind thread-gebunden. `LiveStore.conn()` öffnet deshalb je
Thread eine eigene Verbindung beim ersten Zugriff — das war ein echter Fehler
und ist jetzt Teil des Designs.

## Prozessmodelle

### Ein Prozess (der Normalfall)

```bash
weewx-evo serve
```

Listener, Archiver, optional Admin-Seite, Web-Server, Feeds und Exports in
einem Prozess. Richtig für einen Pi Zero im Schuppen.

### Getrennt (wenn ein Treiber nicht ans Archiv soll)

```bash
weewx-evo listen     # hält die Treiber, mountet nur live.sdb
weewx-evo archive    # hält keine Treiber, mountet beide Dateien
```

Der Listener öffnet das Archiv nie. Ein Treiber darin *hat* die Datei nicht.
Das ist der einzige durchsetzbare Käfig — im selben Prozess genügt
`import sqlite3`. → `deploy/split.yml`, [Security](Security)

Zwei Fallen, beide im Kommentar von `split.yml` festgehalten:

- **Retention gehört zum Archiver**, nicht zum Listener. Pakete dürfen erst
  fallen, wenn sie in einem Satz stehen, und nur diese Seite weiß das.
- **SQLite im WAL-Modus schreibt `-shm` und `-wal` neben die Datei — auch zum
  Lesen.** Ein read-only gemountetes *Verzeichnis* ist deshalb nicht dasselbe
  wie eine read-only Datei und schlägt fehl. Der wirksame Weg ist ein Benutzer
  ohne Schreibrecht aufs Archiv.

## Warum kein Settings-Dienst

Die Frage kommt wieder, deshalb die Begründung: Die Datei **ist** schon, was ein
Daemon wäre, ohne dessen Ausfallarten — atomar geschrieben, überlebt Neustarts
in der richtigen Reihenfolge, mit `cat` lesbar, kann nicht down sein. Listener
und Archiver koordinieren bewusst **nur** über die Datenbank; ein Kanal zwischen
ihnen würde aufheben, dass man sie trennen oder zusammenlegen kann. Was ein
Dienst wirklich brächte — Änderung ohne Neustart — macht `Settings.reload()`.

→ [Configuration](Configuration)

## Paketstruktur

```
src/weewx_evo/
  __init__.py          Die eine Regel, als Docstring
  cli.py               Alle Kommandos, das einzige Programm
  settings.py          Die Rangfolge: Argument > Umgebung > Datei > weewx.conf > Default
  options.py           Option / Group / Schema — das Deklarationsmodell
  config.py            TOML lesen und kommentiert zurückschreiben
  weewxconf.py         weewx.conf lesen (nie schreiben)

  aggregate.py         Transkription von weewx.accum
  obstypes.py          Welche Größe wie aggregiert wird
  archiver.py          Ersetzt StdArchive
  derive.py            Ersetzt StdWXCalculate
  sources.py           Mehrere Stationen, eine Messreihe
  series.py            Ersetzt xtypes.get_series
  units.py             Transkription von weewx.units
  sun.py               Sonnenstand, Auf- und Untergang
  plots.py             Plot-Definitionen und plots.toml

  db/
    schema.py          Schema aus der Datei lesen
    wview.py           Das Startschema für eine neue Datei
    archive.py         Die WeeWX-Datenbank
    daily.py           archive_day_* aufbauen
    live.py            Die Live-Tabelle

  ingest/
    listener.py        HTTP + UDP
    drivers.py         Treiber-Schnittstelle und Registry
    envelope.py        Der JSON-Umschlag — der einzige Treiber im Kern
    parsers.py         Ältere, funktionsbasierte Registry
    state.py           Was ein Treiber sich merken darf
    statuspage.py      Die Live-Seite hinter dem Token
    userdrivers.py     Fremde Treiber installieren
    plugins/           Unsere Treiber, ein Ordner je Treiber
      ecowitt/

  feeds/
    __init__.py        Die Feed-Schnittstelle
    jsongenerator/     Die Zeitreihen, auf denen alles andere steht
    diagnostic/        Zeichnet, was tatsächlich auf der Platte liegt
  feedrunner.py        Fährt die Feeds der Reihe nach, eigener Thread

  exports/
    __init__.py        Export-Schnittstelle und Registry
    ftp.py  rsync.py   Die zwei gebauten
    runner.py          Wann welcher läuft
    tracker.py         Was schon gesendet wurde

  admin.py             Die Einstellungsseite
  adminplots.py        Die Diagramm-Seiten darin (handgeschrieben)
  webserver.py         Die Feeds ausliefern
  netaccess.py         Wer eine Antwort bekommt
  ratelimit.py         Zwei Grenzen: Anfragen und Fehlversuche
```

<!-- covers
src/weewx_evo/__init__.py
deploy/split.yml
-->
