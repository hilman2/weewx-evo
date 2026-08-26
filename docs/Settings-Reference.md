# Einstellungen A–Z

Alle Einstellungen des Kerns, wie `options.core_options()` sie deklariert. Die
Umgebungsvariable ist immer `WEEWX_EVO_` + Name in Großbuchstaben, Punkte zu
Unterstrichen. → [Configuration](Configuration)

Erzeugte Fassungen derselben Liste:

```bash
weewx-evo config show --defaults    # kommentiertes TOML
weewx-evo serve --explain           # Werte samt Herkunft
```

Legende: **A** = advanced (auf der Admin-Seite hinter einem Schalter),
**R** = restart nötig, **!** = required.

## Station

*Wo die Messwerte herkommen, und wo das ist.*

| Name | Kind | Default | | Bedeutung |
|---|---|---|---|---|
| `station.name` | text | `weewx-evo` | | Auf der Live-Seite und in Berichten |
| `station.latitude` | float | — | | Dezimalgrad, negativ südlich des Äquators. Für Sonnenauf- und -untergang und für die Klarhimmel-Strahlung, gegen die ein Solarsensor gemessen wird |
| `station.longitude` | float | — | | Dezimalgrad, negativ westlich von Greenwich |
| `station.altitude` | float | — | | Meter über NN. Das ist, was Stationsdruck in den Barometerwert verwandelt, den alle vergleichen. Von einer Karte nehmen, nicht von der Konsole: Konsolen stehen meist auf dem, was die Anzeige richtig aussehen ließ |

## Archive

*Wie Messwerte zu dem Bestand werden, der bleibt.*

| Name | Kind | Default | | Bedeutung |
|---|---|---|---|---|
| `interval` | duration | `300` (60–3600) | R | Wie viel Zeit ein Archivsatz abdeckt. Fünf Minuten ist üblich. Eine Änderung stört den vorhandenen Bestand nicht — jeder Satz trägt die Spanne, für die er steht, also mitteln alt und neu korrekt zusammen |
| `grace` | duration | `15` (0–300) | A | Wie lange nach Intervallende gewartet wird, damit ein bloß langsames Paket den Satz nicht zweimal berechnen lässt |
| `loop_hilo` | bool | `true` | A | Einzelne Pakete dürfen die Tagesextreme setzen, nicht nur Archivsätze. An by default, wie WeeWX. Aus gemacht sind Tageshöchst- und -tiefstwerte exakt aus dem Archiv allein reproduzierbar |

## Databases

*Zwei Dateien: der Bestand und die Pakete dahinter.*

| Name | Kind | Default | | Bedeutung |
|---|---|---|---|---|
| `plots_file` | path | `plots.toml` | R | Welche Diagramme es gibt. Eigene Datei statt Abschnitt: es ist eine Liste vieler gleichartiger Sätze, und ein aus einer alten Skin importierter Satz ist etwas, das man diffen können will |
| `archive_db` | path | `data/weewx.sdb` | R | Die WeeWX-Datenbank. Bestehende werden benutzt, wie sie sind — das Schema kommt aus der Datei |
| `live_db` | path | `data/live.sdb` | R | Wo Pakete liegen, bis sie in Sätzen stehen. Eigene Datei, damit Größe und Retention nichts mit dem Archiv zu tun haben |
| `retention` | duration | `604800` (min 3600) | | Wie lange Rohpakete bleiben. Sie sind, was einen Satz reproduzierbar macht: solange sie da sind, lässt sich eine falsche Kalibrierung oder ein verspätetes Paket korrigieren. Sieben Tage sind rund 80 MB bei einem Paket alle acht Sekunden |
| `raw_retention` | duration | `3600` (0–86400) | A | Wie lange der Upload, wie er vom Draht kam, neben dem geparsten Paket liegt. Ein Debugging-Hilfsmittel — das, was man an ein Issue über einen nicht platzierbaren Sensor hängt. `0` behält nichts |
| `spool` | path | — | A | Ein Verzeichnis. Jeder Tag Pakete, der die Live-Tabelle verlässt, wird dort vorher als gzip-NDJSON abgelegt. Leer heißt: einfach fallen lassen |

## Listener

*Der Port, auf den die Hardware hochlädt.*

