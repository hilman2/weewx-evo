# Plan

Was nach dem heutigen Stand im Kern fehlt, in der Reihenfolge, in der es
gebaut werden sollte. Jeder Schritt nennt seine Dateien, seinen
Einhängepunkt, seine Entscheidungen, seine Fallen und seinen Test.

**Das Prinzip der Reihenfolge:** zuerst, was heute Messwerte kostet. Dann,
was andere Arbeit erst möglich macht. Dann Breite.

---

## Offene Entscheidungen

Drei Dinge fallen vor der ersten Zeile. Jede steht hier mit Empfehlung; wo
die Empfehlung gilt, ist sie im Plan schon eingearbeitet.

### E1 — Wo QC und Kalibrierung sitzen

**Empfehlung: im Archiver, nicht im Listener.**

Die Live-Tabelle behält den Rohwert, `build()` wendet die Regeln an. Damit
ist ein zu eng gesetzter Grenzwert für die Dauer der Retention reparabel:
Regel ändern, `rebuild`, und Archiv samt Tagesstatistiken folgen. Im Listener
angewandt wäre der Rohwert weg und der Fehlgriff endgültig.

Der Docstring von `archiver.py` sagt es schon, bevor es das Modul gibt:

> A record can be corrected. Fix the packets or the calibration, rebuild the
> span, and the archive and its daily summaries follow.

**Der Preis:** die Live-Anzeige zeigt den Rohwert. Ein Sensor mit leerer
Batterie steht mit −40 °C auf der Seite, während das Archiv sauber ist.
Deshalb ist QC eine Funktion mit zwei Aufrufern, nicht ein Schritt im
Archiver — siehe 1.1.

### E2 — Der Datenweg für Grafana

**Empfehlung: SQLite direkt, aber die Query-Erzeugung austauschbar.**

SQLite kostet nichts und funktioniert sofort. InfluxDB ist ab vier Konsolen
oder mehreren Maschinen deutlich besser (Station als Tag statt als
Datasource, keine Dateirechte, Sekundenauflösung dauerhaft) und steht
deshalb als 3.3 im Plan.

Was den Wechsel billig hält: **die Dashboards werden nicht zweimal gebaut.**
Panel-Definition, Titel, Einheiten, Achsen und Nachkommastellen kommen aus
`plots.toml` und `units`; verschieden ist allein die Query. Also
`grafana/query_sqlite.py` neben einem späteren `grafana/query_influx.py`,
und der Wechsel ist ein Provisioning-Lauf.

**Offen:** wie viele Konsolen, auf wie vielen Maschinen. Bei vier oder mehr
rückt 3.3 in Phase 2.

### E3 — Wer alarmiert

**Empfehlung: Betriebs-Alarme im Kern, Wetter-Alarme in Grafana.**

Grafana Alerting kann Schwellwerte und Kanäle. Aber „Station schweigt seit
sechs Stunden" dort zu bauen hieße, unsere Betriebslogik in Queries zu
duplizieren — und der Alarm fällt aus, wenn Grafana ausfällt. Ein Frostalarm
darf das, ein „nichts wird mehr aufgezeichnet" nicht.

---

## Phase 1 — betreibbar machen

Die drei Lücken, die heute Messwerte oder Schlaf kosten.

### 1.1 `quality.py` — Grenzwerte, Sprünge, Kalibrierung

`weewxconf.py` sagt es beim Import selbst: für `StdCalibrate` und `StdQC`
gibt es hier nichts. Bei einer Konsole ist das ein Schönheitsfehler, bei
zehn der Grund, warum das Archiv nach einem Jahr Müll enthält. Ein Sensor
mit leerer Batterie meldet −40 °C, ein verstopfter Regensensor 300 mm/h beim
Freispülen, ein Funksensor am Rand der Reichweite fünfzehn Minuten lang
denselben Wert. Alles drei landet heute in `archive` — und `archive` ist
genau das, was **nicht** neu gebaut werden kann.

- [ ] `src/weewx_evo/quality.py` — `Rule` je Feld: `minimum`, `maximum`,
      `spike` (Δ je Minute), `stuck` (n gleiche Werte), `offset`, `scale`.
      `apply(data, rules, history) -> (data, verdicts)`
- [ ] `quality.toml` neben `stations.toml` und `sources.toml`. **Nicht** in
      `evo.toml`: das sind viele gleichartige Sätze, dieselbe Begründung wie
      bei `plots.toml`
- [ ] Einhängepunkt A: `archiver.build()`, zwischen `source_merge` und
      `deriver.apply` (`archiver.py:114`–`124`)
