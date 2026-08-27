# Series

`series.py`. The equivalent of `weewx.xtypes.get_series()`, and what every feed
stands on.

Every feed wants the same thing: one reading, over a span, at some resolution.
Today's temperature every five minutes. This month's rain by day. A decade of
yearly maxima. Without it a feed can only report the last value.

## `Series`

```python
@dataclass
class Series:
    obs_type: str
    time: list[float]
    values: list[Any]
    start: list[float]
    stop: list[float]
    aggregate: str | None
    interval: int | str | None
    directions: list[Any] | None
```

**Two parallel arrays rather than a list of pairs**: around 30 % smaller once it
is JSON, and the shape every charting library wants.

`start` and `stop` bound each point. An aggregate belongs to a span, not to a
moment — a daily bar drawn on its timestamp sits in the wrong place on the plot.

| Method | What it means |
|---|---|
| `empty()` | Whether there is anything to draw. A series of nothing but nulls has not |
| `rounded(places=3)` | Round the values in place. **Never the timestamps** |

## `Reader`

```python
reader = Reader(connection, table="archive")
s = reader.series("outTemp", start, stop, aggregate="max", interval="day")
```

Holds a connection and nothing else — **no cache**, so nothing that could go
stale while the archiver writes into the same file.

| Method | What it means |
|---|---|
| `columns()` | The readings the archive table has a column for |
| `has_daily(obs_type)` | Whether there is a daily-summary table for it |
| `span()` | First and last record |
| `series(obs_type, start, stop, aggregate=None, interval=None)` | The main thing |
| `aggregate(obs_type, start, stop, how)` | **One** number for a span |
| `vector(obs_type, start, stop, how)` | A wind vector as `(magnitude, direction)` |
| `buckets(start, stop, interval)` | Which buckets a span falls into |

Without `aggregate` you get the archive records themselves. With one, the span
is cut into buckets and each is reduced to a number.

## The two routes to an aggregate

Choosing between them is most of what this file is.

### 1. From the daily summaries

`archive_day_outTemp` holds minimum, maximum, sum and weighted sum for every
day. **A month of daily maxima is 30 rows via the primary key** instead of a
month of archive records.

And they are the *better* extremes: taken from the live packets, so a gust
between two archive records is in there.

The prerequisite: the span falls on whole local days. `is_midnight(ts)` is
exactly that question — the daily summaries are indexed by it, so it is the
question of whether they can answer at all.

### 2. From the archive table

Everything that does not fall on days.

### `_NOT_THERE`

`_from_daily()` returns either a value, `None`, or the sentinel `_NOT_THERE`.
The difference matters:

| | |
|---|---|
| `_NOT_THERE` | The summaries **cannot** answer → ask the records |
| `None` | The answer **is** nothing |

## Days are days

A daily aggregate gets buckets on **local midnight**, not buckets of 86400
seconds from the start of the request. Months and years likewise.

A day is not always 86400 seconds. That is why it is walked in local time rather
than added up:

| | |
|---|---|
| `FIXED = {"hour": 3600, "week": 604800}` | Fixed lengths |
| `CALENDAR = ("day", "month", "year")` | Calendar units |
| `_floor(ts, unit)` | Start of the day, month or year |
| `_step(ts, unit, count=1)` | Forward by whole units, in local time |
| `_fixed(start, stop, interval)` | Fixed buckets, **stepped in local time** |

`_fixed` also steps in local time instead of adding seconds. That keeps the
boundaries on the same clock time across a daylight-saving change — which is
what WeeWX does and what a plot aligned to hour marks needs.

`buckets()` takes only calendar units that begin **inside** the span: a request
starting at nine in the morning does not get a day bucket that starts at
midnight and is only a quarter covered.

## The aggregates

```python
AGGREGATES = ("avg", "min", "max", "sum", "count", "first", "last",
              "firsttime", "lasttime", "mintime", "maxtime", "rms",
              "vecavg", "vecdir", …)
```

Plus the change aggregates via `_change()`: how far a reading moved over a span
and how fast.

**The starting point is the record *at or before* the beginning of the span**,
not the first one inside it. A meter that stood at 4 kWh when the week began did
not deliver 4 kWh that week.

## Wind

```python
VECTORS = {"windvec": ("windSpeed", "windDir"),
           "windgustvec": ("windGust", "windGustDir")}
WIND = {"max": "windGust", "maxtime": "windGust"}
```

The vector path is separate from the scalar one because averaging is a
**different operation**. The mean of an hour of northerly and an hour of
southerly wind is not a brisk wind, it is a calm — and that is exactly what
comes out when you add the components rather than the magnitudes.

| | |
|---|---|
| `_vector(magnitude, bearing)` | A wind reading as a vector, or nothing |
| `_bearing(x, y)` | The direction of a vector sum, in compass degrees |

A speed without a direction **is not a vector**: there is no arrow to draw and
no way to add it to another. WeeWX throws those away, and so does this. A speed
of zero is the exception.

`vector(obs_type, start, stop, how)`: `avg` and `sum` add the readings as
vectors. Every other aggregate picks **one** reading — the strongest, the first
— and reports its direction.

## One deliberate departure

**A mean here is always weighted by `interval`.**

WeeWX weights that way in the daily summaries, but uses a plain `AVG()` on the
archive table. In a database whose archive interval has changed, WeeWX therefore
contradicts **itself** — depending on which of the two routes a query takes.

Measured: `tools/seriestest.py`, 94 comparisons, 19,957 points, 0 failures,
8 known departures (exactly these).

## Checking it

```bash
python tools/seriestest.py reference/weewx.sdb
```

Asks WeeWX and weewx-evo for the same series and compares. `weewx.xtypes.
get_series` is what every WeeWX report stands on, and `weewx_evo.series` is what
every feed here stands on. If the two diverge, a plot drawn by weewx-evo shows a
different week of weather than the same plot from WeeWX — and that is the one
thing this project must not do.

The test needs an installed WeeWX and a real database. → [Testing](Testing)

<!-- covers
src/weewx_evo/series.py
tools/seriestest.py
-->
