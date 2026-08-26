# weewx-evo

Ein Proof of Concept: der WeeWX-Kern neu geschrieben, modular, ohne Altlasten —
und ohne dass eine bestehende Datenbank etwas davon merkt.

Läuft auf einer Testinstanz neben einer WeeWX-Instanz, beide an derselben
Wetterstation, beide mit derselben Historie als Startpunkt. Die Archive lassen
sich Satz für Satz vergleichen.

## Die eine Regel

Eine bestehende WeeWX-Datenbank muss lesbar und schreibbar bleiben — für WeeWX
selbst. Nicht „importierbar": dieselbe Datei, dieselbe Bedeutung, und WeeWX 5
kann sie danach weiterbenutzen. Alles andere ist verhandelbar, das hier nicht.

## Der Schnitt

```
Quellen (Push oder Pull, je eigener Prozess)
  └─ Listener: HTTP + UDP, Token, Parser-Plugins
      └─ live: jedes Paket, mit Herkunft, N Tage
          └─ Archiver: deterministisch je Zeitspanne
              └─ archive (WeeWX-kompatibel, PK dateTime)
                  └─ archive_day_* (Cache, jederzeit neu berechenbar)
```

Jede Stufe ist aus der vorherigen reproduzierbar. Es gibt keinen flüchtigen
Zustand, aus dem sich eine Zahl herleitet — kein In-Memory-Akkumulator, der
einen Neustart nicht überlebt.

Die Komponenten reden **ausschließlich über die Datenbank**, nie miteinander.
Deshalb laufen sie als drei systemd-Units auf einem Server oder als ein
Prozess auf einem Pi Zero, ohne dass sich eine Zeile Code ändert.

Was das kauft, und was WeeWX heute nicht kann:

- Neustart mitten im Archivintervall kostet nichts.
- Ein verspätetes Push-Paket landet im richtigen Intervall.
- Eine falsche Kalibrierung oder ein Ausreißer lässt sich rückwirkend
  korrigieren, solange die Rohdaten in der Retention liegen.

## Der Kern bietet den Listener. Treiber bringen alles mit.

Die Trennung ist die Architektur, deshalb ausdrücklich:

**Der Kern besitzt den Socket.** Threads, Shutdown, Body-Limits, IPv6,
Token-Prüfung, Schreiben in die Live-Tabelle. Das ist für jedes Protokoll
dasselbe, und es ist die Stelle, an der Push-Treiber schiefgehen.

**Der Treiber besitzt alles andere.** Parsen, Feldnamen, Einheiten, welchem
Gerät er überhaupt antwortet, und **was dieses Gerät zurückhören muss**. Er
liefert ein fertiges Paket ab. Der Kern schaut nicht hinein, weiß nicht, was
ein Ecowitt ist, und lässt sich das auch nicht beibringen.

```python
class MyDriver:
    response = (b'{"ok":true}', "application/json")   # was das Gerät hören will

    def packets(self, body: bytes, meta: dict) -> list[Packet]:
        ...
```

```toml
[project.entry-points."weewx_evo.drivers"]
mine = "my_package:MyDriver"
```

### Zwei Orte für Treiber

```
src/weewx_evo/ingest/plugins/     unsere, im Repo, zentral gepflegt
  ecowitt/                        weewx-ecowitt, komplett übernommen
<datenverzeichnis>/drivers/       fremde, per CLI installiert
```