- [ ] Einhängepunkt B: die Live-Leser — Live-Seite, `uploads/webpush.py`,
      `uploads/mqtt.py`. Sonst zeigt die Seite −40 °C, während das Archiv
      sauber ist
- [ ] `adminquality.py` — eine Zeile je Feld, **mit dem gemessenen
      Wertebereich der letzten 30 Tage daneben**. Ohne den rät man Grenzen
- [ ] `weewx-evo quality check` (was würde verworfen), `quality suggest`
      (Grenzen aus der Historie vorschlagen)

**Entscheidungen:**

- **Erst kalibrieren, dann prüfen.** Andersherum prüft man den
  unkalibrierten Wert gegen kalibrierte Grenzen, und ein Thermometer mit
  0,4 K Versatz fällt an seiner eigenen Obergrenze durch.
- **Ein verworfener Wert ist weg, nicht null.** Null ist eine Messung. Ein
  auf null gesetzter Regenwert ist von echter Trockenheit nicht mehr zu
  unterscheiden — derselbe Fehler, den `uploads/ambient.py` im Docstring
  schon beschreibt.
- **Gezählt und berichtet.** Wie bei den unbeantworteten Tags im
  Cheetah-Feed: stilles Verwerfen ist ein Fehler, der wie ein Sensordefekt
  aussieht.

**Fallen:**

- **Regen ist kumulativ.** Ein Spike-Filter auf `rain` wirft echten
  Starkregen weg. Zählerfelder bekommen per Default keinen.
- **Stuck-Erkennung braucht die Auflösung des Sensors.** Ein Thermometer mit
  0,1 K Auflösung steht in einer ruhigen Nacht zwanzig Minuten still. Das ist
  kein Defekt, und eine Regel ohne diese Zahl meldet jede Nacht.
- **Der Rohwert bleibt bis `forget_raw`.** Bis dahin ist jeder Fehlgriff
  durch `rebuild` reparabel — danach nicht mehr. Das gehört auf die Seite.

**Test:** `tools/quality_test.py` — Pakete mit allen vier Fehlerarten säen,
Satz bauen, prüfen: verworfen, gezählt, Rohwert noch in der Live-Tabelle, und
ein `rebuild` nach Regeländerung liefert ein anderes Ergebnis.

**Größe:** ~400 Zeilen Kern, ~250 Admin-Seite, ~250 Test.

---

### 1.2 `notify/` — der Kern sagt niemandem etwas

Gegrept: kein SMTP, kein Webhook, kein ntfy, nirgends. Der Watchdog startet
den Prozess neu und **sagt es niemandem**. Eine Station, die seit sechs
Stunden schweigt, steht auf einer Seite, die niemand aufmacht.

- [ ] `src/weewx_evo/notify/__init__.py` — Registry im Muster von
      `uploads/__init__.py` (`register_factory`, `kinds()`, Entry-Points)
- [ ] `notify/smtp.py`, `notify/webhook.py` (deckt ntfy, Gotify, Slack,
      Discord, Telegram über URL + Template ab), `notify/mqtt.py` auf dem
      vorhandenen Client
- [ ] `notify/rules.py` — die Ereignisse, **Liste geschlossen und nur
      Betrieb**: Station schweigt · Batterie leer · Export oder Upload
      scheitert seit n Läufen · Watchdog hat neu gestartet, und warum ·
      Deskriptoren oder Platte nahe am Limit · Archiver-Herzschlag steht
- [ ] `notify/runner.py` — eigener Thread, Muster von `exports/runner.py`,
      mit `replace()`; eingehängt in `cli.py` neben den anderen Runnern und
      an `start_watchdog` übergeben (`cli.py:727`, `cli.py:1218`)
- [ ] Zustand in `live_metadata`, wie `exports/record.py` — die
      Einstellungsseite ist ein anderer Prozess

**Entscheidungen:**

- **Nur Betrieb, keine Wetter-Alarme.** Siehe E3. Ein Schwellwert für Frost
  ist Geschmack und gehört dorthin, wo man ihn ohne Deploy ändert.
- **Keine Historie in der Live-Tabelle.** Wie der letzte Lauf ging, ist die
  Frage; das Log hat die Geschichte. Dieselbe Regel wie bei
  `exports/record.py`.

**Fallen:**

- **Flapping.** Ein Grenzwert bei 0,0 °C und eine Temperatur, die um Null
  pendelt, sind vierzig Mails pro Nacht. Hysterese, Mindestabstand, „erst
  nach n Prüfungen" — **und jeder Alarm hat ein Ende**, sonst weiß niemand,
  ob er noch anliegt.
