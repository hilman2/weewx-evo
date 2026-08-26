# Sicherheit

`netaccess.py`, `ratelimit.py`, und die Token-Politik.

> **So einfach wie möglich, so sicher wie nötig.**

Die übliche Anlage steht im Heimnetz: eine kleine Maschine in einem Schuppen
oder Schrank, eine Konsole im selben WLAN, und jemand, der von einem Laptop in
der Küche in die Einstellungen sehen will. Daraus folgt alles.

## Wer eine Antwort bekommt

`netaccess.py`.

**Gebunden auf `0.0.0.0`, geantwortet nur privaten Netzen.**

Auf localhost zu binden macht den Laptop in der Küche zu einem SSH-Tunnel — eine
Sache zu viel zum Erklären. Auf alles zu binden und das Beste zu hoffen ist, wie
eine Konfigurationsseite auf Shodan landet.

```python
PRIVATE = ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12",
           "192.168.0.0/16", "169.254.0.0/16", "::1/128", "fc00::/7", "fe80::/10")
LOOPBACK = ("127.0.0.0/8", "::1/128")
```

Ein **Reverse Proxy verbindet immer von loopback** oder aus dem Docker-Bridge-
Netz, beides privat — er funktioniert also von selbst, ohne dass irgendetwas
geöffnet werden muss. Das ist der Grund, warum dieser Default trägt.

```python
class Access:
    @classmethod
    def parse(cls, setting: str | None) -> Access: ...
    def allows(self, address: str) -> bool: ...
```

| Wert | Bedeutung |
|---|---|
| `private` | Der Default. Die Netze oben |
| `any` | Alles, einschließlich des offenen Internets |
| `10.0.0.0/8, 203.0.113.4` | Eine Liste aus Netzen und Einzeladressen |

**Loopback wird immer hinzugefügt**, egal was dasteht: sich selbst von der
eigenen Maschine auszusperren ist kein Sicherheitsgewinn.

`PRIVATE_ONLY` und `EVERYONE` sind die zwei fertigen Instanzen.

`warn_if_open(access, what)` sagt beim Start **einmal**, wenn ein Dienst dem
ganzen Internet antwortet. Das offene Internet ist eine bewusste Entscheidung
(`--allow any`), und eine bewusste Entscheidung verdient eine Zeile im Log.

### Warum 404 und nicht 403

Ein Peer aus einem Netz, das nicht beantwortet wird, bekommt **404** — dasselbe
wie ein falsches Token.

„Falsches Netz" zu sagen würde bestätigen, dass es hier etwas gibt.

## Zwei Tokens, zwei Ports

| | Kann | Port |
|---|---|---|
| Upload-Token | Schlimmstenfalls einen falschen Messwert schreiben | 8000 |
| Admin-Token | Das Archiv auf eine andere Datei zeigen lassen | 8080 |

**Gleicher Token für beides wird verweigert.**

### Warum das Token im Pfad steht

Hardware kann keine Header senden. Eine Ecowitt-Konsole hat ein Feld für Host,
Port und Pfad. Also ist ein Pfad, den niemand erraten kann, die praktische
Antwort.

Das macht das Token **versuchbar** — es steht in Logs von Proxies, in
Browser-Verläufen, in Referrern. Daher die zweite, enge Grenze.

## Die zwei Grenzen

`ratelimit.py`. Zwei Limits, weil es zwei verschiedene Dinge gibt, vor denen man
Angst haben muss, und eine Zahl nicht beiden dient.

| | Default | Warum |
|---|---|---|
| **Anfragen, die funktionieren** | 10/s je Adresse | Eine Konsole lädt alle acht Sekunden hoch; eine Vantage sendet alle zwei Sekunden ein LOOP-Paket. Selbst eine Station mit mehreren Konsolen und ein Treiber, der nach einem Ausfall aufholt, bleibt unter einer je Sekunde. Zehn ist Luft nach oben |
| **Falsche Tokens** | 5/min je Adresse | Das ist die wirksame Grenze. Der Token steht im Pfad und ist damit erratbar |

Die zweite ist die, die etwas tut. Die erste fängt nur ab, was schiefgegangen
ist.

### Prüfen kostet nichts, nur ein echter Fehlversuch zahlt

Das ist die Regel, die den Unterschied macht.

```python
limits.has_attempts_left(address)   # fragt, ohne zu zahlen
limits.failed(address)              # das hier zahlt
limits.succeeded(address)           # ein richtiger Token: Fehlversuche vergessen
```

**Das war ein Fehler und ist jetzt ein Test** (`tools/ratelimit_test.py`): sonst
hätte sich eine Konsole nach fünf **gültigen** Uploads selbst ausgesperrt.

Der Grund war, dass die Prüfung an zwei Stellen stand — `submit` zählte ein
falsches Token, die Diagnoseseiten nicht. Jetzt macht `_has_token()` beides an
einer Stelle.

### Die Antworten

