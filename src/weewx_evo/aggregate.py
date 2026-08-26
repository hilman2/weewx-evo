"""Turning a stream of observations into statistics.

This is a transcription of WeeWX's `weewx.accum`, not a reinterpretation.
Every arithmetic step is in the same order and the same shape, because these
numbers land in `archive_day_*` tables that WeeWX must keep reading. A
"cleaner" formula that rounds differently is a wrong formula here.

Two things are deliberately different from the original:

  * No global state. The policy is an argument, so the differential test can
    hold two of them at once.
  * The accumulator is fed and then read. It never talks to a database, never
    logs, and never asks what time it is. That is what makes an archive record
    reproducible from stored packets instead of from a live process's memory.
"""

from __future__ import annotations

import datetime
import math
from typing import Any

from .obstypes import DEFAULT_POLICY, Policy


def to_float(x: Any) -> float | None:
    """WeeWX's weeutil.to_float: the string 'none' is a null, not an error."""
    if isinstance(x, str) and x.lower() == "none":
        x = None
    return float(x) if x is not None else None


def _usable(val: Any) -> float | None:
    """Return val as a float, or None if it is missing, unparseable, or NaN."""
    try:
        val = to_float(val)
    except (ValueError, TypeError):
        return None
    # NaN is the only value that is not equal to itself.
    if val is None or val != val:
        return None
    return val


def start_of_archive_day(time_ts: float) -> int:
    """The start of the day an archive record belongs to.

    A record stamped exactly at midnight closes the *previous* day. WeeWX has
    always done this, and the daily summaries are indexed by the result.
    """
    dt = datetime.datetime.fromtimestamp(time_ts)
    sod = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    if dt == sod:
        sod -= datetime.timedelta(days=1)
    return int(sod.timestamp())


class FirstLast:
    """Minimal accumulator. Remembers the first and last value it saw.

    Suitable for strings, which is why it does no arithmetic at all.
    """

    __slots__ = ("first", "firsttime", "last", "lasttime")
    default_stats = (None, None, None, None, 0.0, 0, 0.0, 0)

    def __init__(self, stats_tuple: tuple | None = None) -> None:
        self.first: Any = None
        self.firsttime: float | None = None
        self.last: Any = None
        self.lasttime: float | None = None

    def set_stats(self, stats_tuple: tuple | None = None) -> None:
        """A no-op: nothing this class holds survives a database round trip."""

    def stats_tuple(self) -> tuple:
        return FirstLast.default_stats

    def merge_hilo(self, other: FirstLast) -> None:
        if other.firsttime is not None:
            if self.firsttime is None or other.firsttime < self.firsttime:
                self.firsttime = other.firsttime
                self.first = other.first
        if other.lasttime is not None:
            if self.lasttime is None or other.lasttime >= self.lasttime:
                self.lasttime = other.lasttime
                self.last = other.last

    def merge_sum(self, other: FirstLast) -> None:
        """A no-op. There is no sum to merge."""

    def add_hilo(self, val: Any, ts: float) -> None:
        if val is None:
            return
        if self.firsttime is None or ts < self.firsttime:
            self.first = val
            self.firsttime = ts
        if self.lasttime is None or ts >= self.lasttime:
            self.last = val
            self.lasttime = ts

    def add_sum(self, val: Any, weight: float = 1) -> None:
        """A no-op. There is no sum to add to."""

    @property
    def avg(self) -> None:
        return None


