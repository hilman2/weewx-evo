# Listener

`ingest/listener.py`. Der Listener, hinter dem jeder Push-Treiber sitzt.

Ein Prozess nimmt HTTP und UDP an, gibt die Bytes an einen Treiber und schreibt
die zurückkommenden Pakete in die Live-Tabelle. Treiber öffnen keine Sockets,
prüfen keine Tokens und fassen die Datenbank nicht an — das ist der ganze Punkt:
diese drei sind die Stellen, an denen Push-Treiber schiefgehen, und sie einmal
zu machen heißt, sie einmal zu machen.

## `Ingest`

Was der Listener mit einem Upload macht, sobald er einen hat. Getrennt von den
Transporten, damit dasselbe Objekt HTTP, UDP und die Tests bedient — und damit
ein Pull-Treiber direkt dagegen geschrieben werden kann.

```python
ingest = Ingest(store, token="…", default_driver="ecowitt",
                registry=drivers.DEFAULT, access=PRIVATE_ONLY, limits=limits)
stored, reason, response = ingest.submit(body, path, peer)
```

| Methode | Bedeutung |
|---|---|
| `authorised(path)` | Ob ein Pfad das Token trägt |
| `driver_for(path)` | Den Treiber aus dem Pfad wählen |
| `submit(body, path, peer)` | Einen Upload annehmen. Gibt `(gespeicherte Pakete, Grund, Antwort)` |
| `status()` | Zahlen für `/status` |

Die **Antwort kommt vom Treiber**. Was ein Gerät hören muss, ist Teil seines
Protokolls — ein Ecowitt-Gateway erwartet `{"errcode":"0","errmsg":"ok"}` und
wiederholt sonst.

`_redacted()` speichert den Upload, wie er ankam, mit dem, was der Treiber für
geheim hält, entfernt. **Redaktion ist Protokollwissen**: nur der Treiber weiß,
dass Ecowitts `PASSKEY` die Station identifiziert.

## Die Pfade

Der Treiber wird aus dem Pfad gewählt:

```
POST /<token>/               → der Default-Treiber
POST /<token>/ecowitt/       → dieser Treiber
POST /<token>/json/          → der Umschlag-Treiber
GET  /<token>/?ID=…&…        → Wunderground-Protokoll, Messwerte im Query-String
```

Diagnose, alles hinter dem Token:

| Pfad | Was |
|---|---|
| `GET /<token>/live` | Die Statusseite |
| `GET /<token>/` | Dasselbe |
| `GET /<token>/status` | JSON: Zähler, Treiber, Grenzen |
| `GET /<token>/recent` | JSON: die letzten Pakete, für die Seite |
| `GET /` (ohne Token) | `weewx-evo`, sonst nichts |

Die Diagnoseseiten sitzen auf dem Upload-Pfad, weil dieser Pfad das Einzige ist,
was Fremde draußen hält — eine Seite, die zeigt, was eine Station misst, soll
nicht leichter erreichbar sein als der Endpunkt, der es aufzeichnet.

## Warum das Token im Pfad steht

Hardware kann keine Header senden. Eine Ecowitt-Konsole hat ein Feld für Host,
Port und Pfad — mehr nicht. Also ist ein Pfad, den niemand erraten kann, die
praktische Antwort.

Damit ist das Token **erratbar** im Sinne von: jemand kann es versuchen. Deshalb
die enge Grenze auf Fehlversuche. → [Security](Security)

## Grenzen des Kerns

| | |
|---|---|
| `MAX_BODY` | 1 MiB. Mehr wird nicht gelesen |
| `MAX_RAW` | 8 KiB. So viel vom Rohupload wird aufbewahrt |

## Die Transporte

### `HttpListener`

`ThreadingHTTPServer`. Eine langsame Konsole darf die anderen nicht blockieren.

```python
listener = HttpListener(ingest, host="0.0.0.0", port=8000)
listener.start()      # Thread
listener.stop()
```

### `UdpListener`

Für Hardware, die broadcastet statt zu posten.

```python
UdpListener(ingest, host="0.0.0.0", port=8001, driver="json")
```

Ein Datagramm trägt keinen Pfad, also gibt es kein Token darin: **der Port
selbst ist die Zugangskontrolle**, und der Treiber ist fest eingestellt. `0`
schaltet es ab, und das ist der Default.

### `push()`

```python
push(packets, host="127.0.0.1", port=8000, token="…")
```

So liefert ein **Pull**-Treiber ab. Über Loopback zu gehen statt direkt in die
Datenbank zu schreiben, ist Absicht: es kostet eine Millisekunde und kauft
Prozessisolierung. Ein Treiber, der sich aufhängt, hängt sich in seinem eigenen
Prozess auf.

## Reihenfolge der Prüfungen

```
1. _permitted()   Ist der Peer in einem Netz, das wir überhaupt beantworten?
                  Nein → 404. Nicht "falsches Netz": das würde verraten,
                  dass es hier etwas gibt.
2. Rate-Limit     Zu viele Anfragen → 429 mit Retry-After.
3. _has_token()   Falsches Token → 404 und ein Fehlversuch verbucht.
4. driver_for()   Treiber wählen.
5. driver.packets(body, meta)
6. store.add_all(packets)
```

**Prüfen kostet nichts, nur ein echter Fehlversuch zahlt.** `_has_token()` prüft
und zählt an **einer** Stelle. Das war vorher getrennt — `submit` zählte ein
falsches Token, die Seiten nicht — und `tools/ratelimit_test.py` hält es jetzt
fest. Ohne diese Trennung hätte sich eine Konsole nach fünf **gültigen** Uploads
selbst ausgesperrt.

→ [Security](Security)

## Die Statusseite

`ingest/statuspage.py`. Eine Seite, die zeigt, was gerade ankommt.

Sie existiert für genau eine Frage, die man beim Aufbau immer wieder stellt:
*kommt was an?* Sie sonst zu beantworten heißt SSH, `docker exec` und eine
handgeschriebene SQL-Abfrage.

| | |
|---|---|
| `recent(store, ingest, limit=12)` | Die letzten Pakete und wie es läuft |
| `render(title)` | Die Seite. Eine Datei, keine Abhängigkeiten |
| `short_source(source)` | Quellnamen auf 8 Zeichen kürzen |

`HEADLINE` legt fest, was oben groß steht: Außentemperatur, Feuchte, Barometer,
Wind, Regen.

## Konfiguration

→ [Settings-Reference](Settings-Reference#listener)

```bash
weewx-evo listen --port 8000 --token … --driver ecowitt \
                 --allow private --rate 10
```

<!-- covers
src/weewx_evo/ingest/listener.py
src/weewx_evo/ingest/statuspage.py
tools/ratelimit_test.py
tools/netaccess_test.py
-->
