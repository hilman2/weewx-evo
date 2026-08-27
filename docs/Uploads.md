# Uploads

`uploads/`. Wie die Messwerte selbst zu einem Wetterdienst kommen.

Ein [Export](Exports) verschiebt **Dateien** — ein Feed hat ein Verzeichnis
geschrieben, und irgendetwas muss es auf einen Webhost bringen. Ein Upload
verschiebt **Messwerte**: ein Archivsatz, umgeformt in das, was Weather
Underground oder Windy oder ein APRS-Gateway will, und abgeschickt. Kein
Verzeichnis ist daran beteiligt, und deshalb ist es kein Export mit einer
seltsamen Quelle.

Bei WeeWX steht das als `StdRESTful` im Kern, und hier gehört es auch dahin:
Zu Weather Underground hochzuladen ist keine Erweiterung für eine Wetterstation,
sondern der halbe Grund, eine zu betreiben. Eine Erweiterung ist der zehnte
Dienst; die Form hier ist so gebaut, dass der zehnte vierzig Zeilen sind.

Sieben gibt es: `wunderground`, `pwsweather`, `wow`, `windy`, `weathercloud`,
`cwop` und `mqtt`.

## Die Schnittstelle

```python
class Upload(Protocol):
    def post(self, records: list[dict]) -> Posted:
        ...
```

`records` ist **älteste zuerst**. Meist ist es einer — das Intervall, das
gerade geschlossen hat. Es ist eine Liste, weil eine Verbindung, die zehn
Minuten weg war, beim Zurückkommen zwei Möglichkeiten hat: den neuesten Wert
senden und so tun, als hätte es die anderen nie gegeben, oder alle senden.

Weather Underground, PWSweather und WOW nehmen einen Zeitstempel mit der
Messung entgegen und akzeptieren die verpassten Sätze. Das zur Sache des
Aufrufers zu machen statt jedes Dienstes bedeutet: der Dienst, der nicht
nachreichen kann, sagt es einmal mit `backfill = False` und bekommt nur den
letzten.

## Woher die Sätze kommen

**Nicht durchgereicht — selbst gelesen.** Ein Upload bekommt nichts übergeben;
er liest das Archiv, von dort, wo er zuletzt war. Das ist dieselbe Regel wie
im Rest des Systems: die Komponenten reden über die Datenbank und nicht
miteinander. Es bringt zwei Dinge, die anders schwer zu bekommen sind:

- **Ein Neustart kostet nichts.** Der Upload weiß, wo er war, weil die Zahl
  auf der Platte steht — nicht weil ein Prozess sich etwas gemerkt hat.
- **Eine Verbindung, die zwanzig Minuten weg war**, kommt zurück und sendet
  die zwanzig Minuten statt des aktuellen Werts und eines Lochs.

Der Fortschritt steht in `uploads.json` neben dem Archiv. Es ist ein Cache: die
Datei zu verlieren kostet einen doppelten Post, und jeder Dienst hier
überschreibt einen Zeitstempel, den er schon hat.

```python
progress.through("wu")   # der neueste Satz, den WU angenommen hat
```

## Wann ein Upload läuft

| | |
|---|---|
| `record` | nach jedem Archivsatz — der Standard und fast immer richtig |
| `live` | alle paar Sekunden, aus der Live-Tabelle. Nur MQTT bietet es an |
| `interval` | eigener Takt, für einen Dienst der seltener will (CWOP) |
| `manual` | nur auf `weewx-evo upload run` |

**Jeder Upload läuft in einem eigenen Thread**, aus demselben Grund wie die
Exports: ein Dienst, der nicht mehr antwortet, sitzt in seinem eigenen Timeout
statt im Tick des Archivers. Weather Underground ist ab und zu eine Stunde weg,
und ein Archivintervall, das deshalb zu spät kommt, ist unser Fehler.

## Ein falsches Passwort wird einmal gesagt

Diese Dienste beantworten ein falsches Passwort mit einem fröhlichen HTTP 200
und dem Wort `INVALIDPASSWORDID` im Body. Der Statuscode entscheidet also
nichts, und der Body muss gelesen werden.

Ein `Rejected(permanent=True)` schaltet den Upload ab und schreibt **eine**
Zeile ins Log. Die Alternative ist dieselbe Zeile alle fünf Minuten, ein Jahr
lang — und so hört ein Log auf, gelesen zu werden.

Deshalb hat jeder Upload ein `check()`, und die Admin-Seite einen Knopf dafür:

```bash
weewx-evo upload check
weewx-evo upload check wu
```

## Einheiten

**`units.py`, an einer Stelle.** Jeder dieser Dienste schreibt seine Einheiten
vor und keiner stimmt mit dem nächsten überein: Weather Underground will
Fahrenheit und Zoll Quecksilbersäule, Windy Celsius und Meter pro Sekunde, APRS
Fahrenheit und Hundertstel Zoll. Das Archiv hält, was die Station geschrieben
hat.

Die Umrechnung passiert in `Readings`, einmal, gegen dieselbe Tabelle wie alles
andere. Das war WeeWX' Fehler bei den zwei Diagramm-Generatoren: beide für sich
richtig, in der dritten Nachkommastelle uneins, und niemand findet es.

## Ein fehlender Wert ist fehlend, nie null