class Scalar(FirstLast):
    """Statistics for a scalar observation: min, max, and a weighted mean.

    `wsum` and `sumtime` are what make an average over an arbitrary period
    possible later: the sum is weighted by how long each value stood, so
    records at different archive intervals still average correctly.
    """

    __slots__ = ("min", "mintime", "max", "maxtime", "sum", "count", "wsum", "sumtime")

    def __init__(self, stats_tuple: tuple | None = None) -> None:
        super().__init__(stats_tuple)
        self.set_stats(stats_tuple)

    def set_stats(self, stats_tuple: tuple | None = None) -> None:
        (self.min, self.mintime, self.max, self.maxtime,
         self.sum, self.count, self.wsum, self.sumtime) = (
            stats_tuple if stats_tuple else FirstLast.default_stats
        )

    def stats_tuple(self) -> tuple:
        return (self.min, self.mintime, self.max, self.maxtime,
                self.sum, self.count, self.wsum, self.sumtime)

    def merge_hilo(self, other: Scalar) -> None:  # type: ignore[override]
        super().merge_hilo(other)
        if other.min is not None:
            if self.min is None or other.min < self.min:
                self.min = other.min
                self.mintime = other.mintime
        if other.max is not None:
            if self.max is None or other.max > self.max:
                self.max = other.max
                self.maxtime = other.maxtime

    def merge_sum(self, other: Scalar) -> None:  # type: ignore[override]
        self.sum += other.sum
        self.count += other.count
        self.wsum += other.wsum
        self.sumtime += other.sumtime

    def add_hilo(self, val: Any, ts: float) -> None:
        super().add_hilo(val, ts)
        val = _usable(val)
        if val is None:
            return
        if self.min is None or val < self.min:
            self.min = val
            self.mintime = ts
        if self.max is None or val > self.max:
            self.max = val
            self.maxtime = ts

    def add_sum(self, val: Any, weight: float = 1) -> None:
        val = _usable(val)
        if val is None:
            return
        self.sum += val
        self.count += 1
        self.wsum += val * weight
        self.sumtime += weight

    @property
    def avg(self) -> float | None:
        return self.wsum / self.sumtime if self.count else None


class Vector:
    """Statistics for wind: scalar stats plus the vector sums.

    `xsum`/`ysum` accumulate the east and north components, which is how a
    mean *direction* survives averaging -- adding degrees would not.
    `dirsumtime` counts only the time a direction was actually known, so a
    stretch of missing directions does not drag the mean towards north.
    """

    __slots__ = ("min", "mintime", "max", "maxtime", "sum", "count", "wsum", "sumtime",
                 "max_dir", "xsum", "ysum", "dirsumtime", "squaresum", "wsquaresum",
                 "last", "lasttime")

    default_stats = (None, None, None, None, 0.0, 0, 0.0, 0, None, 0.0, 0.0, 0, 0.0, 0.0)

    def __init__(self, stats_tuple: tuple | None = None) -> None:
        self.set_stats(stats_tuple)
        self.last: tuple[Any, Any] = (None, None)
        self.lasttime: float | None = None

    def set_stats(self, stats_tuple: tuple | None = None) -> None:
        (self.min, self.mintime, self.max, self.maxtime,
         self.sum, self.count, self.wsum, self.sumtime,
         self.max_dir, self.xsum, self.ysum, self.dirsumtime,
         self.squaresum, self.wsquaresum) = (
            stats_tuple if stats_tuple else Vector.default_stats
        )

    def stats_tuple(self) -> tuple:
        return (self.min, self.mintime, self.max, self.maxtime,
                self.sum, self.count, self.wsum, self.sumtime,
                self.max_dir, self.xsum, self.ysum, self.dirsumtime,
                self.squaresum, self.wsquaresum)

    def merge_hilo(self, other: Vector) -> None:
        if other.min is not None:
            if self.min is None or other.min < self.min:
                self.min = other.min
                self.mintime = other.mintime
        if other.max is not None:
            if self.max is None or other.max > self.max:
                self.max = other.max
                self.maxtime = other.maxtime
                self.max_dir = other.max_dir
        if other.lasttime is not None:
            if self.lasttime is None or other.lasttime >= self.lasttime:
                self.lasttime = other.lasttime
                self.last = other.last

    def merge_sum(self, other: Vector) -> None:
        self.sum += other.sum
        self.count += other.count
        self.wsum += other.wsum
        self.sumtime += other.sumtime
        self.xsum += other.xsum
        self.ysum += other.ysum
        self.dirsumtime += other.dirsumtime
        self.squaresum += other.squaresum
        self.wsquaresum += other.wsquaresum

    def add_hilo(self, val: tuple[Any, Any], ts: float) -> None:
        speed, dir_n = _usable(val[0]), _usable(val[1])
        if speed is None:
            return
        if self.min is None or speed < self.min:
            self.min = speed
            self.mintime = ts
        if self.max is None or speed > self.max:
            self.max = speed
            self.maxtime = ts
            self.max_dir = dir_n
        if self.lasttime is None or ts >= self.lasttime:
            self.last = (speed, dir_n)
            self.lasttime = ts

    def add_sum(self, val: tuple[Any, Any], weight: float = 1) -> None:
        speed, dir_n = _usable(val[0]), _usable(val[1])
        if speed is None:
            return
        self.sum += speed
        self.count += 1
        self.wsum += weight * speed
        self.sumtime += weight
        self.squaresum += speed ** 2
        self.wsquaresum += weight * speed ** 2
        if dir_n is not None:
            self.xsum += weight * speed * math.cos(math.radians(90.0 - dir_n))
            self.ysum += weight * speed * math.sin(math.radians(90.0 - dir_n))
        # A missing direction is fine as long as there was no wind to point.
        if dir_n is not None or speed == 0:
            self.dirsumtime += weight

    @property
    def avg(self) -> float | None:
        return self.wsum / self.sumtime if self.count else None

    @property
    def rms(self) -> float | None:
        return math.sqrt(self.wsquaresum / self.sumtime) if self.count else None

    @property
    def vec_avg(self) -> float | None:
        if self.count:
            return math.sqrt((self.xsum ** 2 + self.ysum ** 2) / self.sumtime ** 2)
        return None

    @property
    def vec_dir(self) -> float | None:
        if self.dirsumtime and (self.ysum or self.xsum):
            result = 90.0 - math.degrees(math.atan2(self.ysum, self.xsum))
            if result < 0.0:
                result += 360.0
            return result
        # With a zero vector sum there is no mean direction. Report the last
        # one seen rather than an arbitrary north.
        return self.last[1]


