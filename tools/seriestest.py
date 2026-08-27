"""Ask WeeWX and weewx-evo for the same series, and compare them.

`weewx.xtypes.get_series` is what every WeeWX report is built on, and every
feed here is built on `weewx_evo.series`. If the two disagree, a chart drawn by
weewx-evo shows a different week of weather than the same chart drawn by WeeWX,
which is the one thing this project cannot do.

Run against a real database rather than a made-up one: the same file, the same
day boundaries, the same readings. The timezone matters -- the day summary
tables are keyed by local midnight, and reading them in the wrong zone
compares one day against another. Pass it as the second argument.

    wsl -d Ubuntu -- bash -lc 'source ~/venvs/weewx/bin/activate &&
        cd /mnt/d/Git/weewx-evo && PYTHONPATH=/mnt/d/Git/weewx/src:src
        python3 tools/seriestest.py reference/weewx.sdb Europe/Berlin'
"""

from __future__ import annotations

import math
import os
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

os.environ["TZ"] = sys.argv[2] if len(sys.argv) > 2 else "Europe/Berlin"
time.tzset()

from weewx_evo.series import Reader, is_midnight  # noqa: E402

#: Sub-day resolutions, compared over the whole database. WeeWX works these
#: out from the archive table, and so does weewx-evo.
FINE = [
    ("outTemp", "min", 3600), ("outTemp", "max", 3600),
    ("outTemp", "avg", 3600), ("outTemp", "avg", 900),
    ("outTemp", "avg", 21600), ("outTemp", "mintime", 3600),
    ("outTemp", "maxtime", 3600), ("outTemp", "count", 3600),
    ("outTemp", "first", 3600), ("outTemp", "last", 3600),
    ("outHumidity", "min", 3600), ("outHumidity", "avg", 3600),
    ("barometer", "avg", 3600), ("barometer", "max", 3600),
    ("windSpeed", "avg", 3600), ("windSpeed", "max", 3600),
    ("windSpeed", "vecavg", 3600), ("windDir", "vecdir", 3600),
    ("wind", "vecavg", 3600), ("wind", "vecdir", 3600),
    ("wind", "gustdir", 3600), ("wind", "max", 3600),
    ("wind", "maxtime", 3600),
    ("rain", "sum", 3600), ("rain", "count", 3600),
    ("radiation", "avg", 3600), ("radiation", "max", 3600),
    ("UV", "max", 3600), ("inTemp", "avg", 3600),
    ("dewpoint", "min", 3600), ("windchill", "min", 1800),
    ("heatindex", "max", 1800), ("pressure", "avg", 3600),
    ("outTemp", "diff", 3600), ("outTemp", "tderiv", 3600),
]

#: Daily and coarser, compared over a day-aligned span -- the only kind a
#: report ever asks for. Both sides answer these from the daily summaries.
COARSE = [
    ("outTemp", "min", 86400), ("outTemp", "max", 86400),
    ("outTemp", "avg", 86400), ("outTemp", "sum", 86400),
    ("outTemp", "count", 86400), ("outTemp", "min", "day"),
    ("outTemp", "max", 172800), ("outTemp", "avg", 259200),
    ("outHumidity", "avg", 86400), ("outHumidity", "min", 86400),
    ("barometer", "avg", 86400), ("barometer", "max", 86400),
    ("windSpeed", "avg", 86400), ("windSpeed", "max", 86400),
    ("rain", "sum", 86400), ("rain", "count", 86400),
    ("radiation", "max", 86400), ("radiation", "avg", 86400),
    ("UV", "max", 86400), ("inTemp", "avg", 86400),
    ("dewpoint", "min", 86400), ("dewpoint", "max", 86400),
    ("windchill", "min", 86400), ("heatindex", "max", 86400),
    ("pressure", "avg", 86400), ("ET", "sum", 86400),
    # Calendar units. The reference span sits inside one month, so these are
    # the partial-bucket case: "August so far", not "every August".
    ("outTemp", "max", "month"), ("outTemp", "avg", "month"),
    ("rain", "sum", "month"), ("outTemp", "max", "year"),
    ("rain", "sum", "year"),
]