- **Der Kanal, der mit ausfällt.** „Internet weg" per E-Mail über dasselbe
  Internet ist keine Benachrichtigung. Die Seite muss zwei Kanäle empfehlen,
  und ein Alarm, der nicht rausging, wird gemerkt und nachgeholt.
- **Der Watchdog-Alarm muss vor dem Neustart raus.** Ein Prozess, der sich
  beendet, schickt keine Mail mehr. `watchdog.py` merkt sich den Zeitpunkt
  ohnehin zuerst — die Meldung gehört zwischen Merken und Handeln.

**Test:** `tools/notify_test.py` — SMTP gegen einen lokalen Socket, Webhook
gegen `http.server`, und das Flapping messen: eine um den Grenzwert pendelnde
Reihe darf genau einen Alarm und ein Ende erzeugen.

**Größe:** ~500 Zeilen Kern, ~200 Admin-Seite, ~300 Test.

---

### 1.3 `maintenance.py` — Backup, Integrität, Wartung

Fünfzehn Jahre Messwerte in einer Datei, und `weewx-evo backup` gibt es
nicht. Kein `integrity_check`, kein VACUUM, keine Prüfung von `archive`
gegen `archive_day_*` (WeeWX hat dafür `wee_database --check`).

- [ ] `src/weewx_evo/maintenance.py`
- [ ] `weewx-evo backup [--keep n]` — SQLite `.backup`-API, **nie `cp`**
- [ ] `weewx-evo verify` — `PRAGMA integrity_check`, plus `archive` gegen
      `archive_day_*` über `rebuild_day`, ohne zu schreiben
- [ ] `weewx-evo vacuum`, `weewx-evo prune`
- [ ] Optional auf einem Zeitplan über `schedule.py`, auf dem Raster der
      Stunde

**Fallen:**

- **`cp weewx.sdb` bei aktivem WAL ist ein kaputtes Backup, und man merkt es
  erst beim Zurückspielen.** Das ist der ganze Grund, warum das ein Kommando
  ist und keine Zeile in der Doku: der Nutzer, der klug genug ist, ein Backup
  zu machen, macht hier sonst das Falsche.
- **`integrity_check` auf fünfzehn Jahren dauert.** Nicht im
  Archiver-Thread.
- **Geprüft wird das Backup, nicht das Original.** Ein Backup, das niemand
  geöffnet hat, ist eine Vermutung.

**Test:** `tools/backup_test.py` — während des Backups schreiben,
zurückspielen, und auf der Kopie den Prüfweg von `tools/stillweewx_test.py`
laufen lassen.

**Größe:** ~300 Zeilen, ~200 Test.

---

## Phase 2 — öffnen

### 2.1 `api.py` — die Abfrage-API

Heute ist jede Ausgabe eine Datei. Ein Client mit einer Frage, die kein Plot
beantwortet, hat keinen Weg: Home Assistant nicht, eine App nicht, ein Skript
nicht — und Grafana über Infinity auch nicht. `series.py` kann das alles
schon; es fehlt der Endpunkt.

- [ ] `src/weewx_evo/api.py`, bedient vom `webserver.py`
- [ ] `GET /api/v1/archives`, `/stations`, `/fields`, `/current`, `/series`,
      `/aggregate`
- [ ] Read-only. Token im Header **und** im Pfad — Konsolen können keine
      Header, Skripte wollen keinen Token in der URL
- [ ] Einheiten als Parameter (`units=metric|us|metricwx`, oder je Gruppe)

**Entscheidung:** **nutzt `series.py`, keine zweite Arithmetik.** Das ist der
ganze Punkt — sonst ist es der Fehler aus `chartdata.py` noch einmal.

**Falle:** eine unbegrenzte Spanne ist ein OOM. Punktzahl begrenzen und
`every` erzwingen, statt zu hoffen.

**Test:** `tools/api_test.py` — jede Antwort gegen einen direkten Aufruf von
`series.py` vergleichen.

**Größe:** ~350 Zeilen, ~250 Test.

---

### 2.2 `metrics.py` — `/metrics` für den Prozess

Der Watchdog misst schon alles; es liegt nur in der Live-Tabelle statt auf
einem Endpunkt.

- [ ] `src/weewx_evo/metrics.py` — Prometheus-Textformat, keine Abhängigkeit
- [ ] Deskriptoren, Threads, Herzschlag-Alter, Pakete je Minute und Station,
      letzter Archivsatz, Export-Erfolg und -Dauer, Feed-Dauer, Größe der
      Live-Tabelle

