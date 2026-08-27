# MQTT

`mqtt.py` und `uploads/mqtt.py`. Ein MQTT-3.1.1-Client aus der
Standardbibliothek, und der Upload, der ihn benutzt.

## Warum das existiert

MQTT ist, wie eine moderne Skin lebendig wird. Belchertown, jas, weewx-wdc und
Weather34 beziehen ihre Live-Updates alle von einem MQTT-Broker über
Websockets. Ohne einen rendern diese Skins vollständig — und stehen dann still,
bis jemand die Seite neu lädt.

Da der [Cheetah-Feed](Feeds) existiert, um genau diese Skins unverändert zu
fahren, ist der Broker keine Zugabe.

## Warum selbst geschrieben

`paho-mqtt` ist die naheliegende Antwort und eine Abhängigkeit, und dieser Kern
läuft auf der Standardbibliothek. Das ist keine Parole: es ist das, was
`pip install weewx-evo` auf einem Raspberry Pi ohne Compiler und ohne Ausnahme
in einer Netzwerk-Policy funktionieren lässt. Eine Bequemlichkeitsbibliothek
ist nicht das, wofür man das ausgibt.

Und der Handel ist kleiner, als er aussieht. MQTT 3.1.1 ist seit 2014
eingefroren, das Drahtformat ist ein Byte-Layout statt einer Aushandlung, und
was eine Wetterstation braucht, ist ein Bruchteil davon.

**Bewusst nicht drin:**

- **QoS 2.** Vier Pakete, um eine Temperatur genau einmal zuzustellen, die in
  fünf Minuten überholt ist. QoS 1 ist, was jede Wetter-Skin benutzt, und
  Dubletten sind harmlos, wenn die Nutzlast ihren eigenen Zeitstempel trägt.
- **Session-Wiederaufnahme.** Jedes Mal eine saubere Sitzung. Was
  wiederaufzunehmen wäre, steht im Archiv, und das ist der bessere Speicher.
- **MQTT 5.** Nichts hier braucht seine Properties, und Broker sprechen 3.1.1
  in jeder Installation, der eine Station begegnet.

Was ernst genommen wird, ist das **Wiederverbinden**. Eine
Haushaltsverbindung bricht ab, ein Broker startet neu, ein Container wird
umgeplant — und ein Client, der beim ersten davon aufgibt, ist schlimmer als
gar kein MQTT: die Skin zeigt weiter, was zum Zeitpunkt des Abbruchs galt.

## Zwei Fallen, beide vom Test gefunden

**Ein QoS-1-Publish muss auf sein *eigenes* PUBACK warten.** Ein Client, der
das nächste eintreffende Paket für die Bestätigung hält, besteht jeden
einfachen Test — und bricht in dem Moment, in dem jemand zusätzlich
abonniert, weil dann eingehende PUBLISH-Pakete dazwischenkommen. Der Testbroker
schiebt deshalb absichtlich eines ein.

**Bricht die Verbindung beim Lesen ab, merkt es nur das Lesen.** `_write` kann
es nicht: in einen Socket zu senden, dessen Gegenstelle geschlossen hat,
gelingt in den Kernel-Puffer und meldet nichts. Ohne das Aufräumen an der
Lesestelle glaubt der Client, verbunden zu sein, jeder spätere Publish
verschwindet, und das Log bleibt still.

## Die Topics gehören nicht uns

Das Layout ist das von `matthewwall/weewx-mqtt`, denn dagegen sind diese Skins
geschrieben, und das ist es, was acht Jahre Installationsanleitungen den Leuten
zu konfigurieren sagen.

Also übernommen statt verbessert:

- Das Standard-Topic ist `weather`, und jede Messung geht nach
  `weather/<name>`.
- Namen tragen ein Einheiten-Suffix — `outTemp_C`, `windSpeed_mph` — aus einer
  Reduktionstabelle, in der `degree_compass`, `percent` und `uv_index`
  absichtlich nackt bleiben.
- Derselbe Satz geht zusätzlich als ein JSON-Dokument nach `weather/loop`, weil
  ein Browser mit einem Abonnement billiger ist als mit vierzig.

