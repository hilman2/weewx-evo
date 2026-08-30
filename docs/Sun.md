# Sun

`sun.py`. Where the sun is and when it rises.

Two things need it:

- **A reading.** `maxSolarRad` is what a sensor would see under a cloudless sky,
  and that depends on the elevation. → [Derived-Readings](Derived-Readings)
- **A plot.** The hours of darkness are shaded, because a temperature trace
  makes no sense without knowing which part of it was night. → [Feeds](Feeds)

pyephem when it is installed, and the arithmetic here when it is not — the same
arrangement WeeWX has (it falls back to `weeutil.Sun`).

## Accuracy

Measured against pyephem at six places from Tromsø to Ushuaia and at the four
turning points of the year:

| | |
|---|---|
| Declination | to 0.002° |
| Sunrise | to 37 seconds |

`weeutil.Sun`, WeeWX's own fallback, is out by up to **6.5 minutes** over the
same cases.

A minute out is invisible. Ten minutes out is a band that visibly does not match
the falling temperature trace.

## The functions

| | |
|---|---|
| `solar(when)` | Declination (degrees), equation of time (minutes), distance to the sun (AU). NOAA's algorithm |
| `position(when, lat, lon, alt_m)` | Elevation in degrees and distance in AU |
| `solar_noon(when, longitude)` | When the sun stands highest |
| `crossings(day_ts, lat, lon, angle=HORIZON)` | When the sun passes an elevation going up and going down |
| `events(day_ts, lat, lon)` | Rise, set and the civil twilight around them |
| `day_night(start, stop, lat, lon)` | What a plot needs in order to shade |
| `local_midnight(ts)` | Start of the local day |
| `describe(day_ts, lat, lon)` | A day of sun as a line somebody reads. For the CLI |

```python
HORIZON = -0.833   # upper limb, with refraction
CIVIL   = -6.0     # civil twilight
```

`solar_noon` corrects twice against clock time: how far east or west of its
zone's meridian the observer is, and the equation of time — up to a quarter of
an hour.

`day_night()` returns what the span begins with (`day` or `night`), every
horizon crossing in it, and the stretches of twilight around them. `None` where
nothing happens — polar day and polar night.

## Two pitfalls, both of them real

### pyephem computes refraction itself

Giving it `horizon = -0.833` counts refraction and the solar radius **twice** —
four to five minutes, a night band that visibly does not match the falling
temperature trace.

Correct:

```python
observer.pressure = 0
observer.horizon = "-0:34"
ephem.Sun(), use_center=False    # upper limb
```

### A day is the sun's day, not the calendar's

In Wellington solar noon falls 20 minutes **after** UTC midnight. Anchored to a
calendar date, you pair one morning's sunrise with the previous evening's
sunset.

That is why both times in `crossings()` lie around the solar noon nearest the
given moment — not around midnight.

## Twilight is not an edge

The light goes over the half hour of civil twilight, and at high latitudes in
summer over far longer. That is why `day_night()` hands back the twilight
stretches: a plot can draw the real thing rather than a step.

Costs a few hundred bytes per file, and can be turned off with
`feeds.json.twilight`.

## Checking it

```bash
python tools/suncheck.py
```

Six places × five days, against pyephem **and** against WeeWX's fallback:

```python
PLACES = [("Kirchdorf", 52.0, 9.0), ("Seattle", 47.6, -122.3),
          ("Tromso", 69.65, 18.96), ("Quito", -0.18, -78.47),
          ("Wellington", …), ("Ushuaia", …)]
DAYS = ["2026-03-20", "2026-06-21", "2026-09-22", "2026-12-21", "2026-08-26"]
TOLERANCE = 60.0    # seconds
```

There are three answers and they are not equally good:

- **pyephem** is the accurate one, and the one WeeWX takes when it is there. It
  is the reference here.
- **`weewx_evo.sun`'s formula** is the one used when pyephem is missing.
- **`weeutil.Sun`** is WeeWX's fallback, and the least accurate.

`apart()` works out how far two moments are from each other taking the day they
land in into account: `weeutil.Sun` returns hours relative to a UTC day, so a
sunset in Seattle comes out as 02:27 the following day. Compared directly that
would be a whole day of difference.

→ [Testing](Testing)

<!-- covers
src/weewx_evo/sun.py
tools/suncheck.py
src/weewx_evo/moon.py
src/weewx_evo/planets.py
src/weewx_evo/vsop87.py
-->
