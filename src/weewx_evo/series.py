"""Time series out of the archive.

Every feed needs the same thing: a reading, over a span, at some resolution.
Today's temperature every five minutes. This month's rainfall by day. A decade
of yearly maxima. WeeWX calls this `xtypes.get_series`, and without it a feed
can only report the latest value.

Two ways of getting an aggregate, and choosing between them is most of what
this file does:

**From the daily summaries.** `archive_day_outTemp` already holds the minimum,
maximum, sum and weighted sum for every day. A month of daily maxima is thirty
rows read by primary key. This is what those tables are for, and it is why
weewx-evo maintains them so carefully. They also hold the *better* extremes:
those were recorded from the live packets, so a gust between two archive
records is in there, and a maximum recomputed from the archive alone is duller.

**From the archive table.** Anything not aligned to a day -- hourly, or six
hours, or fifteen minutes -- has to be worked out from the records. A year of
hourly averages is a hundred thousand rows, which SQLite does in well under a
second, and there is no cache worth the trouble of invalidating.

## Days are days

Ask for a daily aggregate and you get days: buckets on local midnight, not
buckets of 86400 seconds measured from whenever the span happened to start.
That is what a daily maximum means, it is what the summary tables are keyed
by, and it is what WeeWX does. A span that begins mid-day contributes no
partial first bucket, again as in WeeWX -- half a day of rain drawn beside
whole days is a lie about a dry morning.

Months and years work the same way and are not a fixed number of seconds. A
day is not always 86400 seconds either, which is why the walk is done in local
time and not by adding.

## One deliberate difference from WeeWX

An average here is always weighted by each record's `interval`. WeeWX weights
it that way in the daily summaries but uses a plain `AVG()` when it works from
the archive table, so in a database whose archive interval has changed, WeeWX
disagrees with itself: its daily average and its hourly averages weight the
same readings differently. The two agree everywhere the interval is constant,
which is every station that has not been reconfigured. Where they do not, this
is the answer the daily summaries would give.
"""

from __future__ import annotations

import datetime
import logging
import math
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from . import units

log = logging.getLogger(__name__)

#: What degree days are counted from. WeeWX's defaults, and the numbers the
#: convention is written in -- 65 F is not 18 C, and a "tidier" base here is
#: a different measurement. A skin may name its own.
DEGREE_DAY_BASES = {"heatdeg": (65.0, "degree_F"),
                    "cooldeg": (65.0, "degree_F"),
                    "growdeg": (50.0, "degree_F")}

#: What can be asked for. The names are WeeWX's, so a plot definition that
#: worked there works here.
AGGREGATES = ("avg", "min", "max", "sum", "count", "first", "last",
              "firsttime", "lasttime", "mintime", "maxtime", "rms",
              "vecavg", "vecdir", "gustdir", "diff", "tderiv", "not_null")

#: Named intervals that are a fixed number of seconds, stepped from the start
#: of the span. WeeWX treats them the same way -- a 'week' is 604800 seconds
#: from wherever you began, not a calendar week beginning on Monday.
FIXED = {"hour": 3600, "week": 604800}

#: Named intervals that follow the calendar.
CALENDAR = ("day", "month", "year")

#: `wind` is not a column. It is the pair of columns, and which one is meant
#: depends on the question: the highest wind of a day is the highest gust.
WIND = {"max": "windGust", "maxtime": "windGust"}

#: Nor are these. A wind vector is a speed *and* a bearing, and a chart that
#: draws arrows needs both at every point. WeeWX carries them as one complex
#: number; here they stay two parallel arrays, which is what survives being
#: written to JSON.
VECTORS = {
    "windvec": ("windSpeed", "windDir"),
    "windgustvec": ("windGust", "windGustDir"),
}


@dataclass
class Series:
    """One reading over one span.

    Two parallel arrays rather than a list of pairs: about 30% smaller once it
    is JSON, and the shape every charting library wants.

    `start` and `stop` bound each point. An aggregate belongs to a span, not
    to an instant -- a daily maximum drawn at midnight is drawn in the wrong
    place, and a chart that shades a bar needs to know how wide the bar is.
    """

    obs_type: str
    time: list[float] = field(default_factory=list)
    values: list[Any] = field(default_factory=list)
    start: list[float] = field(default_factory=list)
    stop: list[float] = field(default_factory=list)
    aggregate: str | None = None
    interval: int | str | None = None
    #: Compass degrees, for the wind vector readings. None for everything
    #: else, because a temperature does not point anywhere. Where it is
    #: filled, `values` holds the magnitudes.
    directions: list[Any] | None = None

    def __len__(self) -> int:
        return len(self.values)

    @property
    def empty(self) -> bool:
        """Whether there is anything to draw. An all-null series is not."""
        return not any(v is not None for v in self.values)

    def rounded(self, places: int | None = 3) -> Series:
        """Round the values in place and return self.

        Three decimals is well past any weather sensor's resolution and takes
        about a third off the size of the JSON. Timestamps are never rounded.
        """
        if places is not None:
            self.values = [v if not isinstance(v, float) else round(v, places)
                           for v in self.values]
            if self.directions is not None:
                # One decimal is already finer than any wind vane.
                self.directions = [
                    v if not isinstance(v, float) else round(v, 1)
                    for v in self.directions]
        return self


