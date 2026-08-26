# WeeWX-Kompatibilität

## Die eine Regel

> Eine bestehende WeeWX-Datenbank bleibt lesbar und schreibbar — **für WeeWX
> selbst**. Nicht „importierbar": dieselbe Datei, dieselbe Bedeutung, und WeeWX 5
> kann sie danach weiterbenutzen.

Alles andere ist verhandelbar. Das hier nicht.

## Was geteilt wird und was nicht

| | |
|---|---|
| **Die Datenbank** | Geteilt. Dieselbe Datei, dieselbe Bedeutung |
| **Die Konfiguration** | Nicht geteilt. `weewx.conf` wird **gelesen, nie geschrieben** |

Zwei Programme, die eine Konfigurationsdatei schreiben, zerstören sich
gegenseitig die Kommentare. Was beide Systeme teilen — Standort, Höhe,
Archivintervall — darf trotzdem dort wohnen bleiben und wird von dort gelesen.

## Wie die Kompatibilität hergestellt wird

### 1. Das Schema kommt aus der Datei

`db/schema.py` liest es aus der geöffneten Datenbank, nicht aus einer Liste im
Code. Eine Anlage mit Sensoren, von denen wir nie gehört haben, behält sie.

`db/wview.py` — das ausgelieferte Startschema — wird **nur** benutzt, um eine
Datenbank anzulegen, die noch nicht existiert.

→ [Database-Archive](Database-Archive)

### 2. Die Arithmetik ist abgeschrieben

`aggregate.py` ist eine Transkription von `weewx.accum`, Schritt für Schritt in
derselben Reihenfolge. `units.py` ist eine Transkription von `weewx.units`,
Ausdruck für Ausdruck.

Eine „sauberere" Formel, die anders rundet, ist hier eine falsche Formel.

→ [Aggregation](Aggregation), [Units](Units)

### 3. Die Gewichtung ist WeeWX'

Jeder Satz trägt `60 * interval` Sekunden Gewicht in den Tagesstatistiken. Das
ist Version 2.0 und aufwärts; Version 1.0 gewichtete gleich, und das ist der
Fehler, für dessen Reparatur `patch_sums` existiert.

→ [Daily-Summaries](Daily-Summaries)

### 4. Die Randfälle sind WeeWX'

- Ein Satz genau um Mitternacht schließt den **vorherigen** Tag.
- Ein Satz genau auf einer Intervallgrenze schließt das Intervall, das dort
  endet.
- Windchill unter 10 °C und über 4,8 km/h, sonst die Temperatur selbst.
- Hitzeindex unter 40 °F ist die Temperatur.
- Eine Geschwindigkeit ohne Richtung ist kein Vektor und wird verworfen.

### 5. Sogar die Fehler sind geerbt

WeeWX' Umrechnungstabelle ist **nicht selbstinvers**: `mph → kph` nimmt
1.609344, `kph → mph` nimmt 1000/1609.34. 52 Paare kommen nicht exakt zurück.

`tools/unitcheck.py` prüft, dass **unsere Drift ihre Drift ist**, nicht dass es
keine gibt.

## Was geprüft wird

| Werkzeug | Was |
|---|---|
| `tools/difftest.py` | Die Tagesstatistiken einer echten Datenbank nachrechnen |
| `tools/roundtrip.py` | Einen Teil neu schreiben und prüfen, dass sich nichts bewegt |
| `tools/unitcheck.py` | Alle 147 Umrechnungen gegen WeeWX |
| `tools/seriestest.py` | Dieselbe Zeitreihe von beiden holen und vergleichen |
| `tools/derive_test.py` | Die abgeleiteten Werte gegen das, was WeeWX geschrieben hat |
| `tools/suncheck.py` | Sonnenzeiten gegen pyephem und gegen `weeutil.Sun` |

→ [Testing](Testing)

## Was verweigert wird

`ArchiveStore._check_version()` **öffnet eine Datenbank nicht**, deren
Tagesstatistiken bekannt fehlerhafte Gewichte tragen:

- WeeWX 4.2.0 las Version-2-Summen als Version 1.
- Die Reparatur in 4.3.0 ließ `dirsumtime` ungewichtet.

Beides ist behebbar, aber **von WeeWX**: `weectl database rebuild-daily`. Eine
solche Datei stillschweigend weiterzuschreiben hieße, falsche Gewichte mit
richtigen zu mischen.

## `weewx.conf` lesen

`weewxconf.py`. Ein eigener Parser, weil `configobj` eine Abhängigkeit wäre und
weewx-evo keine hat.

| Funktion | Bedeutung |
|---|---|
| `parse(text)` | Als verschachtelte Dictionaries. Werte bleiben Strings |
| `read(path)` | |
| `convert(conf, driver_names)` | In weewx-evo-Einstellungen, mit einem Bericht |
| `report(result, source)` | Was der Import tat, zum Lesen **bevor** man ihm traut |

**Typen sind Sache des Aufrufers**: `altitude = 440, meter` ist eine Länge und
eine Einheit, und nur etwas, das weiß, was `altitude` bedeutet, kann daraus
Meter machen.

`_splits()` entscheidet, ob ein Wert eine Liste ist. Der Fall, der es schwer
macht:

