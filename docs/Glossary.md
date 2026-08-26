# Glossar

Begriffe, wie sie in diesem Projekt gemeint sind. Wo WeeWX einen anderen Namen
für dasselbe hat, steht er dabei.

---

**Accumulator** — `aggregate.Accumulator`. Statistiken für eine Menge von
Messgrößen über **eine** Zeitspanne. Rohwerte rein, ein Archivsatz raus.
Transkription von `weewx.accum`. → [Aggregation](Aggregation)

**Aggregat** — Eine Zahl für eine Spanne: `avg`, `min`, `max`, `sum`, `count`,
`first`, `last`, `rms`, `vecavg`, `vecdir` und die Zeitvarianten davon.
→ [Series](Series)

**Archivsatz** (*archive record*) — Eine Zeile in der `archive`-Tabelle. Deckt
`interval` Minuten ab und ist auf das **Ende** dieser Spanne gestempelt.

**`archive_day_*`** — Die Tagesstatistiken. Eine Tabelle je Messgröße. **Ein
Cache**: alles darin ist aus `archive` ableitbar.
→ [Daily-Summaries](Daily-Summaries)

**Archiver** — Der Dienst, der Archivsätze aus Zeitspannen baut. Ersetzt WeeWX'
`StdArchive`. → [Archiver](Archiver)

**Catch-up** — Jedes Intervall bauen, das die Live-Tabelle abdeckt.
`weewx-evo catchup`.

**Deriver** — Was Taupunkt, Windchill und den Regen-Delta ergänzt. Ersetzt
WeeWX' `StdWXCalculate`. → [Derived-Readings](Derived-Readings)

**`dirsumtime`** — Gewicht, das nur für Windmessungen zählt, die eine Richtung
hatten. Eine Windstille ohne Fahne trägt keine Richtung bei.

**Einheitengruppe** (*unit group*) — `group_temperature`, `group_pressure`,
`group_rain` und so weiter. Welche Einheit eine Gruppe hat, hängt vom System ab.
→ [Units](Units)

**Einheitensystem** — `US` (1), `METRIC` (16), `METRICWX` (17). Steht je Satz in
`usUnits`.

**Export** — **Wie** etwas woandershin kommt: FTP, rsync, eine Kopie. Nimmt ein
Verzeichnis. → [Exports](Exports)

**Feed** — **Was** erzeugt wird: eine CSV, ein JSON-Dokument, eine Webseite, ein
Monatsbericht. Schreibt in ein Verzeichnis. → [Feeds](Feeds)

