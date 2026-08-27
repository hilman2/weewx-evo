# Testing

Alle Tests laufen **ohne Netz** und **ohne Zustand außerhalb eines
Temp-Verzeichnisses**.

## Alles auf einmal

```bash
python tools/difftest.py reference/weewx.sdb    # die Arithmetik
python tools/roundtrip.py reference/weewx.sdb   # das Schreiben
python tools/derive_test.py reference/weewx.sdb # die abgeleiteten Werte
python tools/seriestest.py reference/weewx.sdb  # die Zeitreihen (braucht WeeWX)
python tools/unitcheck.py                       # alle Umrechnungen
python tools/suncheck.py                        # Sonnenauf- und -untergang
python tools/smoke.py                           # alles zusammen
python tools/multisource.py                     # mehrere Stationen
python tools/driverinstall.py                   # Fremdtreiber
python tools/adminpage.py                       # die Einstellungsseite
python tools/netaccess_test.py                  # wer geantwortet wird
python tools/ratelimit_test.py                  # die zwei Grenzen
python tools/settings_test.py                   # die Rangfolge
python tools/export_test.py                     # FTP und rsync
python tools/web_test.py                        # Routing und Verzeichnisgrenze
```

Dazu die übernommenen Treibertests:

```bash
wsl -d Ubuntu -- bash -lc 'source ~/venvs/weewx/bin/activate && \
  cd /mnt/d/Git/weewx-evo && python -m pytest tests/ecowitt -q'
```

## Was ein Test hier wert ist

Die Tests, die etwas gefunden haben, prüfen alle dasselbe Muster: **eine
Annahme, die im Browser nie auffällt.**

| Was gefunden wurde | Wo |
|---|---|
| Ein Teil-POST, der alles andere auf Default zurücksetzt | `adminpage.py` |
| Ein Roundtrip, bei dem `"5m"` als String zurückkommt statt als 300 | `adminpage.py` |
| SQLite-Verbindungen sind thread-gebunden | `smoke.py` |
| Eine Konsole sperrt sich nach fünf **gültigen** Uploads selbst aus | `ratelimit_test.py` |
| Drei Transkriptionsfehler in den Knoten-Faktoren | `unitcheck.py` |
| pyephem zählt Refraktion doppelt, wenn man ihm `horizon` gibt | `suncheck.py` |
| `skip_if_empty = year` als Boolean gelesen: 100 Dateien statt 71 | Plot-Importer |

Wer etwas hinzufügt, sucht **diese Sorte Fall**.

## Die Werkzeuge im Einzelnen

### `difftest.py` — der Abnahmetest

**Der Abnahmetest für das ganze Projekt.** Kann weewx-evos Arithmetik die
Tagesstatistiken einer Datenbank nicht reproduzieren, die WeeWX selbst
geschrieben hat, ist nichts darauf Gebautes vertrauenswürdig, und keine noch so
gute Architektur macht das wett.

```bash
python tools/difftest.py reference/weewx.sdb
```

Zwei Spaltenklassen, zwei Maßstäbe:

```python
SUM_COLUMNS     = {"sum", "count", "wsum", "sumtime", "xsum", "ysum",
                   "dirsumtime", "squaresum", "wsquaresum"}
EXTREME_COLUMNS = {"min", "mintime", "max", "maxtime", "max_dir"}
```

- **Summen** stammen ausschließlich aus Archivsätzen und müssen **exakt**
  stimmen.
- **Extreme** dürfen abweichen — aber nur **stumpfer**, nie schärfer. Schärfer
  wäre ein Fehler, und genau darauf prüft der Test.

```
sum mismatches:            0
extremes sharper than DB:  0
extremes duller than DB:   189   (expected: LOOP highs/lows)
```

→ [Aggregation](Aggregation)

### `roundtrip.py` — das Schreiben

`difftest` prüft die Arithmetik. Das hier prüft das **Schreiben**: eine Kopie
einer echten Datenbank, die letzten N Tage gelöscht — Archivsätze und
Tagesstatistiken — und über den **normalen Schreibpfad** zurückgeschrieben, Satz
für Satz, genau wie der Archiver es bei einem Catch-up täte.

```bash
python tools/roundtrip.py reference/weewx.sdb --days 3
python tools/roundtrip.py reference/weewx.sdb --days 3 --packets
```

`--packets` speist die gespeicherten LOOP-Pakete wieder ein (`feed_packets()`).
Wo sie den Zeitraum abdecken, sinkt die Zahl der stumpfen Extreme entsprechend:
**109 → 89 bei 76 % Abdeckung.**

Das ist der messbare Beleg für die [Live-Tabelle](Database-Live).

`Tally` zählt Unterschiede und behält die ersten paar jeder Art zum Zeigen.

### `derive_test.py` — die abgeleiteten Werte