**Entscheidung:** **keine Wetterwerte.** Kein Backfill, keine Jahre,
rate-basiert — Prometheus bekommt den Prozess, Grafana bekommt das Wetter aus
dem Archiv. Steht als Begründung ins Modul, weil die Frage wiederkommt.

**Test:** `tools/metrics_test.py` — Format gegen die Grammatik, und jede Zahl
gegen ihre Quelle.

**Größe:** ~150 Zeilen, ~150 Test.

---

### 2.3 `grafana/` — Provisioning erzeugen, nicht malen

Kein handgemaltes Dashboard ins Repo: das ist bei der ersten Zusatzspalte
falsch. Stattdessen erzeugt aus `archives.toml`, `stations.toml`,
`plots.toml`, dem Schema und `units.all_groups()`.

- [ ] `src/weewx_evo/grafana/__init__.py`, `datasources.py`, `dashboards.py`,
      `panels.py`, `query_sqlite.py`
- [ ] `weewx-evo grafana provision --out /data/grafana`
- [ ] `datasources/` — eine je Archiv, plus die Live-Tabelle
- [ ] `dashboards/` — Übersicht aller Stationen, Station-Detail, Betrieb,
      Sensorzustand (Batterie, Signal, Lücken) — plus **ein Panel je Plot**
      aus `plots.toml`
- [ ] `${station}` als Datasource-Variable, damit ein Dashboard für n
      Konsolen reicht

**Die Entscheidung, die alles trägt:** **Grafana darf nicht anders rechnen
als unsere eigene Seite.** Das ist wörtlich der Fehler, den `chartdata.py`
bei WeeWX beschreibt — zwei Generatoren, dieselbe Zahl, dritte
Nachkommastelle auseinander, und niemand findet es, weil jeder für sich
richtig ist. Nur sieht man ihn hier **nebeneinander auf einem Bildschirm.**
Also folgt das erzeugte SQL der Gewichtung aus `aggregate.py`, und wo das
nicht geht, geht es auf `archive_day_*`.

**Fallen:**

- **Die Einheiten stehen nicht in der Datenbank.** Eine Fahrenheit-Konsole
  liefert 68.2 und die Achse sagt °C — derselbe Fehler wie zweimal beim
  Livepush. Jedes Panel bekommt `unit` und `decimals` aus `units`, und wo die
  Konsole in einem anderen System schreibt, rechnet das SQL um.
- **`archive_day_*` ist der schnelle Weg, und Grafana kennt ihn nicht.** Ein
  Jahr Tagesmaxima sind 365 Zeilen über den Primärschlüssel statt eines Full
  Scan über 105.000. Bei einer Konsole egal, bei zehn nicht.
- **WAL, read-only Mount und UID 472.** Ein Reader ohne Schreibrecht am
  Verzeichnis sieht einen alten Stand oder gar nichts. **Muss gemessen
  werden, nicht angenommen** — das ist die Sorte Problem, die zwei Abende
  kostet, und es muss im Compose-Test auffallen und nicht im Betrieb.

**Test:** `tools/grafana_test.py` — jedes erzeugte JSON gegen Grafanas
Schema, und **jede erzeugte Query gegen die Datenbank ausführen und mit
`series.py` vergleichen**. Ohne den zweiten Teil prüft der Test Syntax statt
Zahlen.

**Größe:** ~600 Zeilen, ~350 Test.

---

### 2.4 `deploy/compose.grafana.yml` — als Overlay

- [ ] `GF_INSTALL_PLUGINS=frser-sqlite-datasource`, Provisioning gemountet,
      Archive read-only
- [ ] anonymer Lesezugang als Option (Wandanzeige im Flur)
- [ ] `docker compose -f compose.yml -f compose.grafana.yml up -d`

**Entscheidung: Overlay, nicht Ersatz.** Wer Grafana nicht will, gibt keine
300 MB dafür her. Das `mem_limit: 256m` im bestehenden Compose steht mit
genau dieser Begründung dort.

**Größe:** ~80 Zeilen, plus ein Abschnitt in `docs/Deployment.md`.

---

## Phase 3 — Breite

### 3.1 MQTT als Treiber

Wir haben einen vollständigen MQTT-Client, er kann `subscribe`, und wir
benutzen ihn nur zum Senden. Ein MQTT-**Treiber** öffnet auf einen Schlag
Zigbee2MQTT, ESPHome, Home Assistant und jeden selbstgebauten Sensor — der
häufigste Fall für „noch ein Sensor dazu", und die Rollen-Mechanik
(`outTemp` → `extraTemp3`) ist dafür schon gebaut.

