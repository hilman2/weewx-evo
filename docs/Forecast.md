# Vorhersage

`forecast/`. Was kommt, von jemandem der es weiß.

Eine Wetterstation misst. Eine Vorhersage ist die andere Hälfte dessen, wofür
Leute überhaupt auf eine Wetterseite schauen — und WeeWX hat sie nie im Kern
gehabt. Deshalb existiert `weewx-DWD`, und deshalb ist es auf zehn Datenquellen,
zwei Abhängigkeiten außerhalb der Standardbibliothek, Radar-Animation und
Pollenflug gewachsen.

Dieses Wachstum ist das Argument dafür, hier eine Linie zu ziehen — nicht
dafür, es gar nicht zu haben.

## Die Linie: drei Quellen und eine vierte für Amerika

| | |
|---|---|
| `open-meteo` | die Welt. Kein Schlüssel, reines JSON, und es wählt das beste Modell für einen Ort selbst — ICON in Deutschland, ECMWF oder GFS anderswo. Eine Quelle deckt fast alle ab |
| `dwd` | Deutschlands eigene Stationsvorhersage (MOSMIX). Die Punktvorhersage für einen tatsächlichen Ort statt einer Gitterzelle |
| `meteoalarm` | Warnungen für 38 europäische Länder, in einem Atom-Feed aus CAP-Dokumenten. Der offizielle Aggregator |
| `dwd-warnings` | Deutschlands Warnungen im Wortlaut des DWD, den MeteoAlarm wegübersetzt |
| `nws` | die Vereinigten Staaten: Warnungen und eine Vorhersage in einer API, ohne Schlüssel |

**Ausdrücklich nicht dabei:** Radar-Animation, Kartenserver, Pollenflug, alles
mit kostenpflichtigem Schlüssel. Jedes davon ist Sache eines Plugins, und die
Plugin-Schnittstelle ist dieselbe wie bei den [Treibern](Drivers).

Keine dieser Quellen braucht ein Konto.

## Wohin es geht: eine eigene Datei, nie ins Archiv

Das ist die eine Regel dieses Projekts, noch einmal gesagt. `archive` ist, was
WeeWX geschrieben hat und weiter lesen können muss — eine Spalte mit
vorhergesagten Temperaturen darin wäre eine Lüge, die sich über Jahre schlecht
mittelt, und `archive_day_*` würde die Lüge bereitwillig zusammenfassen.

Also: `forecast.sdb`, neben dem Archiv, und alles daran ist darauf ausgelegt,
dass sie entbehrlich ist.

- **Ersetzt, nicht angesammelt.** Ein neuer Lauf einer Quelle löscht ihren
  vorherigen. Niemand will die gestrige Vorhersage für heute, und sie zu
  behalten macht aus einer kleinen Datei eine große ohne Leser.
- **Eine Tabelle für die Stunden, eine für die Tage, eine für die Warnungen.**
  Keine breite: eine Warnung hat mit einer Temperatur nichts gemeinsam, und ein
  Tag ist keine Stunde mit anderen Spalten.
- **Die Datei zu löschen kostet einen Download.** Das ist die Definition eines
  Caches und der Grund, warum hier nichts einen Migrationspfad braucht.

Jede Zeile trägt den Namen ihrer Quelle, also können zwei nebeneinander laufen
und eine Seite kann sagen, welche sie meint.

## Zwei Fehlerarten, und sie sind nicht dieselbe

**Ein fehlgeschlagener Abruf behält die alte Vorhersage.** Keine leere. Eine
Quelle, die nicht erreichbar war, hat uns nichts über das Wetter gesagt, und
die gestrige gute Vorhersage durch nichts zu ersetzen macht aus einem
Netzwerk-Schluckauf eine leere Seite.

**Ein leerer Warnungs-Feed ist eine Antwort.** MeteoAlarm liefert keine
Einträge, wenn das Wetter ruhig ist, und das heißt: die Warnungen sind
vorbei. Warnungen werden also **absichtlich** durch nichts ersetzt. Eine
abgelaufene Sturmwarnung auf einer Seite stehen zu lassen ist der eine Fehler
hier, der jemandem tatsächlich schaden könnte.