Die Referenzdatenbank hat Jahre von Sätzen, in denen WeeWX Taupunkt, Hitzeindex
und den Rest aus Messwerten gerechnet hat, **die in derselben Zeile stehen**.
Ein Testorakel, das niemand schreiben musste.

Dazu `rain_tests()` (der eine, der eine Messung ist), `policy_tests()` (die drei
Politiken) und `edge_tests()` (die Ränder der Definitionsbereiche).

→ [Derived-Readings](Derived-Readings)

### `seriestest.py` — die Zeitreihen

Fragt **WeeWX und weewx-evo nach derselben Reihe** und vergleicht.

```python
TOLERANCE = 1e-06
```

94 Vergleiche, 19 957 Punkte, 0 Fehler, 8 bekannte Abweichungen — alle acht die
[bewusste Abweichung](Series#eine-bewusste-abweichung) beim gewichteten
Mittelwert.

Braucht ein installiertes WeeWX.

### `unitcheck.py` — die Einheiten

Alle 147 Umrechnungen gegen WeeWX, bei neun Werten:

```python
SAMPLES = (0.0, 1.0, -1.0, 7.5, 100.0, -40.0, 1013.25, 0.001, 98765.4321)
```

Dazu Gruppen, Systeme, Beschriftungen und Formate.

Die Ausfallart, gegen die das schützt, ist **leise**: ein Faktor, der in der
vierten Nachkommastelle danebenliegt, erzeugt ein Diagramm, das richtig aussieht
und von WeeWX' Diagramm desselben Tages abweicht.

→ [Units](Units)

### `suncheck.py` — die Sonne

Sechs Orte von Tromsø bis Ushuaia, fünf Tage einschließlich der vier Wendepunkte
des Jahres, gegen pyephem **und** gegen `weeutil.Sun`.

```python
TOLERANCE = 60.0    # Sekunden
LOOSE     = 600.0
```

→ [Sun](Sun)

### `smoke.py` — alles zusammen

Startet einen Listener, postet **echte** Ecowitt-Uploads dagegen, lässt den
Archiver die Intervalle ausrechnen und prüft, was landete.

Das ist der Test, der die Fehler fängt, die die Einzeltests nicht können:

- ein Parser, dessen Feldnamen nicht zum Schema passen
- ein Archiver, der einen Satz ohne `interval` schreibt
- ein Listener, der antwortet, bevor er gespeichert hat

`post()` gibt Body **und** Content-Type zurück. Beides zählt: das Gateway prüft
beides.

### `multisource.py` — mehrere Stationen

Prüft genau die drei Fälle, die `weewx-metadriver` als seine Grenzen nennt.

→ [Multiple-Sources](Multiple-Sources)

### `driverinstall.py` — Fremdtreiber

Baut ein Treiberpaket auf der Platte auf, wie jemand es veröffentlichen würde,
installiert es, lädt es und nimmt einen Upload damit entgegen.

Der Test dafür, dass ein fremder Treiber an **derselben Schnittstelle** hängt
wie ein mitgelieferter.

→ [Drivers](Drivers)

### `adminpage.py` — die Einstellungsseite

Rendert die Seite, speichert durch sie hindurch und bricht sie absichtlich.
Geprüft wird die Kette **Deklaration → Formular → Validierung → Datei**, für
jede Art von Einstellung, die es gibt.

`multipart()` und `upload()` posten ein Formular so, wie ein Browser eines mit
einer Datei darin postet — `SKIN` ist eine kleine `[ImageGenerator]`-Sektion.
Damit ist auch der Plot-Importer über den echten Weg geprüft, nicht über einen
Umweg an ihm vorbei.

→ [Admin-Page](Admin-Page)

### `netaccess_test.py` — wer geantwortet wird

Treibt beide Server mit einem Socket, dessen Quelladresse tatsächlich anders
ist. **Eine Peer-Adresse lässt sich über TCP nicht fälschen**, also ist das
echt prüfbar und nicht gemockt.

### `ratelimit_test.py` — die zwei Grenzen

Und **dass es nicht dieselbe Grenze ist**. Beides zu vermengen gibt einem das
Schlechteste von beidem: entweder eine Grenze, die locker genug zum Durchraten
ist, oder eine, die so eng ist, dass eine Konsole sich selbst aussperrt.

→ [Security](Security)

### `settings_test.py` — die Rangfolge

Fünf Orte, eine feste Reihenfolge, ein Auflöser. Die Reihenfolge ist leicht zu
formulieren und leicht subtil falsch zu machen, deshalb ist sie hier festgenagelt
statt in einem Kommentar beschrieben.

**Der Teil, der am härtesten geprüft wird, ist der, der wie ein Detail
aussieht**: ein Argument, das *nicht* angegeben wurde, darf die
Konfigurationsdatei nicht schlagen.

`args_with(**kwargs)` baut einen Namespace, in dem alles Unbenannte `None` ist —
so wie argparse ihn hinterlässt.

→ [Configuration](Configuration)

### `export_test.py` — FTP und rsync

Die FTP-Hälfte läuft gegen einen Server **in diesem Prozess**: Dateien landen
auf der Platte, Verzeichnisse entstehen, das Hineinbewegen passiert. Kein Mock.

`pyftpdlib` ist keine Abhängigkeit von weewx-evo, dieser Teil wird also
ausgelassen, wenn es fehlt, und der Rest läuft trotzdem.

Die rsync-Hälfte prüft die Kommandozeile — nichts geht durch eine Shell.

`local_export()` prüft die Ausfallarten, die FTP nicht hat: ein Hardlink, der
still einen Inode teilt; ein Löschen, das mehr mitnimmt als das, was dieser
Export hingelegt hat; ein Ziel, das das Quellverzeichnis ist. Und danach, dass
der **Web-Server tatsächlich ausliefert, was der Export veröffentlicht hat** —
die beiden Hälften der Kette in einem Test.

`runner_tests()` prüft mit einem absichtlich langsamen `FakeExport`, wann welcher
Export läuft und dass einer den anderen nicht aufhalten kann.

→ [Exports](Exports)

### `web_test.py` — Routing und Grenze

Liefert ein paar Dateien aus und versucht, aus dem Verzeichnis herauszukommen.

→ [Web-Server](Web-Server)

## Was hinausgeht

```bash
python tools/upload_test.py     # was an einen Wetterdienst geht
python tools/mqtt_test.py       # der MQTT-Client, gegen einen eigenen Broker
python tools/forecast_test.py   # die Vorhersagequellen und ihr Speicher
python tools/realtime_test.py   # realtime.txt und wxnow.txt
```

Keiner davon fasst das Netz an. `upload_test.py` und `forecast_test.py` bauen
Anfragen und sehen sie an; `mqtt_test.py` startet einen Broker auf loopback.

`upload_test.py` vergleicht zusätzlich gegen WeeWX, wenn es importierbar ist —
die Ambient-Query parameterweise und das CWOP-Paket Zeichen für Zeichen. Beide
sind Transkriptionen, und eine Transkription ist entweder identisch oder ein
Fehler:

```bash
wsl -d Ubuntu -- bash -lc 'source ~/venvs/weewx/bin/activate && \
  cd /mnt/d/Git/weewx-evo && PYTHONPATH=/mnt/d/Git/weewx/src:src \
  python3 tools/upload_test.py'
```

## Die Treibertests

59 Tests unter `tests/ecowitt/`, ursprünglich aus weewx-ecowitt.

```bash
python -m pytest tests/ecowitt -q
```

Sie gehören jetzt hierher und dürfen wachsen: der Treiber ist Kern, kein
gespiegeltes Fremdrepo.

→ [Driver-Ecowitt](Driver-Ecowitt#die-tests)

## Die Referenzdaten

`reference/` liegt in `.gitignore` — echte Messwerte, mehrere Megabyte.

Neu ziehen:

```bash
ssh <host> 'docker exec weewx python3 -c "
import sqlite3
for s in [\"weewx.sdb\", \"weewx-loop.sdb\"]:
    c = sqlite3.connect(\"/data/archive/\" + s)
    c.execute(\"VACUUM INTO ?\", (\"/data/snap-\" + s,)); c.close()"'
scp <host>:/opt/weewx/data/snap-weewx.sdb reference/weewx.sdb
ssh <host> 'rm -f /opt/weewx/data/snap-*.sdb'
```

**`VACUUM INTO` statt `cp`**: die Datenbank wird nebenher beschrieben, und ein
kopiertes WAL ist ein zerrissener Zustand.

## Dev-Tooling

Alle Python-Dev-Tools laufen in **WSL Ubuntu**, nie mit Windows-Python:

```bash
wsl -d Ubuntu -- bash -lc 'source ~/venvs/weewx/bin/activate && \
  cd /mnt/d/Git/weewx-evo && ruff check src tools tests'
```

Die Default-WSL-Distro ist `docker-desktop` und hat kein Python — deshalb immer
explizit `-d Ubuntu`.

Venvs liegen unter `~/venvs/<project>` **innerhalb** WSL, nicht im Repo auf
`/mnt/d` (NTFS-Long-Path-Bug).

<!-- covers
tools/difftest.py
tools/roundtrip.py
tools/derive_test.py
tools/seriestest.py
tools/unitcheck.py
tools/suncheck.py
tools/smoke.py
tools/multisource.py
tools/driverinstall.py
tools/adminpage.py
tools/netaccess_test.py
tools/ratelimit_test.py
tools/settings_test.py
tools/export_test.py
tools/web_test.py
tests/ecowitt/fixtures/README.md
pyproject.toml
-->
