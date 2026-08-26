"""Render the same tags through WeeWX and through weewx-evo, and compare.

The goal this exists to measure: somebody who has used a skin for eight years
keeps using it, unchanged. That is a claim about hundreds of small
expressions, and the only honest way to make it is to run them through both
and count.

Every line below is a real tag out of the skins WeeWX ships. The comparison is
on the *rendered text*, because that is what ends up on the page: a value
right to the last bit and labelled `mbar` where WeeWX says `hPa` is still a
different page.

    wsl -d Ubuntu -- bash -lc 'source ~/venvs/weewx/bin/activate &&
        cd /mnt/d/Git/weewx-evo && PYTHONPATH=/mnt/d/Git/weewx/src:src
        python3 tools/tagcheck.py reference/weewx.sdb Europe/Berlin'
"""

from __future__ import annotations

import datetime
import os
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

os.environ["TZ"] = sys.argv[2] if len(sys.argv) > 2 else "Europe/Berlin"
time.tzset()

#: The tags, as a template writes them. Grouped so a failure says which idea
#: is broken rather than which line.
TAGS = {
    "the latest reading": [
        "$current.outTemp",
        "$current.outTemp.formatted",
        "$current.outTemp.raw",
        "$current.barometer",
        "$current.outHumidity",
        "$current.windSpeed",
        "$current.dateTime",
        "$current.rainRate",
    ],
    "today": [
        "$day.outTemp.max",
        "$day.outTemp.min",
        "$day.outTemp.avg",
        "$day.outTemp.maxtime",
        "$day.outTemp.mintime",
        "$day.rain.sum",
        "$day.windSpeed.max",
        "$day.barometer.avg",
        "$day.outHumidity.min",
        "$day.outTemp.max.formatted",
        "$day.outTemp.max.raw",
        "$day.outTemp.has_data",
        "$day.outTemp.exists",
    ],
    "the other spans": [
        "$yesterday.outTemp.max",
        "$yesterday.rain.sum",
        "$week.outTemp.max",
        "$week.outTemp.min",
        "$week.rain.sum",
        "$month.outTemp.max",
        "$month.outTemp.avg",
        "$month.rain.sum",
        "$year.outTemp.max",
        "$year.outTemp.min",
        "$year.rain.sum",
        "$hour.outTemp.avg",
    ],
    "wind": [
        "$day.wind.max",
        "$day.wind.maxtime",
        "$day.wind.vecdir",
        "$day.wind.vecavg",
        "$day.wind.gustdir",
        "$day.windGust.max",
        "$day.windDir.avg",
    ],
    "printing": [
        "$day.outTemp.max.format('%.3f')",
        "$day.outTemp.maxtime.format('%H:%M')",
        "$day.outTemp.max.nolabel('%.1f')",
        "$day.outTemp.max.string('nothing')",
        "$day.outTemp.max.degree_F",
        "$day.outTemp.max.degree_C",
        "$day.barometer.max.mbar",
        "$day.barometer.max.inHg",
        "$day.rain.sum.mm",
        "$day.rain.sum.inch",
    ],
    "a span of its own": [
        "$span(hour_delta=6).outTemp.avg",
        "$span(day_delta=2).outTemp.max",
        "$span(hour_delta=24).rain.sum",
    ],
    "the span itself": [
        "$day.start",
        "$day.end",
        "$month.start",
        "$year.start",
    ],
    "the station": [
        "$station.location",
        "$station.latitude_f",
        "$station.longitude_f",
        "$station.station_url",
    ],
    "what things are called": [
        "$obs.label.outTemp",
        "$obs.label.rain",
        "$unit.label.outTemp",
        "$unit.unit_type.rain",
        "$unit.format.barometer",
    ],
    "the sky": [
        "$almanac.hasExtras",
        "$almanac.sunrise",
        "$almanac.sunset",
        "$almanac.sun.rise",
        "$almanac.sun.set",
        "$almanac.sun.transit",
        "$almanac.moon_phase",
        "$almanac.moon_fullness",
        "$almanac.moon.rise",
        "$almanac.moon.set",
        "$almanac.next_full_moon",
        "$almanac.next_new_moon",
        "$almanac.next_equinox",
        "$almanac.next_solstice",
    ],
    "a reading nothing has": [
        "$day.gibtsnicht.max",
        "$current.gibtsnicht",
    ],
}