| Name | Kind | Default | | Bedeutung |
|---|---|---|---|---|
| `host` | text | `0.0.0.0` | A R | Jede Schnittstelle. Einengen, wenn die Maschine in mehr als einem Netz hängt |
| `port` | int | `8000` | R | Unter 1024 braucht root, das dieser Dienst nicht haben sollte |
| `token` | secret | — | ! | Ein Pfadsegment, das jeder Upload tragen muss. Das Einzige zwischen dem offenen Internet und der Messreihe: Hardware kann keinen Header senden, also ist ein nicht erratbarer Pfad die praktische Antwort. Wer es erfährt, kann Messwerte fälschen |
| `driver` | choice | `ecowitt` | | Welcher Treiber einen Upload liest, dessen Pfad keinen nennt. Die Auswahl ist, was installiert ist |
| `udp_port` | int | `0` | A R | Für Hardware, die broadcastet statt zu posten. `0` schaltet ab. Ein Datagramm trägt keinen Pfad, also ist der Port selbst die Zugangskontrolle |

## Who is answered

*Gebunden auf jede Schnittstelle; hier wird entschieden, wer eine Antwort bekommt.*

| Name | Kind | Default | | Bedeutung |
|---|---|---|---|---|
| `allow` | text | `private` | R | `private` = das lokale Netz (Schuppen, Konsole, Laptop in der Küche) und deckt einen Reverse Proxy ab, der immer von einer privaten Adresse verbindet. `any` schließt das offene Internet ein. Oder Netze aufzählen: `10.0.0.0/8, 192.168.1.50`. Loopback wird immer beantwortet |
| `rate` | float | `10.0` | A | Anfragen je Sekunde und Adresse. Eine Konsole sendet im schnellsten Fall eine halbe, das fängt also nur etwas ab, das schiefgegangen ist. Was Token-Raten verhindert, ist die getrennte Grenze für falsche. `0` schaltet ab |
| `behind_proxy` | bool | `false` | A | Dann kommt jede Anfrage von der Proxy-Adresse, und eine Grenze je Adresse würde alle außer dem Verursacher ausbremsen. Das Limitieren bleibt beim Proxy, der als Einziger dazu in der Lage ist |

→ [Security](Security)

## Settings page

*Eigener Port, eigenes Token: sie kann weit mehr als ein Upload.*

| Name | Kind | Default | | Bedeutung |
|---|---|---|---|---|
| `admin.token` | secret | — | | **Nie dasselbe wie das Upload-Token.** Sonst könnte alles, was einen Messwert senden kann, auch ändern, was die Station aufzeichnet. Leer schaltet die Seite ab |
| `admin.port` | int | `8080` | R | |
| `admin.host` | text | `0.0.0.0` | A R | |
| `admin.allow` | text | `private` | | Wie oben, und es lohnt sich, enger zu bleiben. Diese Seite zeigt das Archiv auf Dateien. Von auswärts erreichen, ohne zu öffnen: `ssh -L 8080:localhost:8080 die-station` |
| `admin.rate` | float | `5.0` | A | Speichern sind zwei Anfragen, und durch die Reiter klicken macht mehrere je Sekunde. Eine Grenze, die stört, ist eine, die abgeschaltet wird |

## Website

*Ausliefern, was die Feeds erzeugt haben, auf dieser Maschine.*

| Name | Kind | Default | | Bedeutung |
|---|---|---|---|---|
| `web.enabled` | bool | `false` | R | Ein kleiner Web-Server für das, was die Feeds schreiben. Genug, um die eigenen Seiten im lokalen Netz anzusehen, ohne nginx zu installieren |
| `web.port` | int | `8081` | R | Eigener Port, getrennt von Upload und Einstellungsseite. Die beiden antworten Hardware und einem Betreiber; dieser antwortet Browsern |
| `web.default` | choice | — | | Mit einem gewählten Feed ist `/` dieser Feed und die anderen bleiben unter `/<name>/`. Ohne listet `/` auf, was es gibt |
| `web.allow` | text | `private` | | Wie sonst. Eine Wetterseite ist kein Geheimnis, aber diese Maschine antwortet trotzdem Fremden |
| `web.host` | text | `0.0.0.0` | A R | |

→ [Web-Server](Web-Server)

## Running

*Wo Dinge hinkommen und wie oft sie passieren.*