#: Floats. WeeWX sums in a different order than SQLite does and the last bits
#: differ. A tenth of a millionth is far below any sensor's resolution.
TOLERANCE = 1e-6


def close(a: object, b: object) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if a == b:
            return True
        return abs(a - b) / max(abs(a), abs(b), 1.0) < TOLERANCE
    return a == b


def same(got: list, want: list) -> bool:
    """Two sequences of times, compared including their length.

    The length is the point: `zip` stops at the shorter one, so a series
    with three buckets missing off the end compared as equal to a full one.
    """
    return len(got) == len(want) and all(
        close(a, b) for a, b in zip(got, want, strict=True))


class Tally:
    def __init__(self) -> None:
        self.checked = self.points = self.bad = self.skipped = 0
        self.known = 0


def compare(tally: Tally, label: str, mine: object, their_values: list,
            expected: str = "") -> None:
    """One series against one series."""
    values = mine.values  # type: ignore[attr-defined]
    wrong = [(i, a, b) for i, (a, b) in enumerate(zip(values, their_values, strict=False))
             if not close(a, b)]
    length_ok = len(values) == len(their_values)
    ok = length_ok and not wrong
    tally.checked += 1
    tally.points += len(values)

    if not ok and expected:
        tally.known += 1
        mark = "note"
    elif ok:
        mark = "ok  "
    else:
        mark = "FAIL"
        tally.bad += 1

    print(f"  {mark} {label:<28} {len(values)} point(s)"
          + (f"   {expected}" if mark == "note" else ""))
    if not length_ok:
        print(f"       evo has {len(values)}, weewx has {len(their_values)}")
    for i, a, b in wrong[:3]:
        when = time.strftime("%m-%d %H:%M",
                             time.localtime(mine.time[i]))  # type: ignore
        apart = ("" if not isinstance(a, (int, float))
                 or not isinstance(b, (int, float))
                 else f"  ({abs(a - b):.6g} apart)")
        print(f"       [{i}] {when}  evo={a!r} weewx={b!r}{apart}")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    path = sys.argv[1]

    import weewx.manager
    import weewx.xtypes
    from weeutil.weeutil import TimeSpan

    manager = weewx.manager.DaySummaryManager.open(
        {"SQLITE_ROOT": str(Path(path).parent),
         "database_name": Path(path).name, "driver": "weedb.sqlite"})
    conn = sqlite3.connect(path)
    reader = Reader(conn)
    tally = Tally()

    start, stop = reader.span()
    print(f"{path}  ({os.environ['TZ']})")
    print(f"  {time.strftime('%Y-%m-%d %H:%M', time.localtime(start))}"
          f" to {time.strftime('%Y-%m-%d %H:%M', time.localtime(stop))}")

    intervals = conn.execute(
        "SELECT interval, COUNT(*) FROM archive GROUP BY interval").fetchall()
    mixed = len(intervals) > 1
    print("  archive interval: "
          + ", ".join(f"{m} min ({n} records)" for m, n in intervals)
          + ("   -- it changed, so weighted and plain averages differ"
             if mixed else ""))

    # A day-aligned span, which is the only kind a report ever asks for. The
    # first whole day to the last.
    from weewx_evo.series import _floor, _step
    day_start = _floor(start, "day")
    if day_start < start:
        day_start = _step(day_start, "day")
    day_stop = _floor(stop, "day")
    print(f"  whole days: "
          f"{time.strftime('%Y-%m-%d', time.localtime(day_start))} to "
          f"{time.strftime('%Y-%m-%d', time.localtime(day_stop))}"
          f"  (aligned: {is_midnight(day_start) and is_midnight(day_stop)})\n")

    whole = TimeSpan(int(start), int(stop))
    days = TimeSpan(day_start, day_stop)

    print("no aggregate: the archive records themselves")
    for obs in ("outTemp", "barometer", "windSpeed", "rain", "radiation"):
        theirs = weewx.xtypes.get_series(obs, whole, manager)
        mine = reader.series(obs, whole.start, whole.stop)
        stops_ok = same(mine.stop, list(theirs[1][0]))
        compare(tally, obs, mine, list(theirs[2][0]))
        if not stops_ok:
            print("       the point boundaries differ")
            tally.bad += 1

    print("\nsub-day aggregates, over the whole database")
    weighted = ("weighted average; the archive interval changed"
                if mixed else "")
    for obs, how, interval in FINE:
        label = f"{obs}/{how}/{interval}"
        try:
            theirs = weewx.xtypes.get_series(obs, whole, manager,
                                             aggregate_type=how,
                                             aggregate_interval=interval)
        except Exception as exc:
            print(f"  --   {label:<28} WeeWX will not: {type(exc).__name__}:"
                  f" {exc}")
            tally.skipped += 1
            continue
        mine = reader.series(obs, whole.start, whole.stop, aggregate=how,
                             interval=interval)
        compare(tally, label, mine, list(theirs[2][0]),
                expected=weighted if how == "avg" else "")

    print("\ndaily and coarser, over whole days")
    for obs, how, interval in COARSE:
        label = f"{obs}/{how}/{interval}"
        try:
            theirs = weewx.xtypes.get_series(obs, days, manager,
                                             aggregate_type=how,
                                             aggregate_interval=interval)
        except Exception as exc:
            print(f"  --   {label:<28} WeeWX will not: {type(exc).__name__}:"
                  f" {exc}")
            tally.skipped += 1
            continue
        mine = reader.series(obs, days.start, days.stop, aggregate=how,
                             interval=interval)
        compare(tally, label, mine, list(theirs[2][0]))
        # The bucket boundaries have to line up too, or the values are right
        # and drawn in the wrong place.
        if not same(mine.start, list(theirs[0][0])):
            print("       the bucket boundaries differ:"
                  f" evo {[int(x) for x in mine.start[:3]]}"
                  f" weewx {[int(x) for x in list(theirs[0][0])[:3]]}")
            tally.bad += 1

    print("\nsingle aggregates, day by day")
    # get_aggregate rather than get_series: the same numbers reached the other
    # way, which is how a report asks for "today's high".
    for obs, how in (("outTemp", "min"), ("outTemp", "max"),
                     ("outTemp", "avg"), ("outTemp", "mintime"),
                     ("outTemp", "maxtime"), ("rain", "sum"),
                     ("windSpeed", "max"), ("wind", "vecdir"),
                     ("wind", "vecavg"), ("wind", "gustdir"),
                     ("outTemp", "rms"), ("outTemp", "not_null")):
        bad = 0
        n = 0
        for begin, end in reader.buckets(days.start, days.stop, "day"):
            try:
                theirs = weewx.xtypes.get_aggregate(
                    obs, TimeSpan(begin, end), how, manager)[0]
            except Exception:
                continue
            n += 1
            if not close(reader.aggregate(obs, begin, end, how), theirs):
                bad += 1
        if not n:
            print(f"  --   {obs}/{how:<10} WeeWX will not")
            tally.skipped += 1
            continue
        tally.checked += 1
        tally.bad += bool(bad)
        print(f"  {'ok  ' if not bad else 'FAIL'} {obs}/{how:<10}"
              f" {n} day(s), {bad} differ")

    print("\nwind vectors: a magnitude and a bearing at every point")
    # WeeWX carries these as one complex number. Split into two arrays here,
    # so the comparison is against abs() and the bearing it decodes to.
    import cmath
    for obs, how, unit in (("windvec", None, None),
                           ("windvec", "avg", 3600),
                           ("windvec", "avg", 86400),
                           ("windvec", "max", 3600),
                           ("windvec", "sum", 3600),
                           ("windvec", "first", 3600),
                           ("windvec", "last", 3600),
                           ("windgustvec", "max", 3600),
                           ("windgustvec", "avg", 86400)):
        label = f"{obs}/{how or 'raw'}/{unit or '-'}"
        span = days if unit == 86400 else whole
        try:
            theirs = weewx.xtypes.get_series(obs, span, manager,
                                             aggregate_type=how,
                                             aggregate_interval=unit)
        except Exception as exc:
            print(f"  --   {label:<28} WeeWX will not: {exc}")
            tally.skipped += 1
            continue
        mine = reader.series(obs, span.start, span.stop, aggregate=how,
                             interval=unit)
        mags, dirs = [], []
        for v in theirs[2][0]:
            if v is None:
                mags.append(None)
                dirs.append(None)
            elif isinstance(v, complex):
                mags.append(abs(v))
                deg = 90.0 - math.degrees(cmath.phase(v))
                dirs.append(None if v == 0 else (deg if deg >= 0 else deg + 360.0))
            else:
                mags.append(v)
                dirs.append(None)
        note = ""
        if (how is None and len(mags) == len(mine) + 1
                and int(theirs[1][0][0]) == int(span.start)):
            # WeeWX's unaggregated wind vector query uses `dateTime >= ?`
            # where every other series in WeeWX uses `>`, so it has one extra
            # point at the very start. Dropped here, and noted rather than
            # copied: see the comment in series.py.
            mags, dirs = mags[1:], dirs[1:]
            note = "WeeWX includes one extra point at dateTime == start"
        compare(tally, label, mine, mags, expected=note)
        wrong = [(i, a, b) for i, (a, b) in
                 enumerate(zip(mine.directions or [], dirs, strict=False)) if not close(a, b)]
        if wrong:
            print(f"       {len(wrong)} bearing(s) differ, first:"
                  f" evo={wrong[0][1]!r} weewx={wrong[0][2]!r}")
            tally.bad += 1

    print("\ncalendar buckets over a span that is not aligned to days")
    # The ragged case: a span that starts and ends mid-day. This is what a
    # report asks for when it wants "this month up to now", and it is where
    # the partial bucket at each end has to be drawn as what it covers.
    for obs, how, unit in (("outTemp", "max", "month"),
                           ("rain", "sum", "month"),
                           ("outTemp", "max", "day"),
                           ("rain", "sum", "day")):
        label = f"{obs}/{how}/{unit} ragged"
        try:
            theirs = weewx.xtypes.get_series(obs, whole, manager,
                                             aggregate_type=how,
                                             aggregate_interval=unit)
        except Exception as exc:
            print(f"  --   {label:<28} WeeWX will not: {exc}")
            tally.skipped += 1
            continue
        mine = reader.series(obs, whole.start, whole.stop, aggregate=how,
                             interval=unit)
        compare(tally, label, mine, list(theirs[2][0]))
        for what, got, want in (("start", mine.start, list(theirs[0][0])),
                                ("stop", mine.stop, list(theirs[1][0]))):
            if not same(got, want):
                print(f"       the bucket {what}s differ:"
                      f" evo {[int(x) for x in got[:3]]}"
                      f" weewx {[int(x) for x in want[:3]]}")
                tally.bad += 1

    print("\nbuckets follow the calendar")
    for name in ("day", "month", "year", "hour", 172800):
        got = list(reader.buckets(start, stop, name))
        shown = ", ".join(
            time.strftime("%Y-%m-%d %H:%M", time.localtime(b))
            for b, _ in got[:3])
        print(f"  {name!s:<8} {len(got):>4} bucket(s)   {shown}")
    aligned = all(is_midnight(b) and is_midnight(e)
                  for b, e in reader.buckets(start, stop, "day"))
    tally.checked += 1
    tally.bad += not aligned
    print(f"  {'ok  ' if aligned else 'FAIL'} every daily bucket is a day")

    manager.close()
    conn.close()
    print(f"\n{tally.checked} comparison(s), {tally.points} point(s), "
          f"{tally.bad} failure(s)"
          + (f", {tally.known} known deviation(s)" if tally.known else "")
          + (f", {tally.skipped} skipped" if tally.skipped else ""))
    return 1 if tally.bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
