# Weather forecast

What is coming, next to what has been.

A forecast is fetched from a service, kept in a file of its own beside the
archive, and printed by whatever page asks for it. It is **never written into
the archive**: the archive holds what was measured, and a forecast is somebody
else's guess about a place.

## Setting one up

**Publishing → Add a forecast**, and pick a source. Open-Meteo needs nothing
at all — no account, no key, and the coordinates come from the place.

```toml
forecast.openmeteo.kind = "open-meteo"
forecast.openmeteo.archive = "default"
```

| | |
|---|---|
| `open-meteo` | hours and days, worldwide, no account |
| `dwd` | the German service's own forecast for a station |
| `dwd-warnings` | its warnings for a region |
| `meteoalarm` | European warnings |
| `nws` | the United States |

A station id or a warning region is typed per entry: neither can be worked out
from a latitude. **Try it** on the entry's own page — a source that needs one
and has not been given one answers with the ones nearest to this station, which
is how you find yours.

## On the page

Deck prints it without further configuration: warnings first, then the days,
then the hours. Any skin can read it — `$forecast` answers hours, days,
warnings and which model run they came from.
→ [Forecast](Forecast#what-a-skin-can-write)

## One forecast per place

A forecast is an answer about a pair of coordinates, so it belongs to one
place. Two places want two entries, and a place with no entry gets no
forecast — never its neighbour's, which would be worse than none, because
nothing on the page could say so. → [Several places](Places)

## When the service is down

A fetch that fails leaves the last one in place and says so. The page goes on
printing what it has, with its age; it does not go blank because somebody's
API had a bad afternoon.

Two kinds of failure are kept apart: **could not reach it** and **reached it
and it said no**. The first passes, the second wants looking at.
→ [Forecast](Forecast#two-kinds-of-failure-and-they-are-not-the-same)

<!-- watches
src/weewx_evo/forecast/
-->