| Situation | Antwort | Warum |
|---|---|---|
| Falsches Token | **404**, immer | „Zu viele Versuche" zu sagen würde bestätigen, dass es etwas zu versuchen gibt |
| Falsches Netz | **404** | Dasselbe |
| Zu viele Anfragen | **429** mit `Retry-After` | Das ist ein **echter Client**, dem gesagt wird, langsamer zu machen |

Der Kommentar im Code sagt es kurz: `# 429 here, not 404: this one is a real
client being told to slow down`.

### Wie es gebaut ist

```python
class Bucket:
    """Token-Bucket: Tokens wachsen mit `rate` bis `burst`, jede Anfrage kostet eines."""
```

Diese Form ist hier richtig: eine Konsole, die offline war und ihren Rückstand
postet, darf einen Stoß machen, ohne abgewiesen zu werden.

```python
class Limiter:
    def __init__(self, rate, burst=None, capacity=4096, name="requests"): ...
```

**`capacity` ist wichtig.** Ein Eintrag je Adresse ist in einem Heimnetz
belanglos und in einem öffentlichen ein Weg, einer Maschine den Speicher
auszugehen. Die ältesten Einträge fallen, wenn die Tabelle voll ist.

```python
class Limits:
    """Was ein Dienst benutzt: ein Limit für Anfragen, ein engeres für Fehlversuche."""
```

`announce(limits, what)` sagt beim Start, was begrenzt wird — und was nicht.

### Hinter einem Reverse Proxy

`behind_proxy = true` schaltet das Ratelimit ab.

Dann kommt jede Anfrage von der Adresse des Proxys, und eine Grenze je Adresse
würde **alle außer dem Verursacher** ausbremsen. Das Limitieren bleibt beim
Proxy, der als Einziger die echte Adresse kennt.

## Ein Treiber im Prozess

**Nicht einsperrbar.** Ein Treiber ist Python im selben Interpreter,
`import sqlite3` genügt, und keine Schnittstelle hindert Code daran, sie zu
umgehen. WeeWX hat dieselbe Eigenschaft.

Die Zwischenschicht ist ein **Vertrag, kein Käfig**: ein Treiber bekommt einen
`state` mit `get`/`set`/`delete` auf Strings, nicht den `ArchiveStore`. Damit ist
das Richtige einfach und das Falsche eine sichtbare, absichtliche Handlung.

Durchgesetzt wird außerhalb des Prozesses:

| Mittel | Wirkung |
|---|---|
| `listen` und `archive` getrennt (`deploy/split.yml`) | Der Listener öffnet das Archiv nie. Ein Treiber darin **hat die Datei nicht** |
| Eigener Benutzer ohne Schreibrecht aufs Archiv | Macht die Frage gegenstandslos |
| `driver install` liest den Code | Meldet `sqlite3`, `subprocess`, `socket`. Ein Hinweis, keine Garantie |

→ [Drivers](Drivers), [Deployment](Deployment)

## Der Container

`deploy/split.yml` setzt zusätzlich:

```yaml
read_only: true
tmpfs: [/tmp]
security_opt: [no-new-privileges:true]
cap_drop: [ALL]
```

Und der Prozess läuft als unprivilegierter Benutzer (`Dockerfile`, uid 1001).
Er ist durch Caddy vom Internet erreichbar und hat keinen Grund, die Dateien zu
besitzen, die er schreibt, über das Schreiben hinaus.

## Traversal

Der Web-Server prüft, dass ein aufgelöster Pfad **innerhalb** des
Feed-Verzeichnisses liegt. Das Verzeichnis eines Feeds wird aus einem Template
geschrieben, und ein Template, das man dazu bringen kann, `../../etc` zu
schreiben, ist eines, das irgendwann jemand versehentlich schreibt.
→ [Web-Server](Web-Server)

## Was redigiert wird

Ein Rohupload wird eine Weile aufbewahrt, damit man ihn an ein Issue hängen
kann. **Redaktion ist Protokollwissen** — nur der Treiber weiß, was in seinem
Protokoll ein Geheimnis ist:

```python
SECRETS = ("PASSKEY", "ID", "PASSWORD", "key", "stationkey")   # ecowitt
```

Der PASSKEY identifiziert eine Ecowitt-Station und ist, was jemand bräuchte, um
ihre Messwerte zu fälschen. Alles andere in einem Ecowitt-Upload sind Messwerte.

Auch die Admin-Seite gibt ein `secret` **nie** zurück: sie zeigt, *ob* eines
gesetzt ist. Ein Token, das einmal angezeigt wurde, ist ein Token in einem
Screenshot.

## Prüfen

```bash
python tools/netaccess_test.py    # wer geantwortet wird
python tools/ratelimit_test.py    # die zwei Grenzen
python tools/web_test.py          # die Verzeichnisgrenze
```

`netaccess_test.py` treibt die Server mit einem Socket, dessen Quelladresse
tatsächlich anders ist — **eine Peer-Adresse lässt sich über TCP nicht fälschen**,
also ist das echt prüfbar und nicht gemockt.

<!-- covers
src/weewx_evo/netaccess.py
src/weewx_evo/ratelimit.py
-->