_ACCUM_CLASSES = {"scalar": Scalar, "vector": Vector, "firstlast": FirstLast}


class Accumulator:
    """Statistics for a set of observation types over one span of time.

    Feed it records with `add_record`, then read a record back out with
    `record()`. The span is half-open at the start: a record stamped exactly
    at `start` belongs to the previous span.
    """

    __slots__ = ("start", "stop", "unit_system", "_stats", "_policy")

    def __init__(self, start: float, stop: float, unit_system: int | None = None,
                 policy: Policy = DEFAULT_POLICY) -> None:
        self.start = start
        self.stop = stop
        self.unit_system = unit_system
        self._stats: dict[str, Any] = {}
        self._policy = policy

    def __contains__(self, obs_type: str) -> bool:
        return obs_type in self._stats

    def __getitem__(self, obs_type: str):
        return self._stats[obs_type]

    def __iter__(self):
        return iter(self._stats)

    def includes(self, ts: float) -> bool:
        return self.start < ts <= self.stop

    @property
    def is_empty(self) -> bool:
        return self.unit_system is None

    def add_record(self, record: dict, add_hilo: bool = True, weight: float = 1) -> None:
        """Fold one record into the statistics.

        Raises ValueError if the record falls outside the span, or if its unit
        system differs from what has already been accumulated. Both are bugs in
        the caller, not conditions to paper over: a mixed-unit average is a
        wrong number that looks right.
        """
        if not self.includes(record["dateTime"]):
            raise ValueError(
                f"record at {record['dateTime']} is outside span "
                f"({self.start}, {self.stop}]"
            )
        for obs_type in record:
            adder = self._policy[obs_type].adder
            if adder == "noop":
                continue
            if adder == "check_units":
                self._check_units(record["usUnits"])
            elif adder == "add_wind":
                self._add_wind(record, obs_type, add_hilo, weight)
            else:
                self._add_value(record, obs_type, add_hilo, weight)

    def merge_hilo(self, other: Accumulator) -> None:
        """Fold another accumulator's highs and lows into this one."""
        if other.start < self.start or other.stop > self.stop:
            raise ValueError("the other accumulator's span is not a subset of this one")
        self._check_units(other.unit_system)
        for obs_type in other:
            self._init_type(obs_type)
            if self._policy[obs_type].merger == "avg":
                self._merge_avg(other, obs_type)
            else:
                self._stats[obs_type].merge_hilo(other[obs_type])

    def record(self) -> dict:
        """Extract an archive record. It is stamped at the end of the span."""
        return self.augment({"dateTime": self.stop, "usUnits": self.unit_system})

    def augment(self, record: dict) -> dict:
        """Fill in whatever the record does not already carry.

        Values already present win. That is how a console's own archive record
        keeps its hardware-computed fields while gaining the ones it omitted.
        """
        for obs_type in self._stats:
            if obs_type in record:
                continue
            self._extract(record, obs_type)
        return record

    def set_stats(self, obs_type: str, stats_tuple: tuple | None = None) -> None:
        """Load statistics straight from storage, bypassing the arithmetic.

        With no tuple the type is merely brought into existence, empty. That is
        how a day gets a row for an observation that stayed null all day.
        """
        self._init_type(obs_type)
        self._stats[obs_type].set_stats(stats_tuple)

    # -- adders ----------------------------------------------------------

    def _add_value(self, record: dict, obs_type: str, add_hilo: bool, weight: float) -> None:
        self._init_type(obs_type)
        if add_hilo:
            self._stats[obs_type].add_hilo(record[obs_type], record["dateTime"])
        self._stats[obs_type].add_sum(record[obs_type], weight=weight)

    def _add_wind(self, record: dict, obs_type: str, add_hilo: bool, weight: float) -> None:
        """Wind is accumulated twice: as plain windSpeed, and as a vector."""
        if obs_type in ("windDir", "windGust", "windGustDir"):
            return
        self._add_value(record, obs_type, add_hilo, weight)

        self._init_type("wind")
        if add_hilo:
            # A station that reports no gust direction gets the plain wind
            # direction instead. WeeWX issue #320.
            gust_dir = record["windGustDir"] if "windGustDir" in record \
                else record.get("windDir")
            # Gust first, so the *last* value entered is windSpeed. `last` is
            # what vec_dir falls back on when the vector sum is zero.
            self._stats["wind"].add_hilo((record.get("windGust"), gust_dir),
                                         record["dateTime"])
            self._stats["wind"].add_hilo((record.get("windSpeed"), record.get("windDir")),
                                         record["dateTime"])
        self._stats["wind"].add_sum((record["windSpeed"], record.get("windDir")), weight=weight)

    # -- mergers ---------------------------------------------------------

    def _merge_avg(self, other: Accumulator, obs_type: str) -> None:
        """Merge using the other accumulator's *average* as its high.

        Used for windSpeed, where the daily high should be the highest
        sustained wind, not the highest instantaneous reading -- that one is
        the gust, and it is recorded separately.
        """
        mine, theirs = self._stats[obs_type], other[obs_type]
        if theirs.min is not None:
            if mine.min is None or theirs.min < mine.min:
                mine.min = theirs.min
                mine.mintime = theirs.mintime
        if theirs.avg is not None:
            if mine.max is None or theirs.avg > mine.max:
                mine.max = theirs.avg
                mine.maxtime = other.stop
        if theirs.lasttime is not None:
            if mine.lasttime is None or theirs.lasttime >= mine.lasttime:
                mine.lasttime = theirs.lasttime
                mine.last = theirs.last

    # -- extractors ------------------------------------------------------

    def _extract(self, record: dict, obs_type: str) -> None:
        how = self._policy[obs_type].extractor
        stats = self._stats[obs_type]
        if how == "noop":
            return
        if how == "wind":
            # The vector is flattened back into the four columns the schema has.
            record.setdefault("windSpeed", stats.avg)
            record.setdefault("windDir", stats.vec_dir)
            record.setdefault("windGust", stats.max)
            record.setdefault("windGustDir", stats.max_dir)
        elif how == "sum":
            record[obs_type] = stats.sum if stats.count else None
        elif how == "first":
            record[obs_type] = stats.first
        elif how == "last":
            record[obs_type] = stats.last
        elif how == "min":
            record[obs_type] = stats.min
        elif how == "max":
            record[obs_type] = stats.max
        elif how == "count":
            record[obs_type] = stats.count
        else:
            record[obs_type] = stats.avg

    # -- housekeeping ----------------------------------------------------

    def _init_type(self, obs_type: str) -> None:
        if obs_type not in self._stats:
            self._stats[obs_type] = _ACCUM_CLASSES[self._policy[obs_type].accumulator]()

    def _check_units(self, unit_system: int | None) -> None:
        if self.unit_system is None:
            self.unit_system = unit_system
        elif unit_system is not None and self.unit_system != unit_system:
            raise ValueError(f"unit system mismatch: {self.unit_system} vs {unit_system}")