#: Tags where a difference of a few seconds is the answer, not a fault.
#:
#: WeeWX asks pyephem for these. weewx-evo works them out from Meeus's
#: series, which is what makes `$almanac.hasExtras` true on an installation
#: with nothing added to it -- and lands a handful of seconds away. Measured
#: properly in `tools/mooncheck.py`, over twenty years and six places; this
#: only has to stop reporting it as a mismatch.
NEARLY = {
    "$almanac.next_full_moon", "$almanac.next_new_moon",
    "$almanac.next_first_quarter_moon", "$almanac.next_last_quarter_moon",
    "$almanac.previous_full_moon", "$almanac.previous_new_moon",
    "$almanac.next_equinox", "$almanac.next_solstice",
    "$almanac.previous_equinox", "$almanac.previous_solstice",
    "$almanac.moon.rise", "$almanac.moon.set", "$almanac.moon.transit",
}

#: How far apart two of those may be. Two minutes is well inside what any
#: page shows and well outside what a transcription error looks like.
NEARLY_SECONDS = 120


def check(label: str, ours: str, theirs: str) -> bool:
    ok = ours == theirs
    if not ok and label in NEARLY:
        apart = _seconds_apart(ours, theirs)
        if apart is not None and apart <= NEARLY_SECONDS:
            print(f"  ok   {label:<44} {ours} ({apart:.0f}s from weewx)")
            return True
    if ok:
        print(f"  ok   {label:<44} {ours}")
    else:
        print(f"  FAIL {label:<44} evo={ours!r}")
        print(f"       {'':<44} weewx={theirs!r}")
    return ok


def _seconds_apart(ours: str, theirs: str) -> float | None:
    """How far apart two printed moments are, or None if they are not two."""
    shapes = ("%m/%d/%y %H:%M:%S", "%m/%d/%Y %H:%M:%S", "%H:%M:%S", "%X")
    for shape in shapes:
        try:
            first = datetime.datetime.strptime(ours.strip(), shape)
            second = datetime.datetime.strptime(theirs.strip(), shape)
        except ValueError:
            continue
        return abs((first - second).total_seconds())
    return None


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    path = sys.argv[1]

    import weewx.manager
    import weewx.tags
    import weewx.units
    from weeutil.weeutil import TimeSpan  # noqa: F401 -- used by the tags

    from weewx_evo import units
    from weewx_evo.series import Reader
    from weewx_evo.tags import Tags

    manager = weewx.manager.DaySummaryManager.open(
        {"SQLITE_ROOT": str(Path(path).parent),
         "database_name": Path(path).name, "driver": "weedb.sqlite"})
    conn = sqlite3.connect(path)
    reader = Reader(conn)

    span = reader.span()
    when = span[1] if span else time.time()
    print(f"{path}  ({os.environ['TZ']})")
    print(f"  as of {time.strftime('%Y-%m-%d %H:%M', time.localtime(when))}")

    # The same units on both sides, or every comparison fails on the label.
    # US, because that is what this database holds and what a skin would
    # show without being told otherwise.
    stored = manager.std_unit_system or units.US
    where = {"location": "Kirchdorf an der Amper", "latitude": 48.4596,
             "longitude": 11.6539, "altitude": "440 meter",
             "station_url": "https://example.org"}
    ours = Tags(reader, when=when, target=units.Target(stored),
                unit_system=stored, station=where)
    ours.labels.update(_generic_labels())

    import weewx.almanac

    formatter = weewx.units.Formatter.fromSkinDict(_skin())
    import weewx.defaults

    almanac = weewx.almanac.Almanac(
        when, where["latitude"], where["longitude"],
        altitude=440.0,   # metres, as weewx.almanac documents it
        moon_phases=weewx.defaults.defaults["Almanac"]["moon_phases"],
        formatter=formatter)
    station = _Station(where)
    labels = _Labels(_generic_labels())
    unit_info = weewx.units.UnitInfoHelper(formatter,
                                          weewx.units.Converter())

    theirs = weewx.tags.TimeBinder(
        lambda binding=None: manager, when,
        formatter=weewx.units.Formatter.fromSkinDict(_skin()),
        converter=weewx.units.Converter())
    records = weewx.tags.RecordBinder(
        lambda binding=None: manager, when,
        formatter=weewx.units.Formatter.fromSkinDict(_skin()),
        converter=weewx.units.Converter())

    total = failures = 0
    for heading, expressions in TAGS.items():
        print(f"\n{heading}")
        for expression in expressions:
            total += 1
            mine = _render(expression, ours, ours, extra={
                "_station": ours.station, "_obs": ours.obs,
                "_unit": ours.unit, "_almanac": ours.almanac})
            weewx_said = _render(expression, theirs, records, autocall=True,
                                 extra={"_station": station, "_obs": labels,
                                        "_unit": unit_info,
                                        "_almanac": almanac})
            failures += not check(expression, mine, weewx_said)

    print(f"\n{ours.report()}")
    manager.close()
    conn.close()
    print(f"\n{total} tag(s), {failures} that differ")
    return 1 if failures else 0