```ini
chart_line_colors = "#4282b4", "#b44242"
```

Das beginnt und endet mit einem Anführungszeichen und sind trotzdem fünf Werte.
**Nur ein Komma außerhalb der Anführungszeichen entscheidet.**

### Was übernommen wird

```bash
weewx-evo config import /etc/weewx/weewx.conf
weewx-evo config import /etc/weewx/weewx.conf --write
weewx-evo config import /etc/weewx/weewx.conf --write --overwrite
```

| | |
|---|---|
| `[Station]` | Name, Breite, Länge, Höhe (`_altitude_metres` rechnet Fuß um) |
| `[DataBindings]` / `[Databases]` | `_databases()` findet die SQLite-Datei hinter dem Archiv-Binding |
| `[StdArchive]` | Archivintervall, `loop_hilo` |
| Der Treiber | `_driver()` findet heraus, welcher in Benutzung ist, und bringt seine Einstellungen mit |
| `[Accumulator]` | `_accumulators()` — siehe unten |

### `[Accumulator]` ist besonders

**Das ist der eine Teil von `weewx.conf`, der aufgezeichnete Zahlen ändert statt
Verhalten.** Ein Extraktor entscheidet, ob ein Feld über ein Intervall gemittelt
oder summiert wird. Ihn zu übersehen heißt, dass dieselbe Station in zwei
Systemen zwei verschiedene Zahlen aufzeichnet.

→ [Aggregation](Aggregation#obstypes)

### Was nicht übernommen wird — und warum

`_NOT_OURS` benennt es einzeln:

| Abschnitt | Grund |
|---|---|
| `[StdReport]` | Berichtserzeugung, die weewx-evo (noch) nicht macht |
| `[StdRESTful]` | Uploads zu Wetterdiensten, noch nicht |
| … | |

**Schweigen liest sich wie „verloren".** Der Bericht nennt, was liegen blieb,
und benennt, warum.

## Die Diagramme

```bash
weewx-evo plots import /etc/weewx/skins/Seasons/skin.conf --write
```

Zwei Fallen, beide echt gewesen:

- **WeeWX' Suffixe sind nicht unsere.** Dort ist `M` eine Minute und `m` ein
  *Monat*. Eine Datei, die für WeeWX geschrieben wurde, wird nach WeeWX' Regeln
  gelesen — und nichts wird je mit einem mehrdeutigen Suffix zurückgeschrieben.
- **`skip_if_empty = year` ist eine Zeitspanne, kein Boolean.** Als Boolean
  gelesen schreibt der Seasons-Satz 100 Dateien statt 71.

→ [Plots](Plots#zwei-fallen-im-importer)

## Was WeeWX kann und weewx-evo nicht

- **Berichte und Skins.** Die Generatorseite ist nicht im Umfang. Der JSON-Feed
  ist die Grundlage, auf der eine Skin gebaut werden könnte.
- **RESTful-Uploads** zu Wetterdiensten.
- **Pull-Treiber** für serielle Hardware — die Schnittstelle steht
  (`listener.push()`), die Treiber gibt es nicht.

## Was weewx-evo kann und WeeWX nicht

| | |
|---|---|
| Neustart mitten im Intervall kostet nichts | Es gibt keinen In-Memory-Akkumulator, der ihn nicht überlebt |
| Ein verspätetes Push-Paket landet im richtigen Intervall | Es wird nach seinem Zeitstempel eingeordnet, nicht nach seiner Ankunft |
| Rückwirkende Korrektur | Solange die Rohpakete in der Retention liegen |
| Mehrere Quellen ohne Wrapper-Treiber | Zusammengeführt beim Bau des Intervalls, je Feld → [Multiple-Sources](Multiple-Sources) |
| Listener und Archiver getrennt betreibbar | Ohne Codeänderung |
| Was keine Spalte hat, wird **gemeldet** | `weewx-evo columns` |
| Plot-Definitionen gehören nicht dem Renderer | → [Plots](Plots) |
| Feed und Export sind getrennt | → [Feeds](Feeds), [Exports](Exports) |

## Eine bewusste Abweichung

**Ein Mittelwert ist hier immer mit `interval` gewichtet.** WeeWX gewichtet in
den Tagesstatistiken so, benutzt aber ein schlichtes `AVG()` auf der
Archivtabelle — in einer Datenbank, deren Archivintervall sich geändert hat,
widerspricht WeeWX also sich selbst.

Gemessen: `tools/seriestest.py`, 94 Vergleiche, 19 957 Punkte, 0 Fehler,
8 bekannte Abweichungen (genau diese).

→ [Series](Series#eine-bewusste-abweichung)

## Nebeneinander betreiben

Beide Systeme können dieselbe Station füttern und ihre Archive Satz für Satz
vergleichbar halten. Praktisch heißt das: eine Quelle, die den Rohbody an zwei
Ziele weiterreicht, jedes mit **eigener Pause**, damit ein Ausfall des einen das
andere nicht mitnimmt.

Dieselbe Datenbank gleichzeitig von beiden **beschreiben** zu lassen, ist etwas
anderes und nicht vorgesehen.

<!-- covers
src/weewx_evo/weewxconf.py
src/weewx_evo/db/wview.py
-->