Eine Station ohne Regenmesser, die alle fünf Minuten `rainin=0.00` sendet, ist
von einer in einer Dürre nicht zu unterscheiden — und Weather Underground
behält es für immer. `query()` lässt weg, was `None` ist, und deshalb kommt
jede Messung als `None` zurück statt als Default.

CWOP kann das nicht: das Paket ist positionell, ein fehlender Wert sind Punkte
derselben Breite. Beides wird befolgt, statt eines davon zu wählen.

## Die Dienste

### Ambient: Weather Underground, PWSweather, WOW

Weather Underground hat das Protokoll definiert, die anderen haben es
abgeschrieben — bis auf die Parameternamen. Deshalb ein Modul mit drei Hosts
statt drei fast gleicher Dateien.

Die Formate sind aus `weewx.restx.AmbientThread` übernommen, Feld für Feld,
**samt den Breiten**: `humidity=061` und `windspeedmph=003.1` sind das, was das
Protokoll definiert, und die führenden Nullen sind keine Zierde. Das hat der
Test gefunden (`tools/upload_test.py`), nicht das Lesen.

WOW benennt beide Zugangsdaten um (`siteid`, `siteAuthenticationKey`) und
antwortet auf ein falsches Passwort mit HTTP 403 statt mit einem Wort im Body.
Sonst identisch.

### Windy

Der einzige hier, der nicht Ambient spricht: JSON im Body eines POST, metrisch,
und der Schlüssel steht im Pfad statt in einem Parameter.

**Der Druck ist in Pascal.** Nicht Hektopascal, was jeder andere Dienst und
jedes Barometer benutzt. `101325`, nicht `1013.25`. Den Hektopascal-Wert zu
senden wird angenommen und als Vakuum gezeichnet.

Windy nimmt mehrere Beobachtungen in einer Anfrage, also ist ein Nachreichen
eine Anfrage statt zwölf.

### Weathercloud

Metrisch, und jeder Wert ist eine ganze Zahl in Zehnteln: 21,4 °C geht als
`214`. Kein Zeitstempel im Protokoll, also kein Nachreichen — ein älterer Satz
würde als aktuelle Bedingung veröffentlicht.

### CWOP

Kein HTTP. Ein TCP-Socket, eine Login-Zeile und eine Zeile ASCII im
TNC2-Paketformat, das der Amateurfunk seit den Neunzigern benutzt:

```
DW1234>APZEVO,TCPIP*:/271530z4823.15N/01142.30E_245/007g016t074r006p013P010b10128h61L512.weewx-evo
```

Jedes Feld hat feste Breite, jedes fehlende Feld sind Punkte derselben Breite,
und das Ganze ist positionell. Eine falsche Breite erzeugt keinen Fehler,
sondern eine Messung an der falschen Stelle — still, für immer.

Der Paketbauer ist deshalb aus `weewx.restx.CWOPThread` Zeichen für Zeichen
übernommen, inklusive `h00` für 100 % Feuchte und der zwei verschiedenen
Buchstaben für Sonnenstrahlung über und unter 1000 W/m². Das sind keine
Marotten zum Aufräumen, das ist das Protokoll.

Der Test vergleicht das Paket mit dem, das WeeWX aus demselben Satz baut —
Zeichen für Zeichen.

Zwei Entscheidungen:

- **Zehn Minuten, nicht fünf.** CWOP bittet um einen Bericht alle fünf bis zehn
  Minuten und meint es. Der Standard ist zehn, auf eigenem Takt statt auf dem
  Archivsatz.
- **`APZEVO` als Tocall.** `APWEE5` ist WeeWX zugewiesen und nicht unserer.
  `APZ...` ist der Bereich, den die APRS-Spezifikation für Software ohne
  registrierte Kennung vorsieht.

CWOP braucht Breite und Länge — das Paket **ist** ein Positionsbericht. Sie
werden aus den Stationseinstellungen ergänzt, damit niemand sie zweimal tippt.

### MQTT

Eigene Seite: [MQTT](MQTT).

## Konfiguration

```toml
[uploads.wu]
kind = "wunderground"
station = "IBAYERN123"
password = "..."

[uploads.windy]
kind = "windy"
api_key = "..."

[uploads.cwop]
kind = "cwop"
station = "DW1234"
# Breite und Länge kommen aus [station], wenn hier nichts steht
```

Zwei Konten beim selben Dienst sind zwei Uploads mit verschiedenen Namen.

## Kommandos

```bash
weewx-evo upload list             # was es gibt und was konfiguriert ist
weewx-evo upload check            # fragt die Dienste, sendet nichts
weewx-evo upload run              # jetzt senden
weewx-evo upload run wu --again   # vergessen, wie weit es kam
```

## Prüfen

```bash
python tools/upload_test.py
```

Ohne Netz. Jede Prüfung baut eine Anfrage und sieht sie an. Mit WeeWX auf dem
Pfad vergleicht sie zusätzlich die Ambient-Query und das CWOP-Paket
parameterweise mit dem, was WeeWX aus demselben Satz baut:

```bash
wsl -d Ubuntu -- bash -lc 'source ~/venvs/weewx/bin/activate && \
  cd /mnt/d/Git/weewx-evo && PYTHONPATH=/mnt/d/Git/weewx/src:src \
  python3 tools/upload_test.py'
```

→ [Exports](Exports) · [MQTT](MQTT) · [Feeds](Feeds)
