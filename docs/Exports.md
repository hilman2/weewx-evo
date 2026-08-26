# Exports

`exports/`. Wie das, was ein Feed erzeugt hat, woandershin kommt.

Ein [Feed](Feeds) schreibt Dateien in ein Verzeichnis. Ein Export nimmt dieses
Verzeichnis und bringt es dorthin, wo Leute es sehen — ein Webhost über FTP, ein
Server über rsync, ein Verzeichnis auf dieser Maschine.

**Das Verzeichnis ist die ganze Schnittstelle**: ein Export weiß nicht, was die
Dateien erzeugt hat, und ein Feed weiß nicht, wohin sie gehen.

Drei gibt es: [`local`](#ein-verzeichnis-auf-dieser-maschine), [`ftp`](#ftp-und-ftps)
und [`rsync`](#rsync-über-ssh).

## Die Schnittstelle

```python
class Export(Protocol):
    def send(self, source: Path, files: list[Path] | None = None) -> Sent:
        ...
```

`files` ist, was sich geändert hat, wenn der Aufrufer es weiß. `None` heißt: aus
dem Verzeichnis erarbeiten.

**Zu werfen bedeutet: nichts wurde gesendet.**

### `BaseExport`

Nur `send` muss geschrieben werden.

| Methode | Bedeutung |
|---|---|
| `send(source, files)` | |
| `check()` | Das Ziel probieren und sagen, was passiert ist, ohne zu senden |
| `status()` | |
| `close()` | Optional |
| `options()` | Die Einstellungen |

`check()` ist der Knopf auf der Admin-Seite. Ein falsches Passwort oder einen
falschen Pfad sofort zurückzubekommen ist sehr viel wert — die Alternative ist,
fünf Minuten auf das nächste Intervall zu warten und dann in ein Log zu sehen.

### `Sent`

```python
@dataclass
class Sent:
    sent: int
    skipped: int
    deleted: int
    bytes: int
    seconds: float
    failures: list[tuple[str, str]]
    note: str
```

`ok()` und `summary()` für die Statusseite und das Log.

`ExportError` ist etwas, das einen Export gestoppt hat, **bevor er etwas
gesendet hat**.

## Die Registry

Dieselbe Form wie die Treiber-Registry, aus demselben Grund: ein Export hält
Konfiguration und ein wenig Zustand — was er schon geschickt hat — und das muss
zwischen den Läufen überleben.

| Methode | Bedeutung |
|---|---|
| `register(name, export, replace=False)` | |
| `register_factory(name, factory)` | |
| `configure(name, options)` | |
| `factory_for(kind)` | Die Klasse hinter einer Art, lädt die Registry vorher |
| `get`, `known`, `names` | |
| `kinds()` | Welche Arten es gibt, im Gegensatz zu welche konfiguriert sind |
| `load()` | Holen, was installiert ist. Ein kaputter wird gemeldet, nie fatal |

`factory_for()` ist eine Methode statt eines Zugriffs auf `_factories`, weil der
Zugriff `load()` überspringt — und dann ist noch nichts registriert, was wie
„diese Art gibt es nicht" aussieht.

`ENTRY_POINT_GROUP = "weewx_evo.exports"`.

### `walk(source, files=None)`

Jede zu berücksichtigende Datei, als Pfade relativ zu `source`. Verzeichnisse,
die **nie** hochgeladen werden dürfen, werden hier übersprungen statt in jedem
Export: ein `.git` in einer veröffentlichten Seite ist ein Fehler, den jeder
einmal macht, und einer, der genügt.

### `source_for(settings, feed_directory=None)`

Wo die Dateien eines Exports liegen — aus einem Feed-Namen oder einem schlichten
Verzeichnis. Ein Feed wird gefragt, wo er geschrieben hat; ein Verzeichnis wird
genommen, wie es ist.

## Wann ein Export läuft

`exports/runner.py`. Vier Auslöser:

| | |
|---|---|
| `feed` | wenn **sein** Feed fertig geschrieben hat — der Default, und der richtige |
| `record` | nach jedem Archivsatz, für ein Verzeichnis, das etwas anderes füllt |
| `interval` | eigener Takt (`every`), für ein langsames Ziel |
| `manual` | nur auf `weewx-evo export run` |

**`feed` ist nicht Bequemlichkeit, sondern Reihenfolge.** Hören Feed und Export
beide auf `record`, kann der Export starten, während der Feed noch schreibt —
halbe Seite hochgeladen, sieht aus wie ein kaputtes Template, nicht
reproduzierbar.

Ein Export mit `feed` wartet auf **genau diesen** Feed: zwei Feeds, die zwei
Seiten schreiben, dürfen nicht jeder beide Uploads auslösen.

### `Scheduled`

Ein Export und wann er dran ist.

| | |
|---|---|
| `trigger`, `every` | Vom Export |
| `feed` | Auf welchen er wartet |
| `changed` | Was der Feed gesagt hat, dass er schrieb. Ein Export, der das bekommt, schickt diese Dateien statt das Verzeichnis abzulaufen — schneller, und die einzige Art sicher zu sein, dass eine gerade geschriebene Datei dabei ist |
| `due(now, fired)` | `fired` ist, was gerade passierte: `"record"`, ein Feed-Name oder `""` |
| `run()` | Senden und merken, was passierte. **Wirft nie** |

### `Runner`

**Jeder Export läuft in einem eigenen Thread.** Nicht wegen Geschwindigkeit — es
sind zwei oder drei und sie sind fast immer untätig — sondern damit ein
FTP-Host, der nicht mehr antwortet, nicht 30 Sekunden lang den Archiver
aufhält.

Ein Export kann sich dadurch auch nicht selbst überlappen: der Thread steckt in
`send()` und liest seinen eigenen Auslöser nicht. Was währenddessen feuert, wird
gemerkt und danach **einmal** ausgeführt (`skipped` zählt mit).

| Methode | Bedeutung |
|---|---|
| `record_written()` | Vom Archiver-Thread, kehrt sofort zurück: setzt Flags |
| `feed_produced(feed, files)` | Ein Feed ist fertig. Weckt, was ihn sendet |
| `start()`, `stop()`, `status()` | |

`build(configured, make, source_of)` macht aus Konfiguration, was der Runner
fahren kann. **Was sich nicht bauen lässt, wird gemeldet und ausgelassen.** Ein
falsch konfigurierter Export darf die anderen nicht stoppen, und ganz sicher
nicht die Station: die Messwerte sind der Punkt.

## Nur senden, was sich geändert hat

Das ist der Punkt, an dem ein Export nützlich statt lästig wird.

rsync kann das selbst. **FTP kann es nicht**: das Protokoll hat keinen
verlässlichen Weg zu fragen, wie eine Datei am anderen Ende aussieht. `MDTM` ist
optional, `SIZE` ist im ASCII-Modus optional, und Shared Hosting beantwortet
beide regelmäßig mit etwas Erfundenem.

Also `exports/tracker.py`.

### `Fingerprint`

```python
@dataclass
class Fingerprint:
    size: int
    mtime: int
    digest: str
```

`HASH_UNDER = 256 * 1024` — kleine Dateien werden über ihren **Inhalt**
verglichen, nicht über den Zeitstempel.

Der Fall: Ein Template schreibt `index.html` jeden Lauf mit identischen Bytes
neu. Über den Zeitstempel verglichen ginge die ganze Seite alle fünf Minuten
hoch.

`same_as(other)`: Mit einem Digest entscheidet der allein. Ohne einen — bei
großen Dateien — entscheiden Größe und Zeitstempel.

### `Tracker`

| Methode | Bedeutung |
|---|---|
| `changed(source, files)` | Welche gesendet werden müssen, und wie viele nicht |
| `record(source, relative)` | Notieren, dass diese Datei gesendet wurde, so wie sie jetzt ist |
| `forget(relative)` | |
| `gone(present)` | Was wir gesendet haben und nicht mehr da ist |
| `reset()` | Alles vergessen, der nächste Lauf schickt alles |
| `save()` | Die Aufzeichnung schreiben. Sie zu verlieren kostet **einen** vollen Upload |

**Eine Datei, die sich nicht lesen lässt, gilt als geändert**, nicht als
übersprungen: lieber versuchen und laut scheitern, als still entscheiden, dass
etwas nicht hochgeht.

`gone()` benutzt ein Export, der Dateien am Zielort entfernt. Einer, der das
nicht tut, ignoriert es — **von jemandes Webhost zu löschen ist nichts, womit
man ungefragt anfängt.**

## Ein Verzeichnis auf dieser Maschine

`exports/local.py`. Das dritte Ziel neben FTP und rsync, und das, was die
meisten Stationen tatsächlich wollen: legt hin, was ein Feed erzeugt hat, und
der eingebaute [Web-Server](Web-Server) gibt es einem Browser.

### Warum das ein Export ist und keine Einstellung am Web-Server

Es **war** eine: „liefere dieses Verzeichnis aus". Ein Export ist aus einem
Grund besser: Dann gibt es **eine Stelle**, an der jemand fragt „wo landet
das". Ein Feed schreibt in sein eigenes Arbeitsverzeichnis und weiß nichts vom
Veröffentlichen. Ein Export schickt es zu einem Webhost, ein zweiter legt es
unter die lokale Seite, ein dritter kopiert es auf eine eingehängte Freigabe.
Drei Ziele, eine Idee, eine Seite in den Einstellungen.

### Warum es kopiert und nicht zeigt

Der Web-Server könnte das Verzeichnis des Feeds selbst ausliefern und die Kopie
sparen. Er tut es nicht, aus demselben Grund, aus dem es den FTP-Export gibt:
**ein Feed schreibt sein Verzeichnis neu, während er läuft**, und ein Browser,
der mittendrin lädt, bekommt eine halbe Seite. Was hier landet, ist ein ganzer
Satz Dateien oder der vorherige.

Die Kopie ist billig. Nur Geändertes bewegt sich, beurteilt genau wie bei FTP —
und auf demselben Dateisystem wird ein **Hardlink** statt einer Kopie benutzt,
also kosten hundert veröffentlichte JSON-Dateien hundert Verzeichniseinträge und
keine zweite Kopie von irgendetwas. Wo das Dateisystem nicht linkt, wird von
selbst auf Kopieren zurückgefallen.

| Methode | Bedeutung |
|---|---|
| `send(source, files)` | |
| `_place(source, destination)` | **Eine Datei, atomar.** Daneben geschrieben und hineinbewegt, damit ein Browser, der sie gerade liest, die eine oder die andere Fassung bekommt und nie halb von jeder |
| `_remove(target, tracker, present)` | Löschen, was dieser Export dorthin gebracht hat und der Feed nicht mehr schreibt |
| `check()` | Ob dorthin geschrieben werden kann, und was jetzt dort liegt |

Zwei Dinge, die `send()` verweigert:

- **Kein Verzeichnis gesetzt** → `ExportError`.
- **Das Ziel ist das Quellverzeichnis.** Ein Verzeichnis in sich selbst zu
  veröffentlichen verglich jede Datei mit sich selbst und würde sie dann über
  sich selbst hardlinken. Danach passiert nichts Gutes.

Eine Datei, die sich nicht schreiben lässt, kostet **den Lauf nicht**: sie wird
als Fehlschlag vermerkt, und der Rest wird veröffentlicht. Eine Seite, die nicht
geschrieben werden kann, darf nicht das Veröffentlichen von allem danach kosten.

## FTP und FTPS

`exports/ftp.py`. Shared Hosting gibt einem noch immer FTP und oft nichts
sonst, also existiert das hier und muss am unangenehmen Ende funktionieren:
Server, die mitten im Transfer die Verbindung verlieren, die ein Verzeichnis
nicht anlegen können, das schon existiert, ohne zu fehlern, die `MDTM` mit
Unsinn beantworten, und die eine passive Verbindung von einer anderen Adresse
als Angriff werten.

| Methode | Bedeutung |
|---|---|
| `send(source, files)` | |
| `check()` | Verbinden, ins Zielverzeichnis sehen, berichten |
| `_ensure(connection, remote)` | Ein Verzeichnis und seine Eltern anlegen |
| `_remove(connection, tracker, present)` | Löschen, was wir gesendet haben und nicht mehr erzeugt wird |
| `_put(connection, source, relative)` | |

`_ensure()`: **`MKD` auf ein existierendes Verzeichnis ist auf den meisten
Servern ein Fehler und auf manchen ein Erfolg** — also ist der Fehler das, was
toleriert werden muss, nicht der Erfolg.

`_remove()` löscht **nur Dateien, die dieser Export dorthin gebracht hat**: die
Aufzeichnung sagt, welche das sind, also ist nichts anderes auf dem Konto in
Gefahr.

`TIMEOUT = 30`.

## rsync über SSH

`exports/rsync.py`. Wo FTP gesagt werden muss, was sich geändert hat, arbeitet
rsync es selbst heraus und sendet nur die abweichenden **Teile** der
abweichenden Dateien. Für eine Wetterseite ist das der Unterschied zwischen
einem Upload von Megabyte und einem von Kilobyte.

Es ruft `rsync` auf, statt das Protokoll nachzubauen — und das ist keine
Faulheit: das Delta-Verfahren ist der ganze Wert, und es nachzubauen hieße, es
schlechter nachzubauen.

| Methode | Bedeutung |
|---|---|
| `send(source, files)` | |
| `check()` | Ein Trockenlauf, und was er täte |
| `_command(source, files, dry_run)` | Die Argumentliste. **Nichts geht durch eine Shell** |
| `_read(output)` | Zählen, was rsync sagt, dass es tat |

`_read()` liest `--itemize-changes`: ein führendes `>` heißt übertragen,
`*deleting` heißt entfernt, alles andere ist etwas anderes.

**Es gibt keine Passwortoption.** Ein Passwort müsste von einem Programm getippt
werden, was es in eine Prozessliste oder eine Datei bringt. Public Key in
`authorized_keys`.

`TIMEOUT = 600`.

## Konfiguration

```toml
[exports.site]
kind = "local"
directory = "data/site"
source = "json"
trigger = "feed"
link = true

[exports.webhost]
kind = "ftp"
host = "ftp.example.org"
user = "…"
password = "…"
directory = "/httpdocs"
directory_source = "data/public_html"
trigger = "feed"
source = "json"
tls = true
delete = false
```

→ [Settings-Reference](Settings-Reference#exports)

Auf der Admin-Seite: **einen Export anlegen fragt nur Name und Art.** Alles
andere wird auf der Seite ausgefüllt, die danach erscheint. Nach einem Host und
einem Passwort zu fragen, bevor klar ist, wovon geredet wird, ist ein Formular,
das jemand ausfüllt, ohne zu wissen, was er ausfüllt.
→ [Admin-Page](Admin-Page)

## Kommandos

```bash
weewx-evo export list
weewx-evo export check [name]
weewx-evo export run [name] [--source DIR] [--all]
```

## Prüfen

```bash
python tools/export_test.py
```

Die FTP-Hälfte läuft gegen einen Server **in diesem Prozess**, der Transfer wird
also wirklich geprüft statt gemockt: Dateien landen auf der Platte,
Verzeichnisse entstehen, das Hineinbewegen passiert. `pyftpdlib` ist keine
Abhängigkeit von weewx-evo, dieser Teil wird also ausgelassen, wenn es fehlt,
und der Rest läuft trotzdem.

`local_export()` prüft die Ausfallarten, die FTP nicht hat: ein Hardlink, der
still einen Inode teilt; ein Löschen, das mehr mitnimmt als das, was dieser
Export hingelegt hat; ein Ziel, das das Quellverzeichnis ist. Und danach, dass
der **Web-Server tatsächlich ausliefert, was der Export veröffentlicht hat** —
beide Hälften der Kette in einem Test.

`runner_tests()` prüft, wann welcher Export läuft und **dass einer den anderen
nicht aufhalten kann** — mit einem `FakeExport`, der sich absichtlich Zeit lässt.

→ [Testing](Testing)

<!-- covers
src/weewx_evo/exports/__init__.py
src/weewx_evo/exports/ftp.py
src/weewx_evo/exports/rsync.py
src/weewx_evo/exports/local.py
src/weewx_evo/exports/runner.py
src/weewx_evo/exports/tracker.py
tools/export_test.py
-->