**Fingerprint** — Größe, Zeitstempel und (bei kleinen Dateien) ein Hash. Womit
ein FTP-Export entscheidet, ob eine Datei schon gesendet wurde.
→ [Exports](Exports#nur-senden-was-sich-geändert-hat)

**Grace** — Wie lange nach Intervallende gewartet wird, bevor der Satz gerechnet
wird. Default 15 s. Damit ein bloß langsames Paket nicht zwei Berechnungen
auslöst.

**Homeless** — Ein Messwert, für den die Archivtabelle keine Spalte hat. Wird
gemeldet, nie stillschweigend angelegt. `weewx-evo columns`.

**Intervall** — Wie viel Zeit ein Archivsatz abdeckt. Default 5 Minuten.
**Halboffen am Anfang**: ein Paket genau auf der Grenze schließt das Intervall,
das dort endet.

**Kanal** (*channel*) — Bei Ecowitt: eine Sensorposition, `ch1` bis `ch8`. Zwei
Konsolen nummerieren beide ab eins — deshalb die Konsolenliste.
→ [Driver-Ecowitt](Driver-Ecowitt)

**Kind** — Zwei Bedeutungen. (1) Der Typ einer Einstellung: `text secret int
float bool choice path duration list`. (2) Die Art eines Pakets: `loop` oder
`archive`.

**Live-Tabelle** — `packet` in `live.sdb`. Jedes Paket, das je ankam, N Tage
lang. Ersetzt WeeWX' In-Memory-Akkumulator.
→ [Database-Live](Database-Live)

**LOOP-Paket** — WeeWX' Name für eine einzelne Messung, im Gegensatz zu einem
Archivsatz. Hier `kind = "loop"`.

**`loop_hilo`** — Ob einzelne Pakete die Tagesextreme setzen dürfen. An by
default, wie WeeWX. Aus gemacht sind die Tagesextreme exakt aus dem Archiv
reproduzierbar.

**Manifest** — `index.json`. Was der JSON-Feed erzeugt hat, damit ein Client
seine Seite anlegen kann, bevor er etwas holt.

**`maxSolarRad`** — Was ein Solarsensor bei wolkenlosem Himmel läse. Ein
gemessener Wert dagegen gehalten sagt, wie bewölkt es war.

**Option** — Eine deklarierte Einstellung. Daraus entstehen Formularfeld,
Validierung, Dateikommentar und `--explain`-Zeile.
→ [Configuration](Configuration)

**Paket** (*packet*) — Eine Messung, wie sie ankam, bevor irgendetwas damit
gemacht wurde. `db.live.Packet`.

**PASSKEY** — Womit Ecowitt-Hardware sich ausweist, abgeleitet aus ihrer
MAC-Adresse. Wird redigiert, bevor irgendetwas gespeichert wird, das jemand
weiterreicht.

**Plot** — Eine Diagramm-**Definition**: ein Name, eine Zeitspanne, und die
Messwerte darin. Gehört weewx-evo, nicht einem Renderer. → [Plots](Plots)

**Policy** — Zwei Bedeutungen. (1) `obstypes.Policy`: wie jede Messgröße
aggregiert wird. (2) `sources.Policy`: welche Quelle für welches Feld gewinnt.

**Provenance** — Welches Feld eines Archivsatzes von welcher Quelle kam.
→ [Multiple-Sources](Multiple-Sources)

**Quelle** (*source*) — Eine Station. Steht an jedem Paket. Mehrere Quellen
werden **beim Bau des Intervalls** zusammengeführt, je Feld.

**Retention** — Wie lange Pakete in der Live-Tabelle bleiben. Default 7 Tage.
Solange sie da sind, ist ein Satz korrigierbar.

**Roundtrip** — Ein Wert, der durch Formular, Datei und zurück geht. Der Ort, an
dem `"5m"` als String zurückkommen kann statt als 300.

**Schema** — Zwei Bedeutungen. (1) `db.schema.Schema`: die Form einer
Archivdatenbank, **aus der Datei gelesen**. (2) `options.Schema`: alles, womit
eine Komponente konfigurierbar ist.

**`skip_if_empty`** — Eine **Zeitspanne**, kein Boolean. Sagt, über welchen
Zeitraum ein Sensor nichts gemeldet haben muss, damit ein Diagramm gar nicht
erst erzeugt wird.

**Span** — Zwei Bedeutungen. (1) Die Gruppe eines Diagramms: `day`, `week`,
`month`, `year`. (2) Eine Zeitspanne allgemein. `time_length` ist, was
tatsächlich entscheidet, wie weit ein Diagramm zurückreicht.

**Spool** — Pakete als gzip-NDJSON wegschreiben, bevor sie die Live-Tabelle
verlassen.

**`sumtime`** — Das Gesamtgewicht in einem Akkumulator. Zusammen mit `wsum`
macht es einen Mittelwert über eine beliebige Periode möglich.

**Target** — `units.Target`. Worin Messwerte **gezeigt** werden, unabhängig
davon, was die Datenbank hält. → [Units](Units)

**Token** — Ein Pfadsegment. Zwei davon: eines für Uploads, eines für die
Einstellungsseite, **nie dasselbe**. → [Security](Security)

**Tracker** — Was ein FTP-Export sich merkt, damit er nicht jedes Mal alles
schickt. → [Exports](Exports)

**Trigger** — Wann ein Export läuft: `feed`, `record`, `interval`, `manual`.
`feed` ist der Default und der richtige.

**`usUnits`** — Die Spalte, die sagt, in welchem Einheitensystem ein Satz steht.

**View** — `Settings.view(prefix, schema)`. Die Ecke der Einstellungen, die einer
Komponente gehört, und sonst nichts. Ein Treiber bekommt das, nicht das Ganze.

**`wsum`** — Die gewichtete Summe: jeder Wert mal der Zeit, die er stand.

**`xsum` / `ysum`** — Ost- und Nordkomponente der summierten Windvektoren. Wie
eine mittlere Richtung eine Mittelung überlebt.

<!-- covers
-->
