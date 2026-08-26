# Aggregation

`aggregate.py` ist der Kern: Rohwerte rein, Statistik raus. Kein Zustand, keine
Datenbank, keine Uhr.

> **`aggregate.py` ist eine Transkription von `weewx.accum`, keine
> Neuinterpretation.** Jeder Rechenschritt steht in derselben Reihenfolge und
> derselben Form, weil diese Zahlen in `archive_day_*`-Tabellen landen, die
> WeeWX weiterlesen muss. Eine „sauberere" Formel, die anders rundet, ist hier
> eine **falsche** Formel.

Vor jeder Änderung:

```bash
python tools/difftest.py reference/weewx.sdb
```

→ [Testing](Testing)

## Zwei bewusste Abweichungen vom Original

1. **Kein globaler Zustand.** WeeWX hält die Aggregationspolitik in einer
   globalen `ChainMap`, die Module beim Import verändern
   (`weewx.accum.accum_dict`). Hier ist es ein gewöhnliches Objekt, das man
   herumreicht — genau das macht den Differenztest gegen eine echte Datenbank
   möglich, weil zwei Politiken gleichzeitig existieren können.
   → [`obstypes.py`](#obstypes)
2. **Keine WeeWX-Importe.** Die Datei steht für sich.

## Die Akkumulatoren

Drei Klassen, je eine Sorte Messgröße.

### `FirstLast`

Der minimale. Merkt sich den ersten und den letzten gesehenen Wert. Rechnet
nichts, deshalb taugt er auch für Strings.

`set_stats()` ist bewusst wirkungslos: nichts, was diese Klasse hält, überlebt
eine Runde durch die Datenbank.

### `Scalar`

Minimum, Maximum und ein **gewichteter** Mittelwert.

| Feld | Bedeutung |
|---|---|
| `min`, `mintime` | Tiefstwert und wann |
| `max`, `maxtime` | Höchstwert und wann |
| `sum`, `count` | Summe und Anzahl |
| `wsum`, `sumtime` | Gewichtete Summe und Gesamtgewicht |

`wsum` und `sumtime` sind, was einen Mittelwert über eine beliebige Periode
später überhaupt möglich macht: die Summe ist gewichtet damit, wie lange jeder
Wert stand. Sätze verschiedener Intervalllängen mitteln dadurch korrekt
zusammen. → [Daily-Summaries](Daily-Summaries)

### `Vector`

Für Wind: die skalaren Statistiken plus die Vektorsummen.

| Feld | Bedeutung |
|---|---|
| `xsum`, `ysum` | Ost- und Nordkomponente, summiert |
| `dirsumtime` | Gewicht, das **nur** für Messungen mit einer Richtung zählt |
| `squaresum`, `wsquaresum` | Für den quadratischen Mittelwert (RMS) |
| `max_dir` | Die Richtung zum Höchstwert |

`xsum`/`ysum` sind der Grund, warum eine mittlere *Richtung* eine Mittelung
überlebt — Grad zu addieren täte es nicht. `dirsumtime` zählt nur Messungen mit
Richtung, weil eine Windstille ohne Fahne keine Richtung beiträgt.

Auswertende Methoden: `avg()`, `rms()`, `vec_avg()`, `vec_dir()`.

## `Accumulator`

Statistiken für eine Menge von Messgrößen über **eine** Zeitspanne.

```python
acc = Accumulator(start, stop, policy=DEFAULT_POLICY)
acc.add_record({"dateTime": t, "usUnits": 1, "outTemp": 21.4}, weight=300)
record = acc.record()
```

Die Spanne ist **am Anfang halboffen**: ein Satz, der genau auf `start` fällt,
gehört zur vorherigen Spanne. Dasselbe Prinzip wie
`start_of_archive_day()` — ein Satz genau um Mitternacht schließt den
*vorherigen* Tag. WeeWX hat das immer so gemacht, und die Tagesstatistiken sind
nach dem Ergebnis indiziert.

| Methode | Bedeutung |
|---|---|
| `add_record(record, add_hilo=True, weight=1)` | Einen Satz einfalten. Wirft `ValueError`, wenn er außerhalb der Spanne liegt oder ein anderes Einheitensystem hat — beides sind Fehler im Aufrufer, keine Daten |
| `merge_hilo(other)` | Die Extreme eines anderen Akkumulators einfalten |
| `record()` | Einen Archivsatz herausziehen, gestempelt auf das **Ende** der Spanne |
| `augment(record)` | Auffüllen, was der Satz nicht schon trägt. Vorhandene Werte gewinnen — so behält der Archivsatz einer Konsole ihre hardwaregerechneten Felder und gewinnt die fehlenden dazu |
| `set_stats(obs_type, tuple)` | Statistik direkt aus dem Speicher laden, an der Arithmetik vorbei. Ohne Tupel entsteht der Typ nur, leer — so bekommt ein Tag eine Zeile für eine Größe, die an ihm nie gemessen wurde |

### Wind wird zweimal aufgenommen

`_add_wind()`: einmal als schlichtes `windSpeed`, einmal als Vektor. Das ist
WeeWX' Verhalten und der Grund, warum `windSpeed`- und `wind`-Statistiken in
derselben Datenbank nebeneinander stehen.

### `_merge_avg`

Für `windSpeed` wird beim Zusammenführen der **Mittelwert** des anderen
Akkumulators als dessen Höchstwert benutzt. Das Tageshoch soll der höchste
*anhaltende* Wind sein, nicht die höchste Momentanmessung — die steht in
`windGust`.

## `obstypes`

`obstypes.py` sagt, **wie** jede Größe aggregiert wird.

```python
@dataclass
class ObsPolicy:
    accumulator: str   # scalar | vector | firstlast
    adder: str
    merger: str
    extractor: str
```

`Policy` ist die Politik einer ganzen Anlage. `overrides` spiegelt den
`[Accumulator]`-Abschnitt von `weewx.conf`: eine Abbildung von Messgröße auf die
Felder, die vom Default abweichen.

> **Die Defaults sind WeeWX' `DEFAULTS_INI` wörtlich.** Einen Wert hier zu
> ändern ändert aufgezeichnete Historie.

`DEFAULT_POLICY` ist die Instanz, die überall benutzt wird, wo keine andere
übergeben wurde.

`config import` bringt einen vorhandenen `[Accumulator]`-Abschnitt mit — es ist
der eine Teil von `weewx.conf`, der aufgezeichnete Zahlen ändert statt
Verhaltens. → [WeeWX-Compatibility](WeeWX-Compatibility)

## Hilfsfunktionen

| | |
|---|---|
| `to_float(x)` | WeeWX' `weeutil.to_float`: der String `'none'` ist ein Null-Wert, kein Fehler |
| `_usable(val)` | Als Float, oder `None`, wenn fehlend, unparsbar oder NaN |
| `start_of_archive_day(ts)` | Der Beginn des Tages, zu dem ein Archivsatz gehört — Mitternacht schließt den vorherigen Tag |

## Was der Differenztest prüft

`tools/difftest.py` baut die Tagesstatistiken einer echten Datenbank neu auf und
vergleicht sie mit dem, was WeeWX hineingeschrieben hat. Zwei Spaltenklassen,
zwei Maßstäbe — und der Unterschied ist der Punkt:

- **Summen** (`sum`, `count`, `wsum`, `sumtime`, `xsum`, `ysum`, `dirsumtime`,
  `squaresum`, `wsquaresum`) stammen ausschließlich aus Archivsätzen. Sie müssen
  **exakt** stimmen.
- **Extremwerte** dürfen abweichen. Mit `loop_hilo = True` schreibt WeeWX
  LOOP-Pakete direkt in die Tagesextreme, und die sind feiner als jeder
  Archivsatz. Eine Rekonstruktion kann nur gleich oder **stumpfer** sein — nie
  schärfer. Schärfer wäre ein Fehler, und genau darauf prüft der Test.

```
sum mismatches:            0
extremes sharper than DB:  0
extremes duller than DB:   189   (expected: LOOP highs/lows)
```

Diese Asymmetrie ist das beste Argument für die Live-Tabelle, und sie ist
messbar: `roundtrip.py --packets` speist die gespeicherten LOOP-Pakete wieder
ein, und wo sie den Zeitraum abdecken, sinkt die Zahl entsprechend.

→ [Testing](Testing), [Database-Live](Database-Live)

<!-- covers
src/weewx_evo/aggregate.py
src/weewx_evo/obstypes.py
tools/difftest.py
-->