| Name | Kind | Default | | Bedeutung |
|---|---|---|---|---|
| `table` | text | `archive` | A R | Die Tabelle in der Datenbank. Nur für eine Anlage interessant, die sie umbenannt hat |
| `poll` | duration | `5` (1–300) | A | Wie oft der Archiver nach geschlossenen Intervallen sieht. Die Arbeit ist idempotent und die Grenzen kommen aus den Paketen, also ändert ein verspäteter oder ausgefallener Tick nichts |
| `driver_dir` | path | — | A R | Wo mit `weewx-evo driver install` installierte Treiber liegen. Leer heißt: neben dem Archiv |
| `weewx_conf` | path | — | A | Eine `weewx.conf`, auf die zurückgefallen wird. Gelesen, nie geschrieben. Was hier gesetzt ist, schlägt sie |

## Treiber: ecowitt

Präfix `drivers.ecowitt`. Deklariert in
`ingest/plugins/ecowitt/driver.py::EcowittDriver.options()`.

| Name | Kind | Default | | Bedeutung |
|---|---|---|---|---|
| `passkey` | secret | — | | Der Wert, den die Konsole in jedem Upload zuerst sendet. Hier gesetzt ist die Frage endgültig geklärt. Leer gelassen wird die erste gehörte Konsole adoptiert und in der Datenbank vermerkt — was funktioniert, aber mit der Datenbank verloren geht und die Station danach der Konsole überlässt, die zuerst spricht |
| `model` | text | `Ecowitt` | A | Steht in Logs. Kosmetisch |
| `infer_unknown` | choice | `series` | | `off` = fallen lassen · `series` = übernehmen, wenn sie eine bekannte Serie fortsetzen, den Rest melden · `all` = alles nehmen, was benennbar ist. Ein Messwert in der falschen Spalte lässt sich danach nicht wieder heraustrennen |
| `report_file` | path | `/var/tmp/weewx-evo-ecowitt-report.txt` | | Wohin der erste Upload geschrieben wird, der etwas Unplatzierbares enthält. Die Datei hat den PASSKEY schon entfernt und ist zum Einfügen in ein Issue gedacht. Leer schaltet ab |
| `max_behind` | duration | `3600` | A | Wie alt ein Zeitstempel der Konsole sein darf. Darüber hinaus wird die Ankunftszeit benutzt |
| `max_ahead` | duration | `60` | A | Und wie weit in der Zukunft. Es gibt keine Messwerte aus der Zukunft, das deckt also nur Drift zwischen zwei ungefähr richtigen Uhren ab |

→ [Driver-Ecowitt](Driver-Ecowitt)

## Feed: json

Präfix `feeds.json`. Deklariert in
`feeds/jsongenerator/__init__.py::JSONGenerator.options()`.

| Name | Kind | Default | | Bedeutung |
|---|---|---|---|---|
| `feeds.json.enabled` | bool | `true` | | Aus nur, wenn nichts es liest. Jeder andere Feed, der ein Diagramm zeichnet, tut es |
| `feeds.json.destination` | text | `json` | | Unterhalb des Feed-Ausgabeverzeichnisses. Ein Unterverzeichnis, damit die Daten nicht zwischen den Seiten liegen |
| `feeds.json.manifest` | bool | `true` | | `index.json` schreiben: eine Liste dessen, was es gibt, damit ein Client seine Seite anlegen kann, bevor er etwas holt — und nie nach einem Sensor fragt, den die Station nicht hat |
| `feeds.json.rewrite_unchanged` | bool | `false` | | Ein Jahr Tagesmittel sagt um zehn nach dasselbe wie um zehn. Bleibt das aus, wird eine inhaltsgleiche Datei nicht angefasst — was zählt, wenn ein Export alles Geänderte sendet, über eine Leitung, die jemand nach Megabyte bezahlt |
| `feeds.json.rounding` | int | `3` (0–9) | | Drei ist bereits feiner als jeder Wettersensor und nimmt rund ein Drittel der Dateigröße |
| `feeds.json.indent` | int | `0` (0–8) | A | `0` schreibt so klein wie möglich. `2` macht sie lesbar, während man herausfindet, warum ein Diagramm falsch aussieht |
| `feeds.json.spans` | list | — | A | Kommagetrennt, passend zur Gruppe eines Diagramms. Leer erzeugt alle. Ein Jahresdiagramm über ein Jahrzehnt ist das teure; es wegzulassen ist, wie eine kleine Maschine mitkommt |
| `feeds.json.units` | choice | `METRICWX` | | Worin die Dateien geschrieben werden, egal was das Archiv hält |
| `feeds.json.unit.group_temperature` | choice | — | | Überschreibt das System für diese eine Gruppe — so kommt jemand zu Celsius und Zoll Quecksilber auf einer Seite, weil seine Leser das erwarten |
| `feeds.json.unit.group_pressure` | choice | — | | `mbar` `hPa` `inHg` `mmHg` `kPa` |
| `feeds.json.unit.group_rain` | choice | — | | `mm` `cm` `inch` |
| `feeds.json.unit.group_speed` | choice | — | | `meter_per_second` `km_per_hour` `mile_per_hour` `knot` |
| `feeds.json.unit.group_altitude` | choice | — | A | `meter` `foot` |
| `feeds.json.unit.group_distance` | choice | — | A | `km` `mile` |
| `feeds.json.twilight` | bool | `true` | | Dämmerung ist keine Kante: das Licht geht über die halbe Stunde der bürgerlichen Dämmerung, in hohen Breiten im Sommer über weit länger. Damit kann ein Diagramm das Echte zeichnen statt einer Stufe. Kostet ein paar hundert Byte je Datei |