Unterschieden werden die beiden dadurch, *wo* sie passieren: eine Exception
erreicht den Store nie, ein erfolgreicher Abruf immer.

## Die Fallen der Quellen

### Open-Meteo: der Tagesstempel

Ihr Tagesstempel ist lokale Mitternacht, ausgedrückt in UTC. Der Offset muss
abgezogen werden, um den tatsächlichen Zeitpunkt zu bekommen. Ohne das beginnt
ein „Tag" in Berlin um 02:00, jede Tageszahl hängt zwei Stunden am falschen
Datum — und es kippt an der Sommerzeitgrenze.

`timeformat=unixtime` wird benutzt, weil der Standard lokale ISO-Zeichenketten
ohne Zone sind und die zu parsen bedeutet zu wissen, für welche Zone die API
sich entschieden hat.

`timezone=auto` bleibt trotzdem nötig: es entscheidet, wo ein Tag anfängt.

### MOSMIX: Kelvin

`TTT` ist `287.35`, nicht `14.2`. Jede Temperatur in MOSMIX ist absolut, und
eine als Celsius zu lesen ergibt eine Vorhersage von 287 Grad — was immerhin
auffällt. Falsch herum umgerechnet wären es −259.

Der Druck ist aus demselben Grund in Pascal, und die Strahlung in kJ/m² pro
Stunde statt in Watt.

MOSMIX kommt als KMZ: eine gezippte KML-Datei, ISO-8859-1 kodiert, etwa 350 kB
je Station, mit jedem Wert als leerzeichengetrennte Liste. `zipfile` und
`xml.etree` sind beide in der Standardbibliothek, das kostet also nur den Code.

**Ein Stationskürzel, keine Koordinate.** MOSMIX wird je Station
veröffentlicht, und die nächstgelegene ist ohne die Stationsliste nicht
herleitbar. Deshalb holt `check()` diese Liste und nennt die fünf nächsten —
so findet jemand seine.

### MeteoAlarm: ein Länderfeed ist kein Ort

Deutschlands Feed trägt jede Warnung für jeden Landkreis: an einem
gewöhnlichen Morgen 46 davon. Eine Region muss also gewählt werden, und die
Regions-IDs (`DE037`) kennt niemand auswendig.

`check()` listet deshalb, was gerade im Feed steht, mit Namen — was den
Test-Knopf der Einstellungsseite zum Weg macht, wie jemand seine Region
findet, statt zu einem nachträglichen Validierungsdetail.

Gefiltert wird über die Gebietsbeschreibung **und** die ID, weil „Kreis Plön"
auffindbar ist und `DE037` nicht.

Ohne Region wird alles behalten. Das ist laut statt still, und das ist bei
einer Warnung die richtige Richtung: eine Seite voller Alarme für ein ganzes
Land fällt jemandem auf. Eine fehlende Warnung nicht.

> **Die alten RSS-Feeds wurden am 14. Januar 2026 abgeschaltet.** Die
> Atom-Feeds tragen dieselben Daten. Was noch auf `.../rss/...` zeigt, empfängt
> seitdem nichts — still.

### NWS: ein User-Agent ist Pflicht

`api.weather.gov` verlangt einen, der die Anwendung nennt, und antwortet ohne
ihn mit 403. Das ist ungewöhnlich genug, um es zu erwähnen: dieselbe Anfrage
funktioniert aus einem Browser und nicht aus einer Bibliothek, und das liest
sich einen Nachmittag lang wie ein Netzwerkproblem.

Ein Punkt ist außerdem keine Gitterzelle: alles geht erst über
`/points/{lat},{lon}`. Diese Zuordnung ist für eine feste Station stabil, wird
also einmal geholt und gemerkt.

Die Vorhersage ist Prosa — `"10 mph"`, `"Mostly Cloudy"` — und muss
zurückgeparst werden. Das ist verlustbehaftet und der Grund, warum Open-Meteo
auch in Amerika der Standard bleibt. Worin der NWS unbestritten am besten ist,
sind die Warnungen; die Vorhersage ist deshalb standardmäßig aus.