- [ ] `ingest/plugins/mqtt/` — Topic-Muster auf Feldnamen, `unit_groups()`
- [ ] Falle: ein Broker ist ein **Sammler**, kein Parser. Eigener Thread, und
      er darf hängen, ohne den Listener mitzunehmen.

### 3.2 Import

`adopt.py` deckt weewx.sdb ab, kostenlos, weil es dieselbe Datei ist. Der
eigene Docstring benennt die andere Hälfte.

- [ ] `dumps.py` — MySQL und Postgres
- [ ] `weewx-evo import csv`, WU-History
- [ ] Falle: ein Import schreibt in `archive` und muss danach die
      Tagesstatistiken neu bauen, sonst ist der Cache älter als die Daten.

### 3.3 `uploads/influx.py`

Line Protocol über `http.client`, keine Abhängigkeit. Das Interface passt
schon: `post(records)`, oldest first, mit Merkliste — Backfill ist geschenkt,
`upload run --since 2010` schiebt fünfzehn Jahre nach.

**Was es bringt** (und warum es ab vier Konsolen nach vorn rückt):

| | |
|---|---|
| Station ist ein **Tag**, keine Datasource | eine Query, n Linien, eine neue Konsole erscheint von selbst |
| mehrere Maschinen, ein Grafana | bei SQLite müsste jede Datei erreichbar sein |
| Sekundenauflösung bleibt | die Live-Tabelle vergisst nach N Tagen, für immer |
| keine Dateirechte, kein WAL | Netzwerkdienst statt Mount |

**Was es kostet:** eine zweite Datenhaltung ist eine zweite Wahrheit. Ein
`rebuild` nach einer QC-Korrektur muss die Senke mitziehen, sonst zeigt
Grafana etwas anderes als die eigene Seite — und es braucht eine
Abgleichprüfung, die sagt, wo Punkte fehlen. Dazu 512 MB bis 1 GB RAM und
Influx' eigene Brüche (1.x → 2.x → 3.x, InfluxQL → Flux → SQL), was für ein
Projekt mit dieser Prämisse keine Kleinigkeit ist.

- [ ] `uploads/influx.py`, `grafana/query_influx.py`
- [ ] `rebuild` zieht die Senke mit
- [ ] `weewx-evo upload check --compare` — Punktzahl hier gegen dort

### 3.4 Mehrere Archive in einem Diagramm

`archives.py` gibt n unabhängige Reihen; nichts kann „outTemp aller fünf
Standorte auf einer Achse". Bei 1-n Konsolen ist genau das die Frage — und
sie gehört in `series.py` und `chartdata.py`, damit die **eigene** Seite es
auch kann und nicht nur Grafana.

---

## In jedem Schritt gleich

- [ ] Eine Einstellung geht ins Schema, sonst nirgends — `options.py` für den
      Kern, `options()` am Plugin. Daraus entstehen Formular, Validierung,
      Dateikommentar und `--explain` von selbst
- [ ] `ruff check src/ tools/ tests/` **vor** dem Commit; der Hook blockiert
- [ ] Ein Werkzeug in `tools/`, eingetragen in `tools/runtests.py` und damit
      im Docker-Lauf
- [ ] Eine Seite in `docs/`, verlinkt in `docs/Home.md` und `_Sidebar.md`
- [ ] Der Abschnitt in `CLAUDE.md` — mit den Fallen, nicht mit der
      Funktionsbeschreibung

---

## Nicht gebaut, mit Begründung

| | |
|---|---|
| Wetter-Alarme im Kern | Grafana kann es, und ein Schwellwert ist Geschmack. Siehe E3 |
| Radar, Satellit, Pollen | Plugin-Sache; steht schon so im Docstring von `forecast/` |
| Ein Settings-Dienst | die Datei **ist** schon, was ein Daemon wäre, ohne dessen Ausfallarten |
| Zeitzone je Archiv | `archive_day_*` ist auf lokale Mitternacht geschlüsselt — das wäre eine Änderung an der Arithmetik. Offene Frage in `docs/Stations-and-Archives.md` |
| MQTT-Broker mitliefern | war gebaut, ist wieder raus, weil es an Zertifikaten bricht |
| Views in die Archivdatei | die eine Regel: WeeWX muss die Datei weiterbenutzen können. Additive Schemaobjekte sind ein Risiko für nichts |
| Ein Grafana-Render-Feed | Panels als PNG über Grafanas Render-API, per FTP hoch. Braucht einen Chromium-Container, um Bilder von Diagrammen zu veröffentlichen, die Deck aus denselben Daten schon zeichnet. Grafana ist das Cockpit, Deck die Seite. |
