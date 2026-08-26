# Einheiten

`units.py`. Welche Einheit ein Messwert hat und wie man ihn nennt.

> **`units.py` ist eine Transkription von `weewx.units`, Ausdruck für Ausdruck.**
> Nicht nachgerechnet: ein „sauberer" umgeschriebener Faktor ist ein Diagramm,
> das in der dritten Nachkommastelle von WeeWX abweicht, und herauszufinden
> warum kostet einen Nachmittag.

Die Datenbank hält **ein** Einheitensystem je Satz und sagt in `usUnits`,
welches. Alles andere — welcher Gruppe ein Messwert angehört, welche Einheit
diese Gruppe in jedem System benutzt, wie man umrechnet, was man hinter die Zahl
schreibt — ist Wissen, keine Daten, und lebt hier.

## Die drei Systeme

| Konstante | Wert | Was |
|---|---|---|
| `US` | 1 | Fahrenheit, Zoll, Meilen pro Stunde |
| `METRIC` | 16 | Celsius, Zentimeter, Kilometer pro Stunde |
| `METRICWX` | 17 | Celsius, Millimeter, Meter pro Sekunde |

`name(unit_system)` und `system_from(value, default=US)`. Letzteres nimmt Zahl
**oder** Name, weil beides in freier Wildbahn vorkommt: `usUnits = 1` in einem
Satz, `US` in einer Konfigurationsdatei.

## Der Fall, für den das existiert

Eine Konsole in Deutschland, die Fahrenheit meldet, und eine Seite in Celsius.

**Das Archiv behält, was die Station geschrieben hat.** Umgerechnet wird auf dem
Weg nach draußen. Das ist die Trennung, die `Target` verkörpert.

## Gruppen und Einheiten

```python
group_of(obs_type, aggregate=None, extra=None)   # -> "group_temperature"
unit_of(obs_type, unit_system, aggregate=None, extra=None)  # -> ("degree_C", "group_temperature")
```

`extra` ist, was ein **Treiber** beigetragen hat. Es gewinnt über die eingebaute
Tabelle: ein Treiber kennt seine eigenen Felder, und die Liste des Kerns ist nur
das Standardschema. → [Drivers](Drivers)

Manche Aggregate wechseln die Gruppe: `count` ist eine Anzahl, egal woraus,
`mintime` ist ein Zeitpunkt.

## Umrechnen

```python
convert(value, from_unit, to_unit)
convert_all(values, from_unit, to_unit)   # eine ganze Reihe
can_convert(from_unit, to_unit)           # ohne es zu tun
```

**`None` bleibt `None`.** Eine Lücke in den Messwerten sind nicht null Grad.

**Eine unbekannte Umrechnung wirft**, statt die Zahl unverändert
zurückzugeben — eine Temperatur, die still als Celsius etikettiert wird, während
sie Fahrenheit hält, ist genau der Fehler, den ein stiller Durchreicher
produziert.

Die Konstanten, wie WeeWX sie hat:

```python
INHG_PER_MBAR  = 0.0295299875
MM_PER_INCH    = 25.4
METER_PER_MILE = 1609.34
MILE_PER_KM    = 1000.0 / METER_PER_MILE
```

Die Umrechnungsfunktionen heißen wie im Original: `CtoF`, `FtoC`, `CtoK`,
`KtoC`, `KtoF`, `FtoK`, `FtoE`, `EtoF`, `CtoE`, `EtoC`, `mps_to_mph`,
`kph_to_mph`, `mps_to_knot`, `kph_to_knot`, `mph_to_knot`, `dublin_to_epoch`,
`epoch_to_dublin`.

## Beschriften und formatieren

```python
label(unit, plural=True)        # " °C" — mit führendem Leerzeichen
formatted(value, unit, with_label=False)
```

Ein paar Einheiten haben Singular und Plural (`1 day`, `2 days`), die meisten
nicht.

`formatted()` benutzt der JSON-Feed **nicht** — eine Maschine, die ihn liest,
will die Zahl. Aber ein Feed, der eine Seite schreibt, braucht es, und die
Nachkommastellen gehören neben die Beschriftungen statt verstreut durch
Templates.

## `Target` — was gezeigt wird

```python
target = units.Target(system="METRICWX",
                      overrides={"group_pressure": "inHg"})
values, unit, group = target.convert(values, "outTemp", source_system=US)
```

| Methode | Bedeutung |
|---|---|
| `unit(group)` | Worin diese Gruppe gezeigt wird |
| `for_obs(obs_type, aggregate, extra)` | Einheit und Gruppe für einen Messwert |
| `convert(values, obs_type, source_system, …)` | Eine Reihe aus der Datenbank in das, worin sie gezeigt werden soll |

`overrides` je Gruppe ist, wie jemand zu Grad Celsius und Zoll Quecksilber auf
einer Seite kommt — weil das ist, was seine Leser erwarten.

Der JSON-Feed konfiguriert genau das:

```toml
[feeds.json]
units = "METRICWX"

[feeds.json.unit]
group_pressure = "inHg"
```

→ [Settings-Reference](Settings-Reference#feed-json), [Feeds](Feeds)

## Prüfen

```bash
python tools/unitcheck.py
```

Prüft **alle 147 Umrechnungen** gegen WeeWX bei neun Werten
(`0, 1, -1, 7.5, 100, -40, 1013.25, 0.001, 98765.4321`), dazu Gruppen, Systeme,
Beschriftungen und Formate.

Der Test hat **drei echte Transkriptionsfehler** gefunden — die Knoten-Faktoren,
die geraten statt gelesen waren.

### Was der Test nebenbei dokumentiert

**WeeWX' Tabelle ist nicht selbstinvers.** `mph → kph` nimmt 1.609344,
`kph → mph` nimmt 1000/1609.34. **52 Paare kommen nicht exakt zurück.**

Das ist **absichtlich geerbt**. Der Test prüft, dass unsere Drift *ihre* Drift
ist, nicht dass es keine gibt. Eine „korrigierte" Konstante hier wäre ein
Diagramm, das von WeeWX' Diagramm desselben Tages abweicht — und das ist die
eine Sache, die dieses Projekt nicht tun darf.

<!-- covers
src/weewx_evo/units.py
tools/unitcheck.py
-->
