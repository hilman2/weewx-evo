# Sonne

`sun.py`. Wo die Sonne steht und wann sie aufgeht.

Zwei Dinge brauchen das:

- **Ein Messwert.** `maxSolarRad` ist, was ein Sensor bei wolkenlosem Himmel
  sähe, und das hängt von der Elevation ab. → [Derived-Readings](Derived-Readings)
- **Ein Diagramm.** Die Stunden der Dunkelheit werden schattiert, weil ein
  Temperaturverlauf keinen Sinn ergibt, ohne zu wissen, welcher Teil Nacht war.
  → [Feeds](Feeds)

pyephem, wenn es installiert ist, und die Arithmetik hier, wenn nicht — dieselbe
Anordnung, die WeeWX hat (es fällt auf `weeutil.Sun` zurück).

## Genauigkeit

Gemessen gegen pyephem an sechs Orten von Tromsø bis Ushuaia und den vier
Wendepunkten des Jahres:

| | |
|---|---|
| Deklination | auf 0,002° |
| Sonnenaufgang | auf 37 Sekunden |

`weeutil.Sun`, WeeWX' eigener Fallback, liegt über denselben Fällen bis zu
**6,5 Minuten** daneben.

Eine Minute daneben ist unsichtbar. Zehn Minuten daneben ist ein Band, das
sichtbar nicht zum fallenden Temperaturverlauf passt.

## Die Funktionen

| | |
|---|---|
| `solar(when)` | Deklination (Grad), Zeitgleichung (Minuten), Erdentfernung (AE). NOAA's Algorithmus |
| `position(when, lat, lon, alt_m)` | Elevation in Grad und Entfernung in AE |
| `solar_noon(when, longitude)` | Wann die Sonne am höchsten steht |
| `crossings(day_ts, lat, lon, angle=HORIZON)` | Wann die Sonne eine Elevation aufwärts und abwärts passiert |
| `events(day_ts, lat, lon)` | Aufgang, Untergang und die bürgerliche Dämmerung darum |
| `day_night(start, stop, lat, lon)` | Was ein Diagramm zum Schattieren braucht |
| `local_midnight(ts)` | Beginn des lokalen Tages |
| `describe(day_ts, lat, lon)` | Ein Tag Sonne als Zeile, die jemand liest. Für die CLI |

```python
HORIZON = -0.833   # Oberrand, mit Refraktion
CIVIL   = -6.0     # bürgerliche Dämmerung
```

`solar_noon` korrigiert zweifach gegen die Uhrzeit: wie weit östlich oder
westlich der Beobachter vom Meridian seiner Zone ist, und die Zeitgleichung —
bis zu einer Viertelstunde.

`day_night()` gibt zurück, womit die Spanne beginnt (`day` oder `night`), jede
Horizontpassage darin und die Strecken von Dämmerung darum. `None`, wo nichts
passiert — Polartag und Polarnacht.

## Zwei Fallen, beide echt gewesen

### pyephem rechnet Refraktion selbst

Ihm `horizon = -0.833` zu geben zählt Refraktion und Sonnenradius **doppelt** —
vier bis fünf Minuten, ein Nachtband, das sichtbar nicht zum fallenden
Temperaturverlauf passt.

Richtig:

```python
observer.pressure = 0
observer.horizon = "-0:34"
ephem.Sun(), use_center=False    # Oberrand
```

### Ein Tag ist der Tag der Sonne, nicht der des Kalenders

In Wellington liegt der Sonnenmittag 20 Minuten **nach** UTC-Mitternacht. An
einem Kalenderdatum verankert paart man den Aufgang eines Morgens mit dem
Untergang des Vorabends.

Deshalb liegen beide Zeiten in `crossings()` um den Sonnenmittag, der dem
gegebenen Moment am nächsten ist — nicht um Mitternacht.

## Dämmerung ist keine Kante

Das Licht geht über die halbe Stunde der bürgerlichen Dämmerung, in hohen
Breiten im Sommer über weit länger. Deshalb liefert `day_night()` die
Dämmerungsstrecken mit: ein Diagramm kann das Echte zeichnen statt einer Stufe.

Kostet ein paar hundert Byte je Datei, abschaltbar über `feeds.json.twilight`.

## Prüfen

```bash
python tools/suncheck.py
```

Sechs Orte × fünf Tage, gegen pyephem **und** gegen WeeWX' Fallback:

```python
PLACES = [("Kirchdorf", 52.0, 9.0), ("Seattle", 47.6, -122.3),
          ("Tromso", 69.65, 18.96), ("Quito", -0.18, -78.47),
          ("Wellington", …), ("Ushuaia", …)]
DAYS = ["2026-03-20", "2026-06-21", "2026-09-22", "2026-12-21", "2026-08-26"]
TOLERANCE = 60.0    # Sekunden
```

Es gibt drei Antworten und sie sind nicht gleich gut:

- **pyephem** ist die genaue, und die, die WeeWX nimmt, wenn sie da ist. Sie ist
  hier die Referenz.
- **`weewx_evo.sun`s Formel** ist die, die benutzt wird, wenn pyephem fehlt.
- **`weeutil.Sun`** ist WeeWX' Fallback, und der ungenaueste.

`apart()` rechnet zwei Momente gegeneinander unter Berücksichtigung des Tages,
in dem sie landen: `weeutil.Sun` gibt Stunden relativ zu einem UTC-Tag zurück,
also kommt ein Sonnenuntergang in Seattle als 02:27 des Folgetages heraus.
Direkt verglichen wäre das ein ganzer Tag Unterschied.

→ [Testing](Testing)

<!-- covers
src/weewx_evo/sun.py
tools/suncheck.py
-->
