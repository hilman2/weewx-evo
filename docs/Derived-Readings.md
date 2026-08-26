# Abgeleitete Messwerte

`derive.py`. Messwerte, die aus anderen Messwerten folgen.

Eine Station misst Temperatur, Feuchte, Druck und Wind. Taupunkt, Windchill,
gefühlte Temperatur und Wolkenuntergrenze folgen daraus durch Arithmetik, und
die meisten Konsolen senden sie nicht. WeeWX nennt das `StdWXCalculate`; ohne es
endet eine Datenbank mit einer `dewpoint`-Spalte, die jahrelang leer ist.

**Eines davon ist keine Bequemlichkeit, sondern eine Messung**: `rain`. Siehe
[unten](#der-eine-der-eine-messung-ist).

## Die Formeln

Alle gegen WeeWX geprüft, nicht gegen die Literatur — siehe
[Prüfen](#prüfen).

| Funktion | Was |
|---|---|
| `dewpoint_c(t_c, rh)` | Taupunkt, Magnus-Formel wie bei WeeWX |
| `windchill_c(t_c, v_kph)` | Environment-Canada-Formel. Nur unter 10 °C und über 4,8 km/h definiert; außerhalb ist es die Temperatur selbst, was WeeWX zurückgibt |
| `heatindex_f(t_f, rh)` | Rothfusz mit den zwei Korrekturen. Unter 40 °F gibt es keinen Hitzeindex, und die Temperatur kommt zurück |
| `humidex_c(t_c, rh)` | Unter 21 °C ist es die Temperatur |
| `apptemp_c(t_c, rh, wind_mps)` | Gefühlte Temperatur, Formel des australischen BOM |
| `altimeter_inhg(pressure_inhg, altitude_ft)` | Höhenmessereinstellung aus dem Stationsdruck, aaASOS-Algorithmus |
| `cloudbase_ft(t_f, rh, altitude_ft)` | Wolkenuntergrenze aus der Spreizung |
| `max_solar_rad(lat, lon, alt_m, when, atc=0.8)` | Klarhimmelstrahlung, W/m², Ryan-Stolzenbach (MIT, 1972) |
| `windrun(speed, seconds)` | Weg, den der Wind zurücklegte. Geschwindigkeit mal Zeit — die Einheit folgt der Geschwindigkeit, deshalb wird hier nichts umgerechnet |
| `delta(now, before, name)` | Wie viel eine laufende Summe zugenommen hat |
| `sun_position(when, lat, lon, alt_m)` | Elevation und Erdentfernung. pyephem wenn installiert, sonst NOAA — dieselbe Anordnung wie bei WeeWX |

`SOLAR_CONSTANT = 1367.0`.

### Warum `max_solar_rad` überhaupt gerechnet wird

Es ist, was ein Solarsensor bei wolkenlosem Himmel lesen würde. Ein gemessener
Wert dagegen gehalten ist, was sagt, wie bewölkt es war — deshalb lohnt sich die
Rechnung auch für eine Station, die einen Sensor hat.

## `Deriver`

```python
station = Station(latitude=48.4596, longitude=11.6539, altitude_m=440.0)
deriver = Deriver(station=station, how={...})
record = deriver.apply(record)
```

Das Objekt hält **einen** Zustand: den letzten Wert jeder laufenden Summe, damit
eine Differenz gebildet werden kann. Genau dieser Zustand ist der Grund, warum
es ein Objekt ist und keine Funktion.

| Methode | Bedeutung |
|---|---|
| `wanted(name, record)` | Ob dieser Wert für diesen Satz gerechnet wird |
| `apply(record)` | Ergänzen, was fehlt. Der Satz wird verändert und zurückgegeben |
| `forget()` | Die laufenden Summen vergessen. Das nächste Paket nimmt keine Differenz |

`from_settings(settings)` baut einen aus der aufgelösten Konfiguration.

### Die Reihenfolge zählt

`apply()` rechnet **Taupunkt vor Wolkenuntergrenze**, weil letztere aus ersterem
folgt. Ausgeschrieben statt aus einem Abhängigkeitsgraphen aufgelöst: es sind
acht Werte, und ein Graph wäre mehr Code als die Reihenfolge.

### Die drei Politiken

`HOW = ("prefer_hardware", "hardware", "software")` — WeeWX' `StdWXCalculate`.

| | |
|---|---|
| `prefer_hardware` | Nehmen, was die Konsole schickt; rechnen, wenn sie nichts schickt. Der Default |
| `hardware` | Nur, was die Konsole schickt |
| `software` | Immer selbst rechnen, auch wenn die Konsole etwas schickt |

Je Messwert einstellbar.

## Der eine, der eine Messung ist

`delta(now, before, name="rain")`. Ecowitt-Hardware sendet **laufende Summen**
(`totalrain`, `dailyrain`), nicht das, was seit dem letzten Paket gefallen ist.
`rain` ist die Differenz.

Drei Fälle, die keine Fehler sind und nicht als solche behandelt werden dürfen:

| Fall | Warum es kein Fehler ist | Was passiert |
|---|---|---|
| **Kein Vorwert** — das erste Paket nach einem Start | Es gibt keine Differenz. Eine zu erfinden buchte die ganze bisherige Summe als Regen dieser Minute | Nichts wird gebucht |
| **Die Summe ist kleiner geworden** | Ein Zählerüberlauf oder ein Zurücksetzen um Mitternacht | Der neue Wert selbst, nicht eine negative Zahl |
| **Die Summe steht still** | Es hat nicht geregnet | `0`, kein `None` |

Der erste Fall ist der, der stillschweigend eine Messreihe ruiniert: ein
Neustart nach einem nassen Monat, und die Statistik hat einen Sekundenschauer
von 84 mm.

`_remember()` hält die letzten Werte. `forget()` wirft sie weg — was nach einer
Ausfallzeit richtig ist, weil eine Differenz über eine unbekannte Lücke keine
Aussage ist.

## Prüfen

```bash
python tools/derive_test.py reference/weewx.sdb
```

Die Referenzdatenbank hat Jahre von Sätzen, in denen WeeWX Taupunkt,
Hitzeindex und den Rest aus Messwerten gerechnet hat, die **in derselben Zeile
stehen**. Das macht sie zu einem Testorakel, das niemand schreiben musste: aus
derselben Zeile neu rechnen und vergleichen.

Diese Formeln entscheiden Zahlen, die in eine Datenbank gehen, die WeeWX wieder
liest. **Mit WeeWX übereinzustimmen zählt hier mehr, als im Abstrakten recht zu
haben.**

Der Test prüft zusätzlich:

- `rain_tests()` — der Fall, der eine Messung ist
- `policy_tests()` — die drei Politiken
- `edge_tests()` — die Ränder der Definitionsbereiche

→ [Testing](Testing), [Sun](Sun), [Units](Units)

<!-- covers
src/weewx_evo/derive.py
tools/derive_test.py
-->