Beides gleichzeitig ist dort der Standard und hier auch. Eine Skin benutzt das
eine oder das andere, und niemand muss herausfinden welches.

**Retained, standardmäßig.** Eine retained Nachricht wird einem Browser in dem
Moment übergeben, in dem er abonniert — die Seite zeigt also sofort die
aktuellen Bedingungen statt eines leeren Dashboards bis zum nächsten
Archivsatz. Ohne das sieht eine Skin nach jedem Laden bis zu fünf Minuten
kaputt aus, und das ist die häufigste Beschwerde über MQTT-Wetter-Dashboards
überhaupt.

## Live statt alle fünf Minuten

Ein Archivsatz ist ein Fünf-Minuten-Mittel, das fünf Minuten zu spät kommt. Ein
Dashboard, das eines zeigt, ist vier Minuten und neunundfünfzig Sekunden lang
veraltet.

Deshalb hat der MQTT-Upload als einziger den Auslöser `live`: er liest die
[Live-Tabelle](Database-Live) alle paar Sekunden und veröffentlicht, was neu
ist.

Gelesen wird aus der Datenbank statt über einen Rückruf vom Listener — genau
das lässt Listener und Archiver getrennte Prozesse bleiben. Ein Live-Kanal,
der nur funktioniert, wenn beide ein Prozess sind, würde das still aufheben.

In einer geteilten Installation, in der dieser Prozess das Archiv hat und ein
anderer die Pakete, fällt der Upload auf den Archivsatz zurück: spät statt
gar nicht.

## Home Assistant

`uploads/homeassistant.py`. Home Assistant nimmt MQTT-Topics von selbst auf —
aber nur, wenn ihm gesagt wird, was sie sind: ein retained JSON-Dokument je
Messung, auf einem Topic unter `homeassistant/`.

Das einmal veröffentlicht, und die Station erscheint als Gerät mit benannten,
grafisch dargestellten und einheitenbewussten Sensoren. Kein YAML, kein
Neustart, nichts doppelt getippt.

Zwei Entscheidungen:

- **Immer retained**, was auch immer `retain` für die Messwerte sagt. Eine
  Discovery-Nachricht, die niemand behalten hat, sieht nur ein Home Assistant,
  der in genau der Sekunde lief.
- **Einmal pro Verbindung, nicht pro Messung.** Die Definitionen ändern sich
  zwischen zwei Messungen nicht, und vierzig Dokumente alle zehn Sekunden
  wären der größte Teil des Verkehrs. Nach einem Reconnect gehen sie wieder
  raus, weil ein ohne Persistenz neu gestarteter Broker sie vergessen hat.

Eine falsche `device_class` ist nicht kosmetisch: `pressure` auf einer
Temperatur macht den Verlauf unlesbar, und eine Einheit, die Home Assistant
nicht kennt, macht den Sensor zu einer Zeichenkette ohne Graph. Millibar und
Hektopascal sind dasselbe, und `hPa` ist das, was Home Assistant führt.

Ein Tagesniederschlag wird auf `total_increasing` gesetzt: er springt um
Mitternacht auf null zurück, und als `measurement` läse sich das als negativer
Regen.

## Konfiguration

```toml
[uploads.broker]
kind = "mqtt"
host = "localhost"
topic = "weather"
# Standard: live, alle 10 Sekunden
home_assistant = true
```

## Prüfen

```bash
python tools/mqtt_test.py
```

Ein Broker auf loopback, genug von MQTT 3.1.1, um ehrlich zu antworten. Er ist
absichtlich streng: er lehnt ein SUBSCRIBE ab, dessen feste Flags nicht `0b0010`
sind — ein echter Broker schließt die Verbindung dann ohne Begründung, und das
ist ein langer Nachmittag.

Geprüft wird, was tatsächlich über den Socket geht: das Byte-Layout von
CONNECT, dass ein QoS-1-Publish auf sein eigenes PUBACK wartet, dass ein
abgelehntes Passwort dauerhaft abgelehnt wird, und dass eine abgerissene
Verbindung mit ihren Abonnements zurückkommt.

→ [Uploads](Uploads) · [Live-Datenbank](Database-Live) · [Feeds](Feeds)