def _skin() -> dict:
    """A skin dictionary with nothing in it, so WeeWX uses its own defaults."""
    import weewx.defaults

    return {"Units": weewx.defaults.defaults["Units"]}


#: The spans WeeWX exposes as methods. Cheetah calls them for you -- its
#: NameMapper auto-calls anything callable -- so a template says `$day` and
#: means `day()`. Here they are properties, which is the same thing to a
#: template and a difference the harness has to bridge.
CALLED = ("day", "yesterday", "week", "month", "year", "hour", "rainyear",
          "alltime")


class _Station:
    """What WeeWX's $station offers, out of the same settings."""

    def __init__(self, values: dict) -> None:
        self.__dict__.update(values)
        self.latitude_f = float(values["latitude"])
        self.longitude_f = float(values["longitude"])


class _Labels:
    """What WeeWX's $obs offers."""

    def __init__(self, labels: dict) -> None:
        self.label = type("L", (), dict(labels, __getattr__=lambda s, k: k))()


def _generic_labels() -> dict:
    import weewx.defaults

    return dict(weewx.defaults.defaults["Labels"]["Generic"])


def _render(expression: str, spans: object, current: object,
            autocall: bool = False, extra: dict | None = None) -> str:
    """Evaluate one tag the way a template would, and turn it into text."""
    for name in ("station", "obs", "unit", "almanac"):
        expression = expression.replace(f"${name}", f"_{name}")
    code = expression.replace("$current", "_current").replace("$", "_spans.")
    if autocall:
        import re

        code = re.sub(r"_spans\.(" + "|".join(CALLED) + r")\.",
                      "_spans.\\1().", code)
    try:
        # str() as well as the lookup: both sides put off the query until
        # somebody wants the text, so that is where an unknown reading
        # finally raises.
        names = {"_spans": spans, "_current": _current_of(current)}
        names.update(extra or {})
        return str(eval(code, names))
    except AttributeError as exc:
        return f"<no such tag: {exc}>"
    except Exception as exc:  # noqa: BLE001
        return f"<{type(exc).__name__}: {exc}>"


def _current_of(binder: object) -> object:
    """`$current` is a property on one side and a method on the other."""
    found = getattr(binder, "current", None)
    return found() if callable(found) else found


if __name__ == "__main__":
    raise SystemExit(main())
