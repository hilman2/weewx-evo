# Units

`units.py`. What unit a reading is in, and what to call it.

> **`units.py` is a transcription of `weewx.units`, expression by expression.**
> Not recomputed: a "cleaner" rewritten factor is a plot that differs from WeeWX
> in the third decimal place, and finding out why costs an afternoon.

The database holds **one** unit system per record and says which in `usUnits`.
Everything else — which group a reading belongs to, which unit that group uses
in each system, how to convert, what to write after the number — is knowledge,
not data, and lives here.

## The three systems

| Constant | Value | What |
|---|---|---|
| `US` | 1 | Fahrenheit, inches, miles per hour |
| `METRIC` | 16 | Celsius, centimetres, kilometres per hour |
| `METRICWX` | 17 | Celsius, millimetres, metres per second |

`name(unit_system)` and `system_from(value, default=US)`. The latter takes a
number **or** a name, because both occur in the wild: `usUnits = 1` in a record,
`US` in a configuration file.

## The case this exists for

A console in Germany reporting Fahrenheit, and a page in Celsius.

**The archive keeps what the station wrote.** Conversion happens on the way out.
That is the separation `Target` embodies.

## Groups and units

```python
group_of(obs_type, aggregate=None, extra=None)   # -> "group_temperature"
unit_of(obs_type, unit_system, aggregate=None, extra=None)  # -> ("degree_C", "group_temperature")
```

`extra` is what a **driver** contributed. It wins over the built-in table: a
driver knows its own fields, and the core's list is only the default schema.
→ [Drivers](Drivers)

Some aggregates change group: `count` is a count, whatever it came from, and
`mintime` is a point in time.

## Converting

```python
convert(value, from_unit, to_unit)
convert_all(values, from_unit, to_unit)   # a whole series
can_convert(from_unit, to_unit)           # without doing it
```

**`None` stays `None`.** A gap in the readings is not zero degrees.

**An unknown conversion raises** instead of handing the number back
unchanged — a temperature quietly labelled Celsius while holding Fahrenheit is
exactly the bug a silent pass-through produces.

The constants, as WeeWX has them:

```python
INHG_PER_MBAR  = 0.0295299875
MM_PER_INCH    = 25.4
METER_PER_MILE = 1609.34
MILE_PER_KM    = 1000.0 / METER_PER_MILE
```

The conversion functions are named as in the original: `CtoF`, `FtoC`, `CtoK`,
`KtoC`, `KtoF`, `FtoK`, `FtoE`, `EtoF`, `CtoE`, `EtoC`, `mps_to_mph`,
`kph_to_mph`, `mps_to_knot`, `kph_to_knot`, `mph_to_knot`, `dublin_to_epoch`,
`epoch_to_dublin`.

## Labelling and formatting

```python
label(unit, plural=True)        # " °C" — with a leading space
formatted(value, unit, with_label=False)
```

A few units have a singular and a plural (`1 day`, `2 days`), most do not.

The JSON feed does **not** use `formatted()` — a machine reading it wants the
number. But a feed that writes a page needs it, and the decimal places belong
next to the labels rather than scattered through templates.

## `Target` — what gets shown

```python
target = units.Target(system="METRICWX",
                      overrides={"group_pressure": "inHg"})
values, unit, group = target.convert(values, "outTemp", source_system=US)
```

| Method | What it means |
|---|---|
| `unit(group)` | What this group is shown in |
| `for_obs(obs_type, aggregate, extra)` | Unit and group for a reading |
| `convert(values, obs_type, source_system, …)` | A series from the database into what it should be shown in |

`overrides` per group is how someone ends up with degrees Celsius and inches of
mercury on one page — because that is what their readers expect.

The JSON feed configures exactly that:

```toml
[feeds.json]
units = "METRICWX"

[feeds.json.unit]
group_pressure = "inHg"
```

→ [Settings-Reference](Settings-Reference#feed-json), [Feeds](Feeds)

## Checking it

```bash
python tools/unitcheck.py
```

Checks **every conversion in the table** against WeeWX, at nine values, plus
groups, systems, labels and formats. → [Testing](Testing#unitcheckpy--the-units)

The test found **three real transcription errors** — the knot factors, which had
been guessed rather than read.

### What the test documents along the way

**WeeWX's table is not self-inverse.** `mph → kph` uses 1.609344, `kph → mph`
uses 1000/1609.34. **52 pairs do not come back exactly.**

That is **inherited deliberately**. The test checks that our drift is *their*
drift, not that there is none. A "corrected" constant here would be a plot that
differs from WeeWX's plot of the same day — and that is the one thing this
project must not do.

<!-- covers
src/weewx_evo/units.py
tools/unitcheck.py
-->
