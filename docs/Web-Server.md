# Web-Server

`webserver.py`. Ausliefern, was die Feeds erzeugt haben.

Ein [Feed](Feeds) schreibt ein Verzeichnis voller Dateien. Irgendetwas muss sie
einem Browser geben, und auf einer Station im Schuppen sollte dieses Etwas nicht
nginx sein müssen.

Das ist die kleine lokale Antwort. Wer einen richtigen Web-Server will, stellt
einen davor — oder benutzt einen [Export](Exports) und lässt woanders
ausliefern.

**Was ausgeliefert wird, kommt hier nicht direkt vom Feed.** Ein `local`-Export
legt es hin; dieser Server gibt es aus. Der Umweg ist Absicht: ein Feed schreibt
sein Verzeichnis neu, während er läuft, und ein Browser, der mittendrin lädt,
bekäme eine halbe Seite. → [Exports](Exports#ein-verzeichnis-auf-dieser-maschine)

## Die Routen

```
/                was es gibt — oder eines davon, wenn es der Default ist
/<name>/         dieses Verzeichnis
/<name>/…        alles darunter
```

Mit `web.default` gesetzt ist `/` dieses eine, und die anderen bleiben unter
`/<name>/`.

## Woher die Namen kommen

**Aus den `local`-Exports.** Ein Export namens `site`, der nach `data/site`
veröffentlicht, erscheint unter `/site/`.

Das ist die ganze Konfiguration: man sagt, wo ein Export etwas hinlegt, und von
dort wird es ausgeliefert. **Niemand muss denselben Pfad zweimal aufschreiben.**

```toml
[exports.site]
kind = "local"
directory = "data/site"
source = "json"
```

→ `/site/`

`[web.serve]` benennt zusätzlich Verzeichnisse direkt — für etwas, das dieses
System nicht erzeugt hat: eine handgeschriebene Seite, ein Verzeichnis, das ein
anderes Programm füllt.

```toml
[web.serve]
alt = "/var/www/handgemacht"
```

Direkt Benanntes wird **zuletzt** eingetragen und schlägt damit einen Export
gleichen Namens. Wer einen Pfad aufgeschrieben hat, meinte ihn.

## `Site`

```python
site = Site(feeds={"site": Path("data/site")},
            default="site", title="weewx-evo")
```

| Methode | Bedeutung |
|---|---|
| `resolve(feed, rest)` | Die Datei für eine Anfrage, oder `None` |

`site_from(settings, feeds=None)` baut sie aus der Konfiguration.
`index_page(site)` ist die Liste, wenn keines der Default ist.

`options.published_names()` ist dieselbe Liste für das Formular der Admin-Seite:
die `local`-Exports plus das direkt Benannte. **Die Exports zu lesen statt der
Feeds ist der Unterschied zwischen anbieten, was es gibt, und anbieten, was es
geben könnte.**

### Die Prüfung, auf die es ankommt

Die letzte in `resolve()`: **der aufgelöste Pfad muss innerhalb des
Feed-Verzeichnisses liegen.**

`..` in einer URL, ein Symlink, der hinausführt, ein Template, das seinen
Ausgabepfad aus etwas zusammensetzt, das jemand tippen kann — das Verzeichnis
eines Feeds wird aus einem Template geschrieben, und ein Template, das man dazu
bringen kann, `../../etc` zu schreiben, ist eines, das irgendwann jemand
versehentlich schreibt.

`tools/web_test.py` versucht genau das.

## Caching

```python
INDEXES = ("index.html", "index.htm")
CACHE_SECONDS = {".css": 3600, ".js": 3600,
                 ".woff": 86400, ".woff2": 86400, ".ttf": 86400,
                 ".ico": 86400, ".svg": 3600}
```

HTML und JSON bekommen **kein** Caching: das sind die Dateien, deren Zweck es
ist, sich zu ändern.

## `WebServer`

```python
server = WebServer(site, host="0.0.0.0", port=8081,
                   access=PRIVATE_ONLY, limits=limits)
server.start()
server.stop()
```

Wie die anderen beiden Dienste: gebunden auf alles, geantwortet nur privaten
Netzen, mit demselben Ratelimit. → [Security](Security)

**Kein Token.** Eine Wetterseite ist kein Geheimnis. Was sie schützt, ist die
Netzgrenze — und die Tatsache, dass diese Maschine sonst niemandem antwortet.

## Betrieb

```bash
weewx-evo web --config evo.toml --port 8081
```

Oder als Teil von `serve`, wenn `web.enabled` gesetzt ist. Getrennt aus
demselben Grund wie `listen`: eine Maschine, die nur die Seiten zeigt, muss
nicht die sein, die sie aufzeichnet.

## Einstellungen

→ [Settings-Reference](Settings-Reference#website)

| | |
|---|---|
| `web.enabled` | Ob er in `serve` mitläuft |
| `web.port` | Default 8081, eigener Port |
| `web.default` | Was unter `/` liegt. Die Auswahl kommt aus `published_names()` |
| `web.allow` | Wer eine Antwort bekommt |
| `web.host` | |
| `[web.serve]` | Namen, die direkt auf Verzeichnisse zeigen |

## Prüfen

```bash
python tools/web_test.py
```

Zwei Dinge werden geprüft: das Routing — Feeds unter `/<name>/`, einer optional
unter `/` — und **die Grenze**, was der Teil ist, auf den es ankäme, wenn er
falsch wäre.

<!-- covers
src/weewx_evo/webserver.py
tools/web_test.py
-->
