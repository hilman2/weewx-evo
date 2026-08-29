"""Flux, generated from a plot definition.

The file that decides whether Grafana agrees with the station's own pages.

**Flux rather than InfluxQL**, for two reasons and one of them is not
fashion. InfluxQL needs a DBRP mapping before it can see an InfluxDB 2
bucket, which is a step nobody expects and which fails as "no measurements
found". And an average weighted by the archive interval is expressible in
Flux and not in InfluxQL -- see below for how much that matters here.

**One field per query, and the tag does the rest.** A Flux query that filters
on `_field == "outTemp"` and says nothing about `location` returns one series
per location, already grouped, because Flux carries tags through. That is the
whole reason this upload exists: five places on one axis is a query with a
filter *left out* rather than five queries.

## The weighting, and where it stops being exact

Every mean in this project is weighted by `interval` (`aggregate.py`,
`series.py`), because a database whose archive interval changed from ten
minutes to five is a database where an unweighted mean over the boundary is
wrong -- and WeeWX contradicts itself there, using a weighted mean in the
daily summaries and a plain `AVG()` on the archive table.

`weighted()` writes the Flux for the weighted form. It costs a pivot and two
windows, so it is not the default: it is used where the archive says it is
needed. `intervals_in()` asks the database rather than guessing, and an
archive with a single interval throughout -- which is almost all of them --
gets the plain `mean()` that is exactly equal to it.

An extreme needs none of this: `max` of a bucket is `max` however long the
records in it were.
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import closing
from pathlib import Path

log = logging.getLogger(__name__)

#: What a plot's `aggregate` is called in Flux. `mean` is the default for a
#: line with none: Grafana asks for a window sized to the pixels available,
#: and without one a year of five-minute records is 105,000 points down the
#: wire to draw a chart 800 pixels wide.
FUNCTIONS = {
    "": "mean",
    "avg": "mean",
    "mean": "mean",
    "min": "min",
    "max": "max",
    "sum": "sum",
    "count": "count",
    "last": "last",
    "first": "first",
}

#: The aggregates a changed archive interval does not affect. A maximum is the
#: largest reading in the bucket whether it stood for five minutes or ten.
EXACT_WITHOUT_WEIGHTS = ("min", "max", "first", "last", "count")

#: What comes back: one value, one time, and the tag that says which station.
#:
#: Not a tidy-up. Flux carries every column through and Grafana turns each one
#: into a series named after all the others -- so the weighted query drew its
#: own `_sum` and `_weight` on the temperature axis, sending it to 80 °C, and
#: every legend read `_product {_start="2026-08-28 12:22:52 +0000 UTC",
#: _stop=...}`. Humidity was worse: its extra series sat far above the fixed
#: 0-100 axis, so the real line was flattened against the top and looked like
#: a sensor stuck at 100 %.
#:
#: Found on a real dashboard. Nothing in the JSON says it is about to happen,
#: and no check of the query text would have caught it.
KEEP = ['  |> keep(columns: ["_time", "_value", "location"])']


def escape(text: str) -> str:
    """A string inside a Flux literal.

    Flux takes double quotes and backslash escapes. A location called
    `Kirchdorf "old"` is unlikely and free to survive.
    """
    return str(text).replace("\\", "\\\\").replace('"', '\\"')


def intervals_in(archive: str | Path) -> list[int]:
    """The distinct archive intervals in a database, oldest usage first.

    Measured rather than assumed. One interval means `mean()` and the
    project's weighted average are the same number, so the simple query is
    also the correct one; more than one means they are not, and the operator
    should be told rather than shown two charts that quietly disagree.

    An unreadable database returns nothing -- this is a report, not a
    precondition, and a provisioning run must not fail because the archive is
    on another machine.
    """
    try:
        # `closing` as well: a connection's context manager commits the
        # transaction and leaves the connection open.
        with closing(sqlite3.connect(f"file:{Path(archive)}?mode=ro",
                                     uri=True)) as conn:
            rows = conn.execute(
                "SELECT DISTINCT interval FROM archive "
                "WHERE interval IS NOT NULL ORDER BY interval").fetchall()
    except sqlite3.Error as exc:
        log.debug("could not read the intervals from %s: %s", archive, exc)
        return []
    return [int(row[0]) for row in rows if row[0]]


def _head(bucket: str, measurement: str, field: str,
          location: str = "") -> list[str]:
    """The part every query starts with: bucket, range, measurement, field."""
    lines = [
        f'from(bucket: "{escape(bucket)}")',
        "  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)",
        f'  |> filter(fn: (r) => r._measurement == "{escape(measurement)}")',
    ]
    if location:
        # Named only where one series is wanted. Leaving it out is what draws
        # every location on the same axis.
        lines.append(f'  |> filter(fn: (r) => r.location == "{escape(location)}")')
    lines.append(f'  |> filter(fn: (r) => r._field == "{escape(field)}")')
    return lines


def plain(bucket: str, measurement: str, field: str, aggregate: str = "",
          location: str = "") -> str:
    """One reading, aggregated the ordinary way."""
    function = FUNCTIONS.get(aggregate, "mean")
    lines = _head(bucket, measurement, field, location)
    lines.append(f"  |> aggregateWindow(every: v.windowPeriod, fn: {function}, "
                 f"createEmpty: false)")
    lines += KEEP
    lines.append(f'  |> yield(name: "{escape(field)}")')
    return "\n".join(lines)


def weighted(bucket: str, measurement: str, field: str,
             location: str = "") -> str:
    """A mean weighted by `interval`, which is what this project computes.

    Only for a database whose archive interval has changed. The shape is: read
    the reading and the interval together, pivot them onto one row, then sum
    the products *and* the weights in a single pass over each window, and
    divide.

    **The single pass is the whole difficulty.** The obvious version --
    `map` the product, then `aggregateWindow(fn: sum)` and divide by the
    weight -- returns nothing at all, and it took running it against a real
    InfluxDB to find out: `aggregateWindow` keeps the grouping columns and
    the one column it aggregated, so `_weight` is gone by the time the
    division asks for it. The row is dropped, every row is dropped, and the
    panel is empty with no error anywhere. `reduce` carries both because it
    builds the record itself.

    Two windows and a `join` would also work and is worse: the two would be
    windowed separately, and a bucket that is empty in one and not the other
    silently drops a point.
    """
    lines = [
        f'from(bucket: "{escape(bucket)}")',
        "  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)",
        f'  |> filter(fn: (r) => r._measurement == "{escape(measurement)}")',
    ]
    if location:
        lines.append(f'  |> filter(fn: (r) => r.location == "{escape(location)}")')
    lines += [
        (f'  |> filter(fn: (r) => r._field == "{escape(field)}" or '
         f'r._field == "interval")'),
        ('  |> pivot(rowKey: ["_time"], columnKey: ["_field"], '
         'valueColumn: "_value")'),
        # A record with no interval cannot be weighted, and dropping it is
        # better than weighting it as one: an archive predating the column
        # would otherwise pull every average towards its own readings.
        f'  |> filter(fn: (r) => exists r.{field} and exists r.interval)',
        (f'  |> aggregateWindow(every: v.windowPeriod, createEmpty: false, '
         f'column: "{escape(field)}",'),
        "       fn: (column, tables=<-) => tables |> reduce(",
        "         identity: {_sum: 0.0, _weight: 0.0},",
        "         fn: (r, accumulator) => ({",
        f"           _sum: accumulator._sum + r.{field} * r.interval,",
        "           _weight: accumulator._weight + r.interval,",
        "         })))",
        # A window whose records all had a zero interval would divide by zero
        # and produce an infinity, which Grafana draws as a spike to the edge
        # of the panel.
        "  |> filter(fn: (r) => r._weight > 0.0)",
        "  |> map(fn: (r) => ({ r with _value: r._sum / r._weight }))",
        *KEEP,
        f'  |> yield(name: "{escape(field)}")',
    ]
    return "\n".join(lines)


def for_line(bucket: str, measurement: str, field: str, aggregate: str = "",
             location: str = "", weight: bool = False) -> str:
    """The query for one line of a plot.

    `weight` comes from the archive, not from an opinion: see `intervals_in`.
    An aggregate that a changed interval cannot affect ignores it.
    """
    if weight and aggregate.lower() in ("", "avg", "mean"):
        return weighted(bucket, measurement, field, location)
    if aggregate.lower() in EXACT_WITHOUT_WEIGHTS or not weight:
        return plain(bucket, measurement, field, aggregate, location)
    return plain(bucket, measurement, field, aggregate, location)


def last_seen(bucket: str, measurement: str, field: str = "outTemp") -> str:
    """How long ago each location last wrote anything.

    The one operational question that needs no `/metrics` endpoint: a station
    that has stopped is a location whose newest point is old. In seconds, so a
    panel can colour it.
    """
    return "\n".join([
        f'from(bucket: "{escape(bucket)}")',
        "  |> range(start: -7d)",
        f'  |> filter(fn: (r) => r._measurement == "{escape(measurement)}")',
        f'  |> filter(fn: (r) => r._field == "{escape(field)}")',
        "  |> last()",
        ('  |> map(fn: (r) => ({ r with _value: (float(v: uint(v: now())) '
         '- float(v: uint(v: r._time))) / 1000000000.0 }))'),
        '  |> keep(columns: ["location", "_value"])',
        '  |> yield(name: "age")',
    ])


def locations(bucket: str, measurement: str) -> str:
    """The locations there are, for a dashboard variable.

    Read from the data rather than written into the dashboard: a station
    added next month appears in the list without anybody regenerating
    anything, which is the property that makes one dashboard serve n consoles.
    """
    return "\n".join([
        'import "influxdata/influxdb/schema"',
        (f'schema.tagValues(bucket: "{escape(bucket)}", tag: "location", '
         f'predicate: (r) => r._measurement == "{escape(measurement)}", '
         f'start: -30d)'),
    ])
