# Plugins

Was nicht im Kern liegt, und wie es trotzdem dazukommt.

Zwei Formen, und welche gilt, hängt davon ab, was das Plugin ist.

## Ein Entry Point — Exports, Uploads, Feeds, Vorhersagequellen

Ein pip-installierbares Paket mit einer Zeile in seiner `pyproject.toml`:

```toml
[project.entry-points."weewx_evo.exports"]
sftp = "weewx_evo_sftp:SftpExport"
```

Mehr ist es nicht. `pip install weewx-evo-sftp`, und danach steht `sftp` in
`weewx-evo export list`, in der Auswahl auf der Einstellungsseite und als
`kind = "sftp"` in der Konfiguration — ohne eine Zeile Änderung an weewx-evo.

Die vier Gruppen:

| Gruppe | Wofür | Schnittstelle |
|---|---|---|
| `weewx_evo.exports` | ein Verzeichnis woandershin | `send(source, files)` |
| `weewx_evo.uploads` | die Messwerte an einen Dienst | `post(records)` |
| `weewx_evo.feeds` | etwas erzeugen | `produce(into)` |
| `weewx_evo.forecast` | was kommt | `fetch(place)` |

Jede Registry liest ihre Gruppe beim ersten Zugriff (`load()`). **Ein Plugin,
das nicht importiert, wird gemeldet und übersprungen** — dieselbe Regel wie
bei den Treibern: eines, das kaputt ist, darf die anderen nicht kosten.

Ein Plugin, das `options()` hat, bekommt sein Formular auf der
Einstellungsseite geschenkt. Es muss dafür nichts tun und die Admin-Seite
nichts über es wissen.

## Ein Verzeichnis — Treiber

Treiber liegen **neben den Daten** statt im Paket, damit ein Upgrade sie nicht
anfasst:

```bash
weewx-evo driver install https://github.com/jemand/weewx-evo-acurite
```

→ [Drivers](Drivers#2-installiert--datenverzeichnisdrivers)

## Warum die zwei Formen verschieden sind

Nicht aus Prinzip, sondern aus einem praktischen Unterschied: ein Treiber
muss ein Upgrade des Pakets überleben und in einem Container das Neuanlegen
des Images. Deshalb liegt er im Datenvolume.

Ein Entry-Point-Plugin liegt in `site-packages` und ist nach einem
`docker compose build` weg. Das ist für eine Installation auf einem Pi ohne
Container kein Problem und für eine im Container eines — siehe unten.

## Was ein Plugin darf, was der Kern nicht darf

**Eine Abhängigkeit nehmen.** Der Kern läuft auf der Standardbibliothek, und
das ist keine Parole: es ist das, was `pip install weewx-evo` auf einem
Raspberry Pi ohne Compiler funktionieren lässt. Ein Plugin hat diese
Verpflichtung nicht — wer `paramiko`, `pillow` oder `numpy` braucht, nimmt es.

`weewx-evo-sftp` tut es trotzdem nicht, und der Grund steht in seiner README:
`cryptography` auf einem Pi ohne passendes Wheel ist eine Rust-Toolchain und
vierzig Minuten. Aber es wäre erlaubt gewesen, und das ist der Punkt.

## Der Katalog

[**weewx-evo-plugins**](https://github.com/hilman2/weewx-evo-plugins). Eine
`plugins.toml`, ein Eintrag je Plugin, jeder zeigt auf dessen eigenes
Repository.

**Ein Repo je Plugin, nicht eins für alle.** Jedes hat eigene Issues, eigene
Releases und einen eigenen Maintainer — und genau das lässt jemanden, der
nicht wir ist, eines am Leben halten.

Der Fehler, den das vermeidet, ist der von `weewx-DWD`: zehn unabhängige Dinge
in einem Paket, wo eine Änderung am Radar-Code die Vorhersage kaputt macht und
wer nur Warnungen will, alles mitinstalliert.

Denselben Fall gibt es hier schon: der Ecowitt-Treiber kam aus
`weewx-ecowitt`, einem eigenen Repo für ein **WeeWX**-Plugin. Weil die beiden
verschiedene Programme sind, wanderte kein Fix mehr sinnvoll hin und her. Der
Treiber ist jetzt Kern, jenes Repo bleibt was es ist.

## Was drin ist

| Plugin | Art | `kind` | Wofür |
|---|---|---|---|
| [weewx-evo-sftp](https://github.com/hilman2/weewx-evo-sftp) | Export | `sftp` | Ein Server mit SSH, aber ohne rsync |

## Aus der Admin-Seite installieren?

Die Frage kommt sofort, wenn es einen kuratierten Katalog gibt, deshalb hier
die Antwort statt in einem Issue.

**Für Treiber: ja, und der Mechanismus steht schon.** Sie liegen im
Datenvolume, überleben ein Update, und `driver install` gibt es. Ein Knopf auf
der Einstellungsseite wäre eine Oberfläche vor etwas Vorhandenem.

**Für Entry-Point-Plugins: noch nicht**, und aus einem konkreten Grund. Sie
gehen nach `site-packages`, und in einem Container ist das nach dem nächsten
`docker compose build` weg. Ein Plugin, das nach einem Update verschwindet,
ist schlimmer als eines, das man von Hand installiert hat: es sieht aus wie
ein Fehler und niemand weiß, wo er herkommt.

**Was dagegen unabhängig von der Form spricht**, und was zuerst beantwortet
sein muss:

- **Der Admin-Token bekäme eine neue Bedeutung.** Heute kann er die
  Konfiguration ändern — schlimmstenfalls das Archiv auf eine andere Datei
  zeigen lassen. Mit einem Installations-Knopf kann er beliebigen Code
  ausführen, als der Nutzer, unter dem der Dienst läuft. Das ist eine andere
  Größenordnung und muss eine bewusste Entscheidung sein, keine Beigabe.
- **„Kuratiert" ist eine Aussage, die der Katalog gerade nicht macht.** Er
  sagt, dass ein Plugin existiert und was es zu tun behauptet. Ein Knopf
  daneben liest sich als Empfehlung. Entweder wird wirklich kuratiert — mit
  dem Aufwand und der Verantwortung — oder der Knopf muss ehrlich beschriftet
  sein.
- **Ein Neustart.** Entry Points werden beim Import gelesen; ein frisch
  installiertes Plugin ist erst danach da. Machbar (`needs_restart()` gibt es),
  aber aus „ein Klick" wird „ein Klick, und dann ist die Station eine Minute
  weg".

**Der Weg, der das auflöst**, ist nicht der Knopf, sondern eine gemeinsame
Ladeschicht: Exports, Uploads und Feeds auch als Verzeichnis im Datenvolume
laden zu können, so wie Treiber es schon werden. Dann überlebt jedes Plugin
ein Update, und ein Installations-Knopf hat für alle dieselbe Bedeutung.

Wenn das steht, bleibt vom Rest nur noch die Token-Frage — und die ist mit
zwei Einstellungen zu beantworten: Installation nur aus dem Katalog, nie aus
einer freien URL, und ein Schalter, der es ganz abschaltet.

→ [Drivers](Drivers) · [Exports](Exports) · [Uploads](Uploads) · [Feeds](Feeds)