## Wettercodes

`codes.py`. Jede Quelle spricht einen anderen Dialekt von „was das Wetter tut":
Open-Meteo veröffentlicht einen reduzierten WMO-4677-Satz, der DWD den vollen,
der NWS englische Sätze. Sie werden beim Hereinkommen in WMO-Codes übersetzt,
damit alles danach ein Vokabular hat.

**Die Wörter sind hier Englisch und werden in `language.py` übersetzt** —
dieselbe Anordnung wie bei den Mondphasen und den Himmelsrichtungen.

**Die Symbole sind ein Name, kein Bild.** `partly-cloudy-day` und sonst nichts.
Welche Datei das ist, gehört dem, der die Seite zeichnet: eine Skin bringt ihre
eigenen Icons mit, und eine Abbildung auf einen bestimmten Satz würde die
Icons dieser Skin unbrauchbar machen.

## Was eine Skin schreiben kann

```
$forecast.now.outTemp                  die Stunde, in der wir sind
$forecast.now.text                     "Leichter Regen"
$forecast.now.symbol                   "rain", für welche Icons auch immer
$forecast.hours[3].outTemp             in vier Stunden
$forecast.days[0].tempMax              das heutige Maximum
$forecast.days[1].sunrise              der morgige Sonnenaufgang
$forecast.warnings                     die offiziellen, schlimmste zuerst
$forecast.warning                      die schlimmste, oder nichts
$forecast.updated                      wann zuletzt geholt wurde
$forecast.issued                       wann das Modell gelaufen ist
$forecast.ahead.days[0].tempMax        aus der Quelle namens "ahead"
```

Eine Vorhersagetemperatur kommt als derselbe `Value` zurück wie eine gemessene.
Eine Vorlage formatiert also beide gleich, und `units.Target` rechnet beide um:
eine Seite in Fahrenheit zeigt eine metrische Vorhersage in Fahrenheit, ohne zu
wissen, dass es zwei Systeme gibt.

**Eine fehlende Vorhersage ist kein Fehler.** Auf einer Station, die vor einer
Minute gestartet ist, wurde noch nichts geholt, und eine Vorlage muss trotzdem
rendern. Es kommen leere Listen und `Unknown` zurück, und der Fehlgriff wird
gezählt, damit der Feed ihn berichten kann.

`$forecast.updated` und `$forecast.issued` sind verschiedene Fragen: eine
Seite, die „vor einer Minute aktualisiert" über einen sechs Stunden alten
Modelllauf sagt, lügt höflich. Beide Zahlen sind da, damit sie es nicht muss.

## Konfiguration

Zwei Quellen ist die gewöhnliche Anordnung, nicht die Ausnahme: eine für die
Zahlen und eine für die Warnungen, weil kein Dienst beides gut kann.

```toml
[forecast.ahead]
kind = "open-meteo"
days = 7

[forecast.warnings]
kind = "meteoalarm"
country = "germany"
region = "Kreis Freising"
minimum = "Moderate"
```

## Kommandos

```bash
weewx-evo forecast list             # was es gibt und was konfiguriert ist
weewx-evo forecast check            # einmal holen, nichts speichern
weewx-evo forecast run              # jetzt holen und speichern
weewx-evo forecast show --hours 12  # ausgeben, was gespeichert ist
```

`check` tut doppelten Dienst: eine MOSMIX-Quelle ohne Stationskürzel und eine
MeteoAlarm-Quelle ohne Region antworten beide mit den in Frage kommenden statt
mit einem Fehler.

## Prüfen

```bash
python tools/forecast_test.py
```

Ohne Netz. Jede Vorlage darin ist eine gekürzte Kopie einer echten Antwort —
die Feldnamen, die Namensräume und die Kodierungen sind genau das, was die
Dienste senden, denn daran scheitert das Parsen.

→ [Einheiten](Units) · [Feeds](Feeds) · [Uploads](Uploads)