**`plugins/`** sind unsere. Ein Unterordner je Treiber, nichts wird von Hand
aufgezählt — jedes Unterverzeichnis wird geladen. Der erste ist
[weewx-ecowitt](https://github.com/hilman2/weewx-ecowitt), vollständig
übernommen: `catalog.py` (1074 Zeilen Feldkatalog), `mapping.py`, `infer.py`,
`protocol.py`, `consoles.py`, `columns.py`, `report.py`, `__main__.py`, plus
59 Tests, die unverändert mitliefen. Nur `driver.py` ist neu — das ist das
Stück, das WeeWX kannte und jetzt weewx-evo kennt.

Dass wichtige Treiber hier liegen, ist eine Entscheidung über Pflege, nicht
über Kopplung: ein Treiber im Repo hängt an derselben Schnittstelle wie einer
von außerhalb und ließe sich herausziehen, ohne dass der Kern es merkt.

**Fremde Treiber** liegen außerhalb des Pakets, damit ein Upgrade sie nicht
anfasst und nichts darin für unseres gehalten wird:

```bash
weewx-evo driver install https://github.com/jemand/weewx-evo-acurite
weewx-evo driver install ./treiber.zip
weewx-evo driver list
weewx-evo driver remove acurite
```

### Kann ein Treiber Amok laufen?

Im Prozess: **nein, nicht verhinderbar.** Ein Treiber ist Python im selben
Interpreter, `import sqlite3` genügt, und keine Schnittstelle hindert Code
daran, sie zu umgehen. WeeWX hat dieselbe Eigenschaft.

Die Zwischenschicht ist deshalb ein Vertrag, kein Käfig. Ein Treiber bekommt
einen `state` — `get`, `set`, `delete` auf Strings — und nicht den
`ArchiveStore`. Damit ist das Richtige einfach und das Falsche eine sichtbare,
absichtliche Handlung.

Durchgesetzt wird es außerhalb des Prozesses, und die Architektur kann das
schon:

| Mittel | Wirkung |
|---|---|
| `weewx-evo listen` und `archive` getrennt (`deploy/split.yml`) | Der Listener öffnet das Archiv nie. Ein Treiber darin hat die Datei nicht. |
| Eigener Benutzer ohne Schreibrecht aufs Archiv | Macht die Frage gegenstandslos. |
| `weewx-evo driver install` liest den Code | Meldet `sqlite3`, `subprocess`, `socket`. Ein Hinweis, keine Garantie. |

Die Live-Tabelle ist die einzige Schnittstelle zwischen den beiden Diensten.
Deshalb ist das Aufteilen eine Änderung an einer Compose-Datei und an keiner
Zeile Code.

### Was keine Spalte hat, wird gemeldet

Ein Messwert überlebt das Archivintervall nur, wenn die Tabelle eine Spalte
für ihn hat. Das Standardschema hat 113, Ecowitt-Hardware füllt das Vierfache.
Dass etwas wegfällt, ist normal — dass es **still** wegfällt, ist der Fehler,
den dieses Projekt beheben will:

```
$ weewx-evo columns
44 field(s) arriving, 8 with nowhere to live.

  dayRain           2831 packet(s), e.g. 0.012      -> REAL
  lightning_num     2831 packet(s), e.g. 0.0        -> INTEGER
  ...
```

Angelegt wird nichts von allein. Wohin ein Messwert gehört, ist eine
Entscheidung, und die falsche mischt zwei Sensoren in eine Spalte, die danach
niemand mehr trennt. `--add` legt an, das Werkzeug des Treibers
(`python -m user.ecowitt`) sagt genauer, wohin.

## Mehrere Quellen

WeeWX kennt genau einen `station_type`, deshalb braucht das Zusammenführen
zweier Stationen dort einen Treiber, der Treiber umschließt —
[weewx-metadriver](https://github.com/tkeffer/weewx-metadriver). Dessen
Grenzen folgen daraus, *wo* er sitzt: Pakete werden beim Eintreffen
zusammengeführt, also darf nur der primäre Treiber Archivsätze liefern, nur
seine Uhr wird gelesen, und ein abgestürztes Kind bleibt tot.

Hier umschließt nichts irgendwas. Jede Quelle liefert selbst ein, ihre Pakete
landen mit ihrem Namen in der Live-Tabelle, und zusammengeführt wird erst beim
Aufbau des Intervalls — wenn alle Pakete samt Herkunft vorliegen. Damit
verschiebt sich die Frage von „welcher Treiber hat das Sagen" zu „welcher
Quelle glaube ich für *dieses Feld* in *diesem Intervall*".

```toml
# sources.toml
[sources]
outTemp = "garten, dach"     # der Garten ist die Messreihe
"soil*" = "garten"           # nur der Garten hat Bodensonden
"*"     = "dach, garten"     # alles andere: zuerst das Dach
```

Die Regel gilt **je Feld**, nicht je Datensatz — dasselbe Muster wie die Sicht
`messreihe_1d` der Wetterstation Kirchdorf. Eine Station, die Temperatur und
Regen misst, aber keine Schneehöhe messen *kann*, liefert ihre Temperatur und
ihren Regen; die Schneehöhe kommt von dem, der sie hat.

Gemittelt wird über Quellen **nie**. Zwei Thermometer mit 19 °C und 21 °C
ergeben nirgends 20 °C — es sind zwei Messungen zweier Orte, und eine davon zu
nehmen ist die einzige ehrliche Antwort. Wer beide will, gibt der zweiten eine
eigene Spalte.

`tools/multisource.py` prüft genau die drei Fälle, die der Metatreiber nennt.

## Was läuft

| Modul | Zweck |
|---|---|
| `aggregate.py` | Der Kern. Rohwerte rein, Statistik raus. Kein Zustand, keine DB, keine Uhr. |
| `obstypes.py` | Welche Größe wie aggregiert wird. Ohne globalen Zustand, anders als WeeWX. |
| `sources.py` | Welche Quelle für welches Feld gewinnt. |
| `archiver.py` | Archivsätze aus Zeitspannen. Ersetzt `StdArchive`. |
| `db/live.py` | Die Live-Tabelle. Append-only, idempotent, mit Retention. |
| `db/archive.py` | Die WeeWX-Datenbank, lesend und schreibend. |
| `db/schema.py` | Schema-Introspektion. Das Schema kommt aus der Datei, nie aus einer Liste im Code. |
| `ingest/listener.py` | HTTP + UDP, Token, Treiberauswahl. Ein Ort für das, was Push-Treiber falsch machen. |
| `ingest/drivers.py` | Die Treiber-Schnittstelle und ihre Registry. |
| `ingest/envelope.py` | Der JSON-Umschlag — der Vertrag, kein Protokoll. Der einzige Treiber im Kern. |
| `ingest/plugins/ecowitt.py` | Ecowitt, über weewx-ecowitt. |

## Tests

`tools/` ist kein Beiwerk. Die Zusage dieses Projekts ist, dass eine bestehende
Datenbank unverändert bleibt und dieselben Zahlen herauskommen. Diese Dateien
sind der Beleg dafür, und sie laufen gegen eine echte Datenbank statt gegen
ausgedachte Werte.

Alle ohne Netz, ohne Zustand außerhalb eines Temp-Verzeichnisses:

```bash
python tools/difftest.py reference/weewx.sdb     # die Arithmetik
python tools/roundtrip.py reference/weewx.sdb    # das Schreiben
python tools/smoke.py                             # alles zusammen
python tools/multisource.py                       # mehrere Stationen
python tools/driverinstall.py                     # Fremdtreiber
python tools/adminpage.py                         # die Einstellungsseite
python tools/settings_test.py                     # die Rangfolge der Quellen
python tools/netaccess_test.py                    # wer geantwortet wird
python tools/ratelimit_test.py                    # die zwei Grenzen
python tools/export_test.py                       # FTP und rsync
python tools/web_test.py                          # der lokale Webserver
python tools/derive_test.py                       # die Ableitungen
python tools/feeds_test.py                        # mehrere Feeds nebeneinander
python -m pytest tests/                           # der Ecowitt-Treiber
python -m ruff check --select F src/ tools/       # undefinierte Namen
```

`ruff` ist der einzige Punkt, an dem ein Werkzeug von außen gebraucht wird,
und er verdient seinen Platz: ein Aufruf in einer Schleife, die selten läuft,
wird sonst erst im Betrieb gefunden. Genau so ist es einmal passiert.

Drei vergleichen direkt gegen ein installiertes WeeWX und brauchen es deshalb
im Pfad:

```bash
PYTHONPATH=/pfad/zu/weewx/src:src python3 tools/seriestest.py \
    reference/weewx.sdb Europe/Berlin      # Zeitreihen gegen weewx.xtypes
PYTHONPATH=/pfad/zu/weewx/src:src python3 tools/unitcheck.py   # 147 Umrechnungen
PYTHONPATH=/pfad/zu/weewx/src:src python3 tools/suncheck.py    # Sonnenstand
PYTHONPATH=/pfad/zu/weewx/src:src python3 tools/tagcheck.py     reference/weewx.sdb Europe/Berlin      # die Tags, die ein Skin benutzt
```

`PYTHONPATH` dabei **nicht** exportieren: die Ecowitt-Tests greifen sonst auf
WeeWX' eigene Module zu und schlagen fehl, ohne dass etwas kaputt wäre.

Die Zeitzone bei `seriestest.py` ist kein Beiwerk: die Tagestabellen sind auf
lokale Mitternacht geschlüsselt, und in der falschen Zone gelesen vergleicht man
einen Tag mit einem anderen.

Gemessen, Stand heute:

| | |
|---|---|
| Tagesstatistiken gegen die echte Datenbank | 0 Summenabweichungen |
| Zeitreihen gegen `weewx.xtypes` | 94 Vergleiche, 19 957 Punkte, 0 Fehler |
| Einheiten gegen `weewx.units` | 147 Umrechnungen × 9 Werte, exakt |
| Sonnenaufgang gegen pyephem | 37 s im schlechtesten Fall |
| Template-Tags gegen `weewx.tags` | 82 Ausdrücke, 0 Abweichungen |
| Ecowitt-Treiber | 59 Tests, unverändert übernommen |

### Der Abnahmetest

`difftest.py` baut die Tagesstatistiken einer echten Datenbank neu und
vergleicht sie mit dem, was WeeWX hineingeschrieben hat. Gegen die
Testinstanz (2280 Sätze, 134 Spalten, 132 Tagestabellen):

```
sum mismatches:            0
extremes sharper than DB:  0
extremes duller than DB:   189   (expected: LOOP highs/lows)
```

Zwei Spaltenklassen, zwei Maßstäbe — und der Unterschied ist der Punkt:

- **Summen** (`sum`, `count`, `wsum`, `sumtime`, `xsum`, `ysum`, `dirsumtime`,
  `squaresum`, `wsquaresum`) stammen ausschließlich aus Archivsätzen. Sie
  müssen exakt stimmen. Sie tun es.
- **Extremwerte** dürfen abweichen. Mit `loop_hilo = True` schreibt WeeWX
  LOOP-Pakete direkt in die Tagesextreme, und die sind feiner als jeder
  Archivsatz. Eine Rekonstruktion kann nur gleich oder stumpfer sein — nie
  schärfer. Schärfer wäre ein Fehler, und genau darauf prüft der Test.

`roundtrip.py --packets` speist die gespeicherten LOOP-Pakete wieder ein. Wo
sie den Zeitraum abdecken, sinkt die Zahl entsprechend: 109 → 89 bei 76 %
Abdeckung.

Diese Asymmetrie ist das beste Argument für die Live-Tabelle, und sie ist
messbar. Darunter am 25.08.2026 ein `outTemp`-Minimum von 17,6 °F (−8 °C) und
ein Maximum von 96,8 °F (36 °C), acht Minuten auseinander, spätabends im
August. Beides Müll aus einer Umbauphase — und beides steht dauerhaft in der
Statistik, weil die LOOP-Pakete fort sind. `weectl database rebuild-daily`
würde es entfernen und dabei jedes echte LOOP-Extrem des gesamten Zeitraums
mitnehmen.

## Betrieb

```bash
weewx-evo serve      # Listener + Archiver in einem Prozess
weewx-evo listen     # nur der Listener
weewx-evo archive    # nur der Archiver
weewx-evo catchup    # jedes Intervall bauen, das die Live-Tabelle abdeckt
weewx-evo rebuild <von> <bis>
weewx-evo status
```

Konfiguration über `WEEWX_EVO_*` in der Umgebung oder als Argumente.

### Größe der Live-Tabelle

Gemessen an der Konsole in Kirchdorf, ein Paket alle 8 s: rund 11 MB pro Tag,
also etwa 80 MB bei sieben Tagen Retention. Eine Vantage mit einem LOOP-Paket
alle 2 s ist das Vierfache. Eigene Datei, eigene Retention — die Archiv-DB
bleibt klein und sicherbar.

## Referenzdaten

`reference/` liegt in `.gitignore` — echte Messwerte, mehrere Megabyte. Neu
ziehen:

```bash
HOST=your-weewx-host
ssh $HOST 'docker exec weewx python3 -c "
import sqlite3
for s in [\"weewx.sdb\", \"weewx-loop.sdb\"]:
    c = sqlite3.connect(\"/data/archive/\" + s)
    c.execute(\"VACUUM INTO ?\", (\"/data/snap-\" + s,)); c.close()"'
scp $HOST:/opt/weewx/data/snap-weewx.sdb reference/weewx.sdb
ssh $HOST 'rm -f /opt/weewx/data/snap-*.sdb'
```

`VACUUM INTO` statt `cp`: die Datenbank wird nebenher beschrieben, und ein
kopiertes WAL ist ein zerrissener Zustand.

## Verwandte Arbeit im Original

Die Architektur ist in `D:\Git\weewx` bereits in vier Zweigen erprobt. Sie
sind die Spezifikation für dieses Projekt und sein Referenz-Orakel:

| Zweig | Was er zeigt |
|---|---|
| `core-http-listener` | HTTP/UDP-Listener als Basis aller Push-Treiber, Token-Prüfung an einer Stelle |
| `loop-store` | LOOP-Pakete in eigener Datenbank, NDJSON-Export beim Verlassen der Retention |
| `ingest-table` | Jeder Archivsatz aus der Ingest-Tabelle gerechnet statt aus dem Akkumulator |
| `split-archive-service` | `StdArchive` in Generator und Speicher getrennt |

## Lizenz

GPL v3, und das ist keine freie Wahl. `aggregate.py` und `units.py` sind
Transkriptionen aus WeeWX, Ausdruck für Ausdruck: die Tagesstatistik-Arithmetik
aus `weewx.accum`, die 147 Umrechnungen aus `weewx.units`. Damit ist dieser Code
ein abgeleitetes Werk, und WeeWX steht unter GPL v3.

Das ist Absicht, nicht Notlage. Eine „sauberer" neu gerechnete Umrechnung ist
ein Diagramm, das in der dritten Nachkommastelle von WeeWX abweicht, und die
ganze Zusage dieses Projekts ist, dass es das nicht tut.

WeeWX: Copyright (c) Tom Keffer und Mitwirkende, <https://weewx.com>.

### Mitgeliefert

- [uPlot](https://github.com/leeoniya/uPlot) 1.6.32, MIT, unverändert unter
  `src/weewx_evo/feeds/diagnostic/vendor/`. Der Diagnose-Feed zeichnet damit,
  ohne dass eine Station dafür ins Netz muss.
- [weewx-ecowitt](https://github.com/hilman2/weewx-ecowitt), vollständig
  übernommen als erster Treiber, samt seinen 59 Tests.

Ansonsten nichts. Der Kern kommt mit der Standardbibliothek aus, und pyephem
wird benutzt, wenn es da ist, ohne dass es fehlen darf.
