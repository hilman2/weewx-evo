# Derived readings

`derive.py`. Readings that follow from other readings.

A station measures temperature, humidity, pressure and wind. Dewpoint, wind
chill, apparent temperature and cloud base follow from those by arithmetic, and
most consoles do not send them. WeeWX calls this `StdWXCalculate`; without it a
database ends up with a `dewpoint` column that stays empty for years.

**One of them is not a convenience but a measurement**: `rain`. See
[below](#the-one-that-is-a-measurement).

## The formulas

All checked against WeeWX, not against the literature — see
[Checking it](#checking-it).

| Function | What |
|---|---|
| `dewpoint_c(t_c, rh)` | Dewpoint, Magnus formula as in WeeWX |
| `windchill_c(t_c, v_kph)` | Environment Canada formula. Defined only below 10 °C and above 4.8 km/h; outside that it is the temperature itself, which is what WeeWX returns |
| `heatindex_f(t_f, rh)` | Rothfusz with the two corrections. Below 40 °F there is no heat index, and the temperature comes back |
| `humidex_c(t_c, rh)` | Below 21 °C it is the temperature |
| `apptemp_c(t_c, rh, wind_mps)` | Apparent temperature, Australian BOM formula |
| `altimeter_inhg(pressure_inhg, altitude_ft)` | Altimeter setting from station pressure, aaASOS algorithm |
| `cloudbase_ft(t_f, rh, altitude_ft)` | Cloud base from the spread |
| `max_solar_rad(lat, lon, alt_m, when, atc=0.8)` | Clear-sky radiation, W/m², Ryan-Stolzenbach (MIT, 1972) |
| `windrun(speed, seconds)` | The distance the wind travelled. Speed times time — the unit follows the speed, which is why nothing is converted here |
| `delta(now, before, name)` | How much a running total has gone up by |
| `sun_position(when, lat, lon, alt_m)` | Elevation and distance to the sun. pyephem if installed, NOAA otherwise — the same arrangement as in WeeWX |

`SOLAR_CONSTANT = 1367.0`.

### Why `max_solar_rad` is computed at all

It is what a solar sensor would read under a cloudless sky. Held against a
measured value, it is what says how cloudy it was — which is why the computation
is worth it even for a station that has a sensor.

## `Deriver`

```python
station = Station(latitude=48.4596, longitude=11.6539, altitude_m=440.0)
deriver = Deriver(station=station, how={...})
record = deriver.apply(record)
```

The object holds **one** piece of state: the last value of every running total,
so that a difference can be taken. That state is exactly why it is an object and
not a function.

| Method | What it means |
|---|---|
| `wanted(name, record)` | Whether this value is computed for this record |
| `apply(record)` | Fill in what is missing. The record is modified and returned |
| `forget()` | Forget the running totals. The next packet takes no difference |

`from_settings(settings)` builds one from the resolved configuration.

### The order matters

`apply()` computes **dewpoint before cloud base**, because the latter follows
from the former. Written out rather than resolved from a dependency graph: there
are eight values, and a graph would be more code than the order.

### The three policies

`HOW = ("prefer_hardware", "hardware", "software")` — WeeWX's `StdWXCalculate`.

| | |
|---|---|
| `prefer_hardware` | Take what the console sends; compute when it sends nothing. The default |
| `hardware` | Only what the console sends |
| `software` | Always compute it ourselves, even when the console sends something |

Settable per reading.

## The one that is a measurement

`delta(now, before, name="rain")`. Ecowitt hardware sends **running totals**
(`totalrain`, `dailyrain`), not what has fallen since the last packet. `rain` is
the difference.

Three cases that are not errors and must not be treated as such:

| Case | Why it is not an error | What happens |
|---|---|---|
| **No previous value** — the first packet after a start | There is no difference. Inventing one would book the entire total so far as rain in that minute | Nothing is booked |
| **The total has gone down** | A counter overflow or a reset at midnight | The new value itself, not a negative number |
| **The total is standing still** | It has not rained | `0`, not `None` |

The first case is the one that ruins a record silently: a restart after a wet
month, and the statistics have an 84 mm shower lasting a second.

`_remember()` holds the last values. `forget()` throws them away — which is the
right thing after an outage, because a difference across an unknown gap is not a
statement.

## Checking it

```bash
python tools/derive_test.py reference/weewx.sdb
```

The reference database has years of records in which WeeWX computed dewpoint,
heat index and the rest from readings that are **in the same row**. That makes
it a test oracle nobody had to write: recompute from the same row and compare.

These formulas decide numbers that go into a database WeeWX reads again.
**Agreeing with WeeWX counts for more here than being right in the abstract.**

The test additionally checks:

- `rain_tests()` — the case that is a measurement
- `policy_tests()` — the three policies
- `edge_tests()` — the edges of the domains

→ [Testing](Testing), [Sun](Sun), [Units](Units)

<!-- covers
src/weewx_evo/derive.py
tools/derive_test.py
-->