→ [Feeds](Feeds), [Units](Units)

## Exports

Präfix `exports.<name>`. Deklariert in `exports/ftp.py` und `exports/rsync.py`.
Gemeinsam für beide:

| Name | Kind | Default | Bedeutung |
|---|---|---|---|
| `kind` | choice | — | `ftp` oder `rsync` |
| `host` | text | — | Der Server. Kein URL, nur der Name |
| `user` | text | — | |
| `directory` | text | `/` (ftp), — (rsync) | Wohin auf dem Server. Bei Shared Hosting meist `/httpdocs` oder `/public_html`, selten das Login-Verzeichnis |
| `source` | choice | — | Welchen Feed dieser Export sendet |
| `directory_source` | path | — | Oder ein Verzeichnis, wenn kein Feed gewählt ist |
| `delete` | bool | `false` | Entfernt Dateien, die nicht mehr erzeugt werden. Nur, was dieser Export selbst dorthin gebracht hat — er führt Buch |
| `trigger` | choice | `feed` | `feed` · `record` · `interval` · `manual` |
| `every` | duration | `900` (60–86400) | Nur mit `interval`. Unter dem Archivintervall liefe er ohne Neues |
| `timeout` | duration | `30` (ftp) / `600` (rsync) | Ein toter Host darf das nächste Intervall nicht aufhalten |

Nur FTP:

| Name | Kind | Default | Bedeutung |
|---|---|---|---|
| `password` | secret | — | |
| `port` | int | `21` | |
| `tls` | bool | `true` | FTPS. Aus nur, wenn der Host kein TLS hat — dann geht das Passwort als lesbarer Text übers Netz |
| `passive` | bool | `true` | Fast immer richtig. Aktiv verlangt, dass der Server zurück verbindet, was kein Heimrouter erlaubt |
| `tracker` | path | — | Wo vermerkt wird, was schon gesendet wurde. Leer heißt: neben dem Quellverzeichnis. Das ist, was verhindert, dass jedes Mal alles hochgeht; es zu verlieren kostet einen vollen Upload |

Nur rsync:

| Name | Kind | Default | Bedeutung |
|---|---|---|---|
| `port` | int | `22` | SSH-Port |
| `compress` | bool | `true` | Lohnt für Text, und eine Wetterseite ist meist Text |
| `key` | path | — | Leer benutzt, was SSH von selbst nähme. **Es gibt keine Passwortoption**: ein Passwort müsste von einem Programm getippt werden, was es in eine Prozessliste oder eine Datei bringt. Public Key in `authorized_keys` |
| `extra` | text | — | Weitere rsync-Argumente, durchgereicht wie sie sind. An Leerzeichen getrennt, also nichts mit Leerzeichen darin |

→ [Exports](Exports)

<!-- covers
src/weewx_evo/options.py
src/weewx_evo/ingest/plugins/ecowitt/driver.py
src/weewx_evo/feeds/jsongenerator/__init__.py
src/weewx_evo/exports/ftp.py
src/weewx_evo/exports/rsync.py
-->