class Reader:
    """Reads series from one archive database.

    Holds a connection and nothing else -- no cache, and so nothing that could
    go stale while the archiver writes to the same file.
    """

    def __init__(self, connection: sqlite3.Connection,
                 table: str = "archive") -> None:
        self.conn = connection
        self.table = table
        self._daily: set[str] | None = None
        self._columns: set[str] | None = None
        self._system: int | None = None

    # -- what the database has -------------------------------------------

    @property
    def columns(self) -> set[str]:
        """The readings the archive table has a column for."""
        if self._columns is None:
            self._columns = {
                row[1] for row in
                self.conn.execute(f"PRAGMA table_info({self.table})")}
        return self._columns

    @property
    def system(self) -> int:
        """Which unit system the archive holds. US, METRIC or METRICWX.

        Taken from the first record, which is what WeeWX's manager does. A
        database whose station changed system mid-life is already mixed, and
        picking a different record here would only move which half is wrong.
        """
        if self._system is None:
            row = self.conn.execute(
                f"SELECT usUnits FROM {self.table} ORDER BY dateTime LIMIT 1"
            ).fetchone()
            self._system = int(row[0]) if row and row[0] is not None                 else units.US
        return self._system

    def has_daily(self, obs_type: str) -> bool:
        """Whether there is a daily summary table for this reading."""
        if self._daily is None:
            prefix = f"{self.table}_day_"
            self._daily = {
                name[len(prefix):] for (name,) in self.conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                    " AND name LIKE ? || '%'", (prefix,))
                if not name.endswith("__metadata")
            }
        return obs_type in self._daily

    def span(self) -> tuple[int, int] | None:
        """The first and last record in the archive, or None if it is empty.

        Two queries, not one, and that is the whole point. SQLite answers
        `MIN(dateTime)` or `MAX(dateTime)` from the primary key without
        reading a row; asked for both in one statement it gives up on the
        index and scans the table.

        Measured on ten years, a million records:

            SELECT MIN(dateTime), MAX(dateTime)   52.94 ms   SCAN archive
            SELECT MIN(dateTime)                   0.01 ms
            SELECT MAX(dateTime)                   0.00 ms

        A page asks for `$alltime` once per tile, so the statistics page
        called this 354 times: nineteen seconds of a twenty-three second
        render, spent finding out something the file knew instantly.
        """
        first = self.conn.execute(
            f"SELECT MIN(dateTime) FROM {self.table}").fetchone()
        if not first or first[0] is None:
            return None
        last = self.conn.execute(
            f"SELECT MAX(dateTime) FROM {self.table}").fetchone()
        return int(first[0]), int(last[0])

    # -- the entry point -------------------------------------------------

    def series(self, obs_type: str, start: float, stop: float,
               aggregate: str | None = None,
               interval: int | str | None = None) -> Series:
        """A reading over a span.

        With no aggregate, the archive records themselves. With one, the span
        is cut into buckets and each is reduced to a number.

        `interval` is a number of seconds, or one of 'hour', 'day', 'week',
        'month', 'year'. Days, months and years follow the calendar; the
        others are counted from the start of the span.
        """
        if obs_type in VECTORS:
            return self._vector_series(obs_type, start, stop, aggregate,
                                       interval)
        if aggregate is None:
            return self._records(obs_type, start, stop)

        aggregate = aggregate.lower()
        if aggregate not in AGGREGATES:
            raise ValueError(f"{aggregate!r} is not an aggregate. One of: "
                             f"{', '.join(AGGREGATES)}")

        spans = list(self.buckets(start, stop, interval or "day"))
        # Every bucket at once out of the daily summaries, where they can
        # answer it. None means they cannot, and then it is one query per
        # bucket as below.
        whole = self._daily_series(obs_type, aggregate, spans, interval)
        if whole is not None:
            return whole

        out = Series(obs_type=obs_type, aggregate=aggregate, interval=interval)
        for begin, end in spans:
            out.time.append(end)
            out.values.append(self.aggregate(obs_type, begin, end, aggregate))
            out.start.append(begin)
            out.stop.append(end)
        return out

    def aggregate(self, obs_type: str, start: float, stop: float,
                  how: str,
                  bases: dict[str, tuple[float, str]] | None = None) -> Any:
        """One number for one span.

        Answered from the daily summaries when the span is whole days and they
        hold that aggregate -- thirty rows read by key instead of a month of
        records, and the extremes are the ones the live packets saw.
        """
        if obs_type in DEGREE_DAY_BASES:
            return self.degree_days(obs_type, start, stop, how, bases)
        if obs_type in VECTORS:
            # `windvec` is not a column: it is a speed and a direction, and
            # `series()` knows how to put them together. One number out of a
            # pair of columns is the speed -- whether there is a wind vector
            # to draw is whether there is a wind speed, and the highest wind
            # of a day is the highest speed whichever way it blew.
            #
            # Without this a template asking `check_for_data('windvec')` got
            # nothing back and left the chart off the page, while the file
            # sat there drawn and correct.
            obs_type = VECTORS[obs_type][0]
        if stop > start and is_midnight(start) and is_midnight(stop) \
                and self.has_daily(obs_type):
            value = self._from_daily(obs_type, start, stop, how)
            if value is not _NOT_THERE:
                return value
        return self._from_records(obs_type, start, stop, how)

    # -- degree days -----------------------------------------------------

    def degree_days(self, obs_type: str, start: float, stop: float,
                    how: str,
                    bases: dict[str, tuple[float, str]] | None = None) -> Any:
        """Heating, cooling and growing degree days over a span.

        Not a column and never was: a count of how far each day's mean
        temperature sat from a base, added up. Transcribed from
        `weewx.xtypes.AggregateHeatCool`, including the two things about it
        that are easy to get wrong -- it walks whole calendar days whatever
        the span's own edges are, and a day with no temperature is left out
        of both the total and the count rather than counted as zero.
        """
        if how not in ("sum", "avg", "not_null"):
            # A total and a mean are the only two that mean anything: the
            # maximum of a set of degree days is a day, not a measurement.
            raise ValueError(f"{how} is not an aggregate for {obs_type}")
        amount, unit = (bases or {}).get(obs_type, DEGREE_DAY_BASES[obs_type])
        # The base is written in whatever unit its author used, and the day
        # means come out of the database in whatever the station wrote.
        stored, _ = units.unit_of("outTemp", self.system)
        base = units.convert(float(amount), unit, stored)

        total, count = 0.0, 0
        for begin, end in _day_spans(start, stop):
            mean = self.aggregate("outTemp", begin, end, "avg")
            if mean is None:
                continue
            if how == "not_null":
                return True
            if obs_type == "heatdeg":
                total += max(base - mean, 0)
            else:
                total += max(mean - base, 0)
            count += 1

        if how == "not_null":
            return False
        if how == "sum":
            return total
        return total / count if count else None

    # -- raw records -----------------------------------------------------

    def _records(self, obs_type: str, start: float, stop: float) -> Series:
        """Every archive record in the span, unaggregated."""
        out = Series(obs_type=obs_type)
        column = "windSpeed" if obs_type == "wind" else obs_type
        if column not in self.columns:
            # A feed asking for a sensor this station has never had should
            # draw nothing, not fail.
            log.debug("no column %r in %s", column, self.table)
            return out

        for ts, value, minutes in self.conn.execute(
                f'SELECT dateTime, "{column}", interval FROM {self.table}'
                " WHERE dateTime > ? AND dateTime <= ? ORDER BY dateTime",
                (start, stop)):
            out.time.append(ts)
            out.values.append(value)
            # A record covers the interval that ends at its timestamp.
            out.start.append(ts - (minutes or 0) * 60)
            out.stop.append(ts)
        return out

    # -- wind vectors ----------------------------------------------------

    def _vector_series(self, obs_type: str, start: float, stop: float,
                       aggregate: str | None,
                       interval: int | str | None) -> Series:
        """A wind vector over a span: magnitudes and bearings together.

        Kept apart from the scalar path because averaging them is a different
        operation. The mean of an hour of northerly and an hour of southerly
        wind is a strong wind by the speeds and no wind at all by the vectors,
        and only the second one says where the air actually went.
        """
        magnitude, bearing = VECTORS[obs_type]
        out = Series(obs_type=obs_type, aggregate=aggregate,
                     interval=interval, directions=[])
        if not {magnitude, bearing} <= self.columns:
            return out

        if aggregate is None:
            # `>` and not `>=`. WeeWX uses `>=` here and `>` for every other
            # series, so a wind vector drawn beside a temperature over the
            # same span has one more point than it does, at a different time.
            # That is a slip rather than a decision, and copying it would put
            # one function in this file at odds with the rest of it.
            for ts, mag, direction, minutes in self.conn.execute(
                    f'SELECT dateTime, "{magnitude}", "{bearing}", interval'
                    f" FROM {self.table}"
                    " WHERE dateTime > ? AND dateTime <= ? ORDER BY dateTime",
                    (start, stop)):
                mag, direction = _vector(mag, direction)
                out.time.append(ts)
                out.values.append(mag)
                out.directions.append(direction)
                out.start.append(ts - (minutes or 0) * 60)
                out.stop.append(ts)
            return out

        aggregate = aggregate.lower()
        for begin, end in self.buckets(start, stop, interval or "day"):
            mag, direction = self.vector(obs_type, begin, end, aggregate)
            out.time.append(end)
            out.values.append(mag)
            out.directions.append(direction)
            out.start.append(begin)
            out.stop.append(end)
        return out

    def vector(self, obs_type: str, start: float, stop: float,
               how: str) -> tuple[float | None, float | None]:
        """One wind vector for one span, as (magnitude, bearing).

        `avg` and `sum` add the readings as vectors. Every other aggregate
        picks one reading -- the strongest, the first -- and reports the
        bearing that came with it, which is the only bearing that means
        anything for a single gust.
        """
        magnitude, bearing = VECTORS[obs_type]
        window = (f"FROM {self.table} WHERE dateTime > ? AND dateTime <= ?"
                  f' AND "{magnitude}" IS NOT NULL')
        args = (start, stop)

        picks = {
            "min": f'ORDER BY "{magnitude}" ASC LIMIT 1',
            "max": f'ORDER BY "{magnitude}" DESC LIMIT 1',
            "first": "ORDER BY dateTime ASC LIMIT 1",
            "last": "ORDER BY dateTime DESC LIMIT 1",
        }
        try:
            if how in picks:
                row = self.conn.execute(
                    f'SELECT "{magnitude}", "{bearing}" {window} {picks[how]}',
                    args).fetchone()
                return _vector(row[0], row[1]) if row else (None, None)

            if how in ("count", "not_null"):
                row = self.conn.execute(
                    f"SELECT COUNT(dateTime) {window}", args).fetchone()
                count = int(row[0]) if row and row[0] is not None else 0
                return (bool(count) if how == "not_null" else count), None

            if how not in ("avg", "sum"):
                return None, None

            if how == "avg" and obs_type == "windvec" and stop > start \
                    and is_midnight(start) and is_midnight(stop) \
                    and self.has_daily("wind"):
                # The daily summaries hold the wind vector already, summed
                # over the live packets rather than the archive records. They
                # divide by `dirsumtime` -- the time a direction was actually
                # known -- where the record path below divides by the number
                # of readings. Different answers from different data, and this
                # is the better one, which is why WeeWX prefers it too.
                row = self.conn.execute(
                    f"SELECT SUM(xsum), SUM(ysum), SUM(dirsumtime)"
                    f" FROM {self.table}_day_wind"
                    " WHERE dateTime >= ? AND dateTime < ?", args).fetchone()
                if row and None not in row and row[2]:
                    x, y = row[0] / row[2], row[1] / row[2]
                    return math.sqrt(x ** 2 + y ** 2), _bearing(x, y)
                return None, None

            # Added as vectors, in Python rather than SQL: a reading with a
            # speed and no direction still counts towards the average even
            # though it contributes nothing to the sum, and that distinction
            # does not survive a GROUP BY. WeeWX divides by the number of
            # readings here, not by their combined interval -- unlike
            # `vecavg`, which is the same idea done the other way.
            xsum = ysum = 0.0
            count = 0
            for mag, direction in self.conn.execute(
                    f'SELECT "{magnitude}", "{bearing}" {window}', args):
                if mag is None:
                    continue
                if mag != 0.0 and direction is None:
                    continue
                if direction is not None:
                    xsum += mag * math.cos(math.radians(90.0 - direction))
                    ysum += mag * math.sin(math.radians(90.0 - direction))
                count += 1
            if not count:
                return None, None
            if how == "avg":
                xsum, ysum = xsum / count, ysum / count
            return math.sqrt(xsum ** 2 + ysum ** 2), _bearing(xsum, ysum)
        except sqlite3.OperationalError as exc:
            log.debug("cannot aggregate %r as %r: %s", obs_type, how, exc)
            return None, None

    # -- daily summaries -------------------------------------------------

    def _from_daily(self, obs_type: str, start: float, stop: float,
                    how: str) -> Any:
        """From the daily summary tables, or _NOT_THERE if they cannot say.

        `_NOT_THERE` and `None` are different answers: the first means ask the
        records instead, the second means there is nothing to report.
        """
        table = f"{self.table}_day_{obs_type}"
        window = " WHERE dateTime >= ? AND dateTime < ?"
        args = (start, stop)
        try:
            if how in ("min", "max"):
                # A day with no readings has NULL for both, which MIN and MAX
                # ignore.
                fn = "MIN" if how == "min" else "MAX"
                row = self.conn.execute(
                    f'SELECT {fn}("{how}") FROM {table}{window}',
                    args).fetchone()
                return row[0] if row else None

            if how in ("mintime", "maxtime"):
                # Ordering by the value, so the guard on count matters: in
                # SQLite a NULL sorts first ascending and an empty day would
                # win.
                field_ = "min" if how == "mintime" else "max"
                order = "ASC" if how == "mintime" else "DESC"
                row = self.conn.execute(
                    f'SELECT "{how}" FROM {table}{window} AND count > 0'
                    f' ORDER BY "{field_}" {order} LIMIT 1', args).fetchone()
                return int(row[0]) if row and row[0] is not None else None

            if how in ("sum", "count"):
                row = self.conn.execute(
                    f'SELECT SUM("{how}") FROM {table}{window}',
                    args).fetchone()
                if not row or row[0] is None:
                    return None
                return int(row[0]) if how == "count" else row[0]

            if how == "not_null":
                row = self.conn.execute(
                    f"SELECT 1 FROM {table}{window} AND count > 0 LIMIT 1",
                    args).fetchone()
                return bool(row)

            if how == "avg":
                # Weighted: the sum of the weighted sums over the sum of the
                # weights. The mean of daily means would count a day with four
                # readings the same as one with three hundred.
                row = self.conn.execute(
                    f"SELECT SUM(wsum), SUM(sumtime) FROM {table}{window}",
                    args).fetchone()
                return row[0] / row[1] if row and row[1] else None

            if how == "rms":
                row = self.conn.execute(
                    f"SELECT SUM(wsquaresum), SUM(sumtime) FROM {table}{window}",
                    args).fetchone()
                return math.sqrt(row[0] / row[1]) if row and row[1] else None

            if how in ("vecavg", "vecdir"):
                row = self.conn.execute(
                    "SELECT SUM(xsum), SUM(ysum), SUM(sumtime)"
                    f" FROM {table}{window}", args).fetchone()
                if not row or row[2] is None:
                    return None
                xsum, ysum, sumtime = row
                if how == "vecdir":
                    return _bearing(xsum, ysum)
                if not sumtime:
                    return None
                return math.sqrt((xsum ** 2 + ysum ** 2) / sumtime ** 2)

            if how == "gustdir":
                row = self.conn.execute(
                    f"SELECT max_dir FROM {table}{window} AND count > 0"
                    " ORDER BY max DESC LIMIT 1", args).fetchone()
                return row[0] if row else None
        except sqlite3.OperationalError:
            # A summary table without that column -- a scalar asked a vector
            # question. The records can try.
            return _NOT_THERE
        return _NOT_THERE

    # -- many buckets at once --------------------------------------------

    def _daily_series(self, obs_type: str, how: str,
                      spans: list[tuple[int, int]],
                      interval: int | str | None) -> Series | None:
        """A whole series out of the daily summaries in one query, or None.

        The slow way asks the database once per bucket. That is one row
        fetched per statement, and the statement costs far more than the
        row: ten years of daily maxima is 3650 round trips to answer 3650
        questions the file could answer in one.

        None means "this one cannot be done that way" -- a bucket that is
        not whole days, an aggregate the summaries do not hold, a column
        the table does not have. The caller then walks bucket by bucket as
        before, so the fast path can decline anything it is unsure of.
        """
        if how not in _DAILY_REDUCERS or obs_type in DEGREE_DAY_BASES:
            return None
        if not spans or not self.has_daily(obs_type):
            return None
        # `aggregate()` only reads the summaries for whole-day spans, and
        # this has to make the same choice for every bucket or the series
        # would be half one thing and half the other.
        for begin, end in spans:
            if end <= begin or not is_midnight(begin) or not is_midnight(end):
                return None

        table = f"{self.table}_day_{obs_type}"
        try:
            cursor = self.conn.execute(
                f"SELECT * FROM {table} WHERE dateTime >= ? AND dateTime < ?"
                " ORDER BY dateTime", (spans[0][0], spans[-1][1]))
            rows = cursor.fetchall()
        except sqlite3.OperationalError:
            return None
        columns = {name[0]: index
                   for index, name in enumerate(cursor.description)}
        reducer, needed = _DAILY_REDUCERS[how]
        if not needed <= set(columns):
            # A scalar table asked a vector question. The records can try.
            return None

        out = Series(obs_type=obs_type, aggregate=how, interval=interval)
        when = columns["dateTime"]
        at = 0
        for begin, end in spans:
            # Both lists run in time order, so the rows for a bucket are
            # the next few: no searching, one pass over each.
            while at < len(rows) and rows[at][when] < begin:
                at += 1
            first = at
            while at < len(rows) and rows[at][when] < end:
                at += 1
            out.time.append(end)
            out.values.append(reducer(rows[first:at], columns))
            out.start.append(begin)
            out.stop.append(end)
        return out

    # -- from the records ------------------------------------------------

    def _from_records(self, obs_type: str, start: float, stop: float,
                      how: str) -> Any:
        """The general case: aggregate the archive records themselves."""
        if how in ("vecavg", "vecdir", "gustdir"):
            return self._wind(start, stop, how)

        if obs_type == "wind":
            column = WIND.get(how, "windSpeed")
        else:
            column = obs_type
        if column not in self.columns:
            return None

        quoted = f'"{column}"'
        window = (f"FROM {self.table} WHERE dateTime > ? AND dateTime <= ?"
                  f" AND {quoted} IS NOT NULL")
        args = (start, stop)

        plain = {
            "min": f"SELECT MIN({quoted}) {window}",
            "max": f"SELECT MAX({quoted}) {window}",
            "sum": f"SELECT SUM({quoted}) {window}",
            "count": f"SELECT COUNT({quoted}) {window}",
            "first": f"SELECT {quoted} {window} ORDER BY dateTime LIMIT 1",
            "last": f"SELECT {quoted} {window} ORDER BY dateTime DESC LIMIT 1",
            "firsttime": f"SELECT MIN(dateTime) {window}",
            "lasttime": f"SELECT MAX(dateTime) {window}",
            "mintime": f"SELECT dateTime {window} ORDER BY {quoted} LIMIT 1",
            "maxtime": (f"SELECT dateTime {window}"
                        f" ORDER BY {quoted} DESC LIMIT 1"),
            "not_null": f"SELECT 1 {window} LIMIT 1",
        }
        try:
            if how in plain:
                row = self.conn.execute(plain[how], args).fetchone()
                if how == "not_null":
                    return bool(row)
                if not row or row[0] is None:
                    return None
                if how in ("count", "mintime", "maxtime", "firsttime",
                           "lasttime"):
                    return int(row[0])
                return row[0]

            if how == "avg":
                # Weighted by each record's own interval. See the note at the
                # top of the file: WeeWX uses a plain AVG here and a weighted
                # one in the daily summaries.
                row = self.conn.execute(
                    f"SELECT SUM({quoted} * interval), SUM(interval) {window}",
                    args).fetchone()
                return row[0] / row[1] if row and row[1] else None

            if how == "rms":
                row = self.conn.execute(
                    f"SELECT SUM({quoted} * {quoted} * interval),"
                    f" SUM(interval) {window}", args).fetchone()
                return math.sqrt(row[0] / row[1]) if row and row[1] else None

            if how in ("diff", "tderiv"):
                return self._change(column, start, stop, how)
        except sqlite3.OperationalError as exc:
            log.debug("cannot aggregate %r as %r: %s", obs_type, how, exc)
        return None

    def _change(self, column: str, start: float, stop: float,
                how: str) -> float | None:
        """How much a reading moved across a span, and how fast.

        The starting point is the record *at or before* the start of the span,
        not the first one inside it. A meter that stood at 4 kWh at nine and 5
        at ten used one kilowatt-hour in that hour; measuring from the first
        reading after nine would miss whatever happened in the first minute,
        and every bucket would be short by its own first step. WeeWX draws the
        boundary the same way.
        """
        quoted = f'"{column}"'
        edge = (f"SELECT dateTime, {quoted} FROM {self.table}"
                " WHERE dateTime %s ? ORDER BY dateTime %s LIMIT 1")
        first = self.conn.execute(edge % (">=", "ASC"), (start,)).fetchone()
        last = self.conn.execute(edge % ("<=", "DESC"), (stop,)).fetchone()
        if not first or not last or first[1] is None or last[1] is None:
            return None
        if how == "diff":
            return last[1] - first[1]
        elapsed = last[0] - first[0]
        # One record cannot show a rate of change.
        return (last[1] - first[1]) / elapsed if elapsed else None

    def _wind(self, start: float, stop: float, how: str) -> float | None:
        """The vector aggregates, which need two columns at once.

        A wind average is not the average of the speeds: an hour of northerly
        followed by an hour of southerly averages to a brisk wind by that
        measure and to nothing at all by this one, and it is this one that
        says where the air went.
        """
        need = {"vecavg": ("windSpeed", "windDir"),
                "vecdir": ("windSpeed", "windDir"),
                "gustdir": ("windGust", "windGustDir")}[how]
        if not set(need) <= self.columns:
            return None

        args = (start, stop)
        window = f"FROM {self.table} WHERE dateTime > ? AND dateTime <= ?"
        try:
            if how == "gustdir":
                row = self.conn.execute(
                    f"SELECT windGustDir {window} AND windGust IS NOT NULL"
                    " ORDER BY windGust DESC LIMIT 1", args).fetchone()
                return row[0] if row else None

            # Split each reading into its components and sum those, weighted
            # by how long the reading stood for. RADIANS and COS arrived in
            # SQLite 3.35 (2021); older ones raise, and there is no answer.
            row = self.conn.execute(
                "SELECT SUM(interval * windSpeed * COS(RADIANS(90 - windDir))),"
                "       SUM(interval * windSpeed * SIN(RADIANS(90 - windDir))),"
                f"      SUM(interval) {window}"
                " AND windSpeed IS NOT NULL AND windDir IS NOT NULL",
                args).fetchone()
        except sqlite3.OperationalError as exc:
            log.debug("no wind vector aggregate: %s", exc)
            return None

        if not row or row[0] is None:
            return None
        x, y, weight = row
        if how == "vecdir":
            return _bearing(x, y)
        return math.sqrt((x ** 2 + y ** 2) / weight ** 2) if weight else None

    # -- cutting a span into buckets -------------------------------------

    def buckets(self, start: float, stop: float,
                interval: int | str) -> Iterator[tuple[int, int]]:
        """The buckets a span is cut into, as (begin, end) pairs.

        Days, months and years are whole calendar units, and only ones that
        begin inside the span: a request starting at nine in the morning does
        not get a five-sixths-of-a-day bucket at the front. The last one is
        whole too, even where the span ends inside it -- that is the bar for
        today on a chart of this month.

        Everything else is counted from the start of the span in local time,
        so a change to summer time moves one boundary rather than shifting
        every bucket after it by an hour.
        """
        if isinstance(interval, str):
            interval = interval.strip().lower()
            if interval in FIXED:
                interval = FIXED[interval]
            elif interval.isdigit():
                # A number that arrived as text. A configuration file has
                # no numbers in it, only words, and a skin passing
                # `aggregate_interval` straight through hands over "21600"
                # -- which is six hours and not a name.
                interval = int(interval)
            elif interval not in CALENDAR:
                raise ValueError(
                    f"{interval!r} is not an interval. A number of seconds, "
                    f"or one of: hour, {', '.join(CALENDAR)}, week.")

        if isinstance(interval, str):
            unit, count = interval, 1
        elif interval >= 86400 and interval % 86400 == 0:
            # A whole number of days means days, not that many seconds.
            unit, count = "day", int(interval // 86400)
        else:
            if interval <= 0:
                raise ValueError("an interval has to be longer than nothing")
            yield from _fixed(start, stop, int(interval))
            return

        # Calendar buckets are made of whole days, so first work out which
        # days the span covers at all: from the first midnight inside it to
        # the end of the day it finishes in. A span starting at nine in the
        # morning does not get that morning -- there is no half-day row to
        # give it.
        lo = start if is_midnight(start) else _step(_floor(start, "day"), "day")
        hi = stop if is_midnight(stop) else _step(_floor(stop, "day"), "day")
        if lo >= hi:
            return

        begin = _floor(lo, unit)
        while begin < hi:
            end = _step(begin, unit, count)
            # Clipped to the days there are. A bucket at either end holds
            # fewer days than a whole month or a whole three; that is what
            # "this month so far" is, and it is drawn as what it covers.
            yield max(begin, int(lo)), min(end, int(hi))
            begin = end


class _NotThere:
    """Tells 'the summaries cannot answer' from 'the answer is nothing'."""

    def __repr__(self) -> str:  # pragma: no cover - for a traceback
        return "<not in the daily summaries>"


_NOT_THERE = _NotThere()


def _vector(magnitude: float | None,
            bearing: float | None) -> tuple[float | None, float | None]:
    """One wind reading as a vector, or nothing.

    A speed with no bearing is not a vector: there is no arrow to draw and no
    way to add it to another one. WeeWX discards those, and so does this. A
    speed of zero is the exception -- calm has no direction and does not need
    one.
    """
    if magnitude is None:
        return None, None
    if magnitude == 0:
        return 0.0, None
    if bearing is None:
        return None, None
    return magnitude, bearing


def _bearing(x: float | None, y: float | None) -> float | None:
    """The direction of a summed wind vector, in compass degrees.

    The components are held as east and north; a bearing is measured clockwise
    from north, which is what the subtraction from 90 is for.
    """
    if x is None or y is None or (x == 0.0 and y == 0.0):
        return None
    degrees = 90.0 - math.degrees(math.atan2(y, x))
    return degrees if degrees >= 0 else degrees + 360.0


def is_midnight(ts: float) -> bool:
    """Whether a timestamp falls exactly on a local midnight.

    The daily summaries are keyed by these, so this is the question of whether
    they can answer at all.
    """
    return datetime.datetime.fromtimestamp(ts).time() == datetime.time()


def _fixed(start: float, stop: float,
           interval: int) -> Iterator[tuple[int, int]]:
    """Buckets of a fixed length, stepped in local time from the start.

    Stepping in local time rather than adding seconds keeps the boundaries on
    the same clock time across a change to summer time, which is what WeeWX
    does and what anyone reading an hourly chart expects.
    """
    dt = datetime.datetime.fromtimestamp(start)
    end_dt = datetime.datetime.fromtimestamp(stop)
    delta = datetime.timedelta(seconds=interval)
    last = 0
    while dt < end_dt:
        nxt = min(dt + delta, end_dt)
        begin, end = int(dt.timestamp()), int(nxt.timestamp())
        if end > begin > last:
            yield begin, end
            last = begin
        dt = nxt


def _day_spans(start: float, stop: float) -> Iterator[tuple[int, int]]:
    """Whole calendar days covering a span, ends included.

    The day containing `start` through the day containing `stop`, except that
    a `stop` landing exactly on midnight belongs to the day before it. What
    `weeutil.genDaySpans` yields, and degree days are defined on it: half a
    day of temperatures is not a degree day.
    """
    begin = _floor(start, "day")
    last = _floor(stop, "day")
    if last == stop:
        last = _step(last, "day", -1)
    while begin <= last:
        end = _step(begin, "day")
        yield begin, end
        begin = end


def _floor(ts: float, unit: str) -> int:
    """The start of the day, month or year a timestamp falls in."""
    dt = datetime.datetime.fromtimestamp(ts).replace(
        hour=0, minute=0, second=0, microsecond=0)
    if unit == "month":
        dt = dt.replace(day=1)
    elif unit == "year":
        dt = dt.replace(month=1, day=1)
    return int(dt.timestamp())


def _step(ts: float, unit: str, count: int = 1) -> int:
    """Move forward by whole days, months or years, in local time."""
    dt = datetime.datetime.fromtimestamp(ts)
    if unit == "day":
        dt += datetime.timedelta(days=count)
        # Adding a day across a change to summer time lands at 23:00 or 01:00.
        # Midnight was what was meant.
        dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    elif unit == "month":
        month = dt.month - 1 + count
        dt = dt.replace(year=dt.year + month // 12, month=month % 12 + 1, day=1)
    else:
        dt = dt.replace(year=dt.year + count, month=1, day=1)
    return int(dt.timestamp())


# -- one bucket out of a run of daily summary rows -----------------------
#
# A transcription of `Reader._from_daily`, statement by statement. That
# method asks the database for one bucket; these answer the same question
# about rows already in hand, so a whole series costs one query instead of
# one per bucket. Where the two disagree the series is wrong, so they are
# written to be read side by side.


def _sum_of(rows, columns, field):
    """SUM(field): NULL over no rows, and NULLs skipped over some."""
    total = None
    index = columns[field]
    for row in rows:
        value = row[index]
        if value is not None:
            total = value if total is None else total + value
    return total


def _sorts_first(value, current, descending):
    """Whether `value` comes before `current` in SQLite's ORDER BY.

    NULL sorts before every value ascending and after every value
    descending. That is the whole reason the callers filter on `count`
    first: getting it wrong here would pick an empty day. Ties keep the
    row already held, which is the one `LIMIT 1` would have met first.
    """
    if value is None or current is None:
        if descending:
            return value is not None and current is None
        return value is None and current is not None
    return value > current if descending else value < current


def _first_by(rows, columns, field, descending):
    """The row `ORDER BY field [DESC] LIMIT 1` would return."""
    best = None
    index = columns[field]
    for row in rows:
        if not row[columns["count"]]:
            continue
        if best is None or _sorts_first(row[index], best[index], descending):
            best = row
    return best


def _daily_extreme(rows, columns, field):
    """MIN("min") or MAX("max"), which ignore the NULLs an empty day has."""
    values = [row[columns[field]] for row in rows
              if row[columns[field]] is not None]
    if not values:
        return None
    return min(values) if field == "min" else max(values)


def _daily_at(rows, columns, field, order, descending):
    row = _first_by(rows, columns, order, descending)
    if row is None or row[columns[field]] is None:
        return None
    return int(row[columns[field]])


def _daily_avg(rows, columns):
    weight = _sum_of(rows, columns, "sumtime")
    return _sum_of(rows, columns, "wsum") / weight if weight else None


def _daily_rms(rows, columns):
    weight = _sum_of(rows, columns, "sumtime")
    if not weight:
        return None
    return math.sqrt(_sum_of(rows, columns, "wsquaresum") / weight)


def _daily_vector(rows, columns, how):
    weight = _sum_of(rows, columns, "sumtime")
    if weight is None:
        return None
    xsum = _sum_of(rows, columns, "xsum")
    ysum = _sum_of(rows, columns, "ysum")
    if how == "vecdir":
        return _bearing(xsum, ysum)
    if not weight:
        return None
    return math.sqrt((xsum ** 2 + ysum ** 2) / weight ** 2)


def _daily_gustdir(rows, columns):
    row = _first_by(rows, columns, "max", descending=True)
    return row[columns["max_dir"]] if row is not None else None


def _daily_count(rows, columns):
    total = _sum_of(rows, columns, "count")
    return None if total is None else int(total)


#: What each aggregate reduces to, and the columns it needs to do it. An
#: aggregate missing from here is one the summaries cannot answer, so the
#: fast path declines it and the records are asked instead.
_DAILY_REDUCERS = {
    "min": (lambda rows, cols: _daily_extreme(rows, cols, "min"), {"min"}),
    "max": (lambda rows, cols: _daily_extreme(rows, cols, "max"), {"max"}),
    "mintime": (lambda rows, cols: _daily_at(rows, cols, "mintime", "min",
                                             False),
                {"mintime", "min", "count"}),
    "maxtime": (lambda rows, cols: _daily_at(rows, cols, "maxtime", "max",
                                             True),
                {"maxtime", "max", "count"}),
    "sum": (lambda rows, cols: _sum_of(rows, cols, "sum"), {"sum"}),
    "count": (_daily_count, {"count"}),
    "not_null": (lambda rows, cols: any(row[cols["count"]] for row in rows),
                 {"count"}),
    "avg": (_daily_avg, {"wsum", "sumtime"}),
    "rms": (_daily_rms, {"wsquaresum", "sumtime"}),
    "vecavg": (lambda rows, cols: _daily_vector(rows, cols, "vecavg"),
               {"xsum", "ysum", "sumtime"}),
    "vecdir": (lambda rows, cols: _daily_vector(rows, cols, "vecdir"),
               {"xsum", "ysum", "sumtime"}),
    "gustdir": (_daily_gustdir, {"max_dir", "max", "count"}),
}
