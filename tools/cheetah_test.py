"""A skin written for WeeWX, rendered here.

The promise this feed makes is narrow and total: a skin somebody has been
using for eight years keeps working, unchanged. So the things worth testing
are the ones that look fine on the first page and are wrong on the fortieth.

Four of them, all found the hard way:

- `#include` is resolved by Cheetah against the process's *current
  directory*. WeeWX chdirs into the skin. Here a listener is answering
  hardware on other threads, so the includes are spliced in instead -- and
  a nested include has to work, because skins nest them.
- A skin brings its own units, decimals and words. A page that has printed
  one decimal of pressure in millibars for eight years must keep doing it,
  whatever this program's defaults are.
- `heatdeg` and `cooldeg` are not columns. They are counted from daily mean
  temperatures against a base the skin may move, and a skin that moves it
  gets a different number.
- A reading the station has never had must behave the way WeeWX makes it
  behave, which is two different ways: `$current.foo` prints `?'foo'?` and
  `$day.foo.max` raises. A skin is written against both, and it is counted
  either way -- a page that renders at 95% looks like our bug and cannot be
  reproduced.

    python tools/cheetah_test.py
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

os.environ.setdefault("TZ", "Europe/Berlin")
try:
    time.tzset()
except AttributeError:  # pragma: no cover - Windows
    pass


def _decimals(text: object) -> int:
    """How many digits are printed after the point. "12.758 Grad" is three."""
    head, _, tail = str(text or "").partition(".")
    del head
    count = 0
    for char in tail:
        if not char.isdigit():
            break
        count += 1
    return count


def _number(text: object) -> float:
    """The number in front of a label. "60.1 F-day" is 60.1."""
    digits = ""
    for char in str(text or ""):
        if char.isdigit() or char in ".-":
            digits += char
        elif digits:
            break
    return float(digits or 0.0)


def check(label: str, got: object, want: object) -> bool:
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: {got!r}"
          + ("" if ok else f" != {want!r}"))
    return ok


def archive(path: Path) -> None:
    """Three days of readings, in US units because that is the awkward case.

    The station wrote Fahrenheit and inches of mercury; the skin asks for
    Celsius and millibars. Everything the conversion touches is here.
    """
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE archive (dateTime INTEGER PRIMARY KEY, "
                 "usUnits INTEGER, `interval` INTEGER, outTemp REAL, "
                 "barometer REAL, rain REAL)")
    # Three days up to now, so `$day` has something in it. Whole days in
    # local time, because degree days are counted per calendar day and a
    # bucket of 86400 seconds is not one.
    midnight = int(time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1)))
    start = midnight - 2 * 86400
    while start < time.time():
        # Around 50 F, below the 65 F base, so there are heating degree days
        # and no cooling ones.
        conn.execute("INSERT INTO archive VALUES (?, 1, 5, ?, ?, ?)",
                     (start, 45.0 + (start % 28800) / 2880.0, 29.9, 0.0))
        start += 300
    conn.commit()
    conn.close()


SKIN_CONF = """
SKIN_NAME = Testing
SKIN_VERSION = 1.2.3

[Units]
    [[Groups]]
        group_temperature = degree_C
        group_pressure = mbar
    [[StringFormats]]
        degree_C = %.3f
        mbar = %.1f
    [[Labels]]
        degree_C = " Grad"
    [[DegreeDays]]
        heating_base = 70, degree_F

[Labels]
    [[Generic]]
        outTemp = Aussentemperatur

[Extras]
    radar_url = https://example.org/radar.png

[DisplayOptions]
    observations = outTemp, barometer

[CheetahGenerator]
    encoding = utf8
    [[ToDate]]
        [[[index]]]
            template = index.html.tmpl
        [[[fresh]]]
            template = fresh.html.tmpl
            stale_age = 86400
"""

INDEX = """#include "header.inc"
name=$SKIN_NAME/$SKIN_VERSION
temp=$current.outTemp
label=$obs.label.outTemp
press=$day.barometer.avg
heat=$year.heatdeg.sum
cool=$year.cooldeg.sum
extras=$Extras.radar_url
walk=#for $x in $observations#$getattr($current, $x) #end for#
missing=$current.nosuchreading
guarded=#if $day.nosuchreading.has_data#yes#else#no#end if#
"""

HEADER = '#include "deeper.inc"\nheader=yes\n'
DEEPER = "deeper=yes\n"
FRESH = "fresh=$current.outTemp\n"


def main() -> int:
    from weewx_evo import units
    from weewx_evo.feeds.cheetah import CheetahFeed
    from weewx_evo.series import Reader, _day_spans
    from weewx_evo.tags import Tags

    tmp = Path(tempfile.mkdtemp(prefix="weewx-evo-cheetah-"))
    failures = 0
    try:
        try:
            import Cheetah.Template  # noqa: F401
        except ImportError:
            print("Cheetah is not installed; nothing to test here.")
            return 0

        db = tmp / "weewx.sdb"
        archive(db)
        skin = tmp / "skins" / "Testing"
        skin.mkdir(parents=True)
        (skin / "skin.conf").write_text(SKIN_CONF, encoding="utf-8")
        (skin / "index.html.tmpl").write_text(INDEX, encoding="utf-8")
        (skin / "header.inc").write_text(HEADER, encoding="utf-8")
        (skin / "deeper.inc").write_text(DEEPER, encoding="utf-8")
        (skin / "fresh.html.tmpl").write_text(FRESH, encoding="utf-8")
        (skin / "site.css").write_text("body{}", encoding="utf-8")

        conn = sqlite3.connect(db)
        reader = Reader(conn)
        tags = Tags(reader, target=units.Target(reader.system),
                    unit_system=reader.system,
                    station={"location": "Nowhere"})
        out = tmp / "public"
        feed = CheetahFeed(reader, skin, tags, encoding="utf8")
        feed.produce(out)

        print("\nthe pages are written")
        failures += not check("nothing failed", feed.failed, [])
        failures += not check("two pages", feed.rendered, 2)
        page = (out / "index.html").read_text(encoding="utf-8")
        got = dict(line.split("=", 1) for line in page.splitlines() if "=" in line)

        print("\nan include is spliced in, however deep")
        # Cheetah would resolve these against the process's directory. If
        # that ever comes back, this is where it shows.
        failures += not check("one level", got.get("header"), "yes")
        failures += not check("two levels", got.get("deeper"), "yes")

        print("\nthe skin's own file decides how a page reads")
        failures += not check("its name", got.get("name"), "Testing/1.2.3")
        # Stored in Fahrenheit, shown in Celsius because the skin says so,
        # with the skin's three decimals and the skin's own word for it.
        temp = got.get("temp", "")
        failures += not check("in Celsius, because the skin asked",
                              _number(temp) < 30.0, True)
        failures += not check("to the skin's three decimals",
                              _decimals(temp), 3)
        failures += not check("and the skin's own word for the unit",
                              temp.endswith(" Grad"), True)
        failures += not check("what the skin calls the reading",
                              got.get("label"), "Aussentemperatur")
        press = got.get("press", "")
        failures += not check("millibars", press.endswith(" mbar"), True)
        failures += not check("and one decimal of them", _decimals(press), 1)
        failures += not check("a section of its own", got.get("extras"),
                              "https://example.org/radar.png")
        # `$observations` with no `$DisplayOptions.` in front of it: WeeWX
        # puts the section's contents into the search list itself, and a
        # skin walking its own list of readings depends on that.
        walk = got.get("walk", "")
        failures += not check("its DisplayOptions are top-level names too",
                              " Grad" in walk and " mbar" in walk, True)

        print("\ndegree days are counted, from where the skin says")
        # Three days below the base, so heating degree days and no cooling.
        failures += not check("there are some", _number(got.get("heat")) > 0,
                              True)
        failures += not check("and none the other way",
                              _number(got.get("cool")), 0.0)
        failures += not check("labelled as degree days",
                              got.get("heat", "").endswith("°F-day"), True)
        # The skin moved the base from 65 F to 70 F. Five degrees a day
        # more, over the three days there are readings for.
        tags.degree_day_bases["heatdeg"] = (65.0, "degree_F")
        lower = reader.aggregate("heatdeg", tags.month.span[0],
                                 tags.month.span[1], "sum",
                                 tags.degree_day_bases)
        tags.degree_day_bases["heatdeg"] = (70.0, "degree_F")
        higher = reader.aggregate("heatdeg", tags.month.span[0],
                                  tags.month.span[1], "sum",
                                  tags.degree_day_bases)
        failures += not check("a higher base is more degree days",
                              higher > lower, True)
        # Only days that have a temperature count. A day the station was
        # off is left out of the total, not counted as zero -- that is the
        # part of WeeWX's arithmetic that is easy to get wrong.
        days = sum(1 for begin, end
                   in _day_spans(tags.month.span[0], tags.month.span[1])
                   if reader.aggregate("outTemp", begin, end, "avg")
                   is not None)
        failures += not check("by five a day, on every day there is data",
                              round(higher - lower, 6), 5.0 * days)

        print("\na reading the station never had reads as WeeWX reads it")
        # Two different behaviours, and a skin is written against both:
        # `$current.foo` prints and carries on, `$day.foo.max` raises.
        # Getting either one wrong takes a page down that works in WeeWX.
        failures += not check("printed, not blank", got.get("missing"),
                              "?\'nosuchreading\'?")
        failures += not check("and the guard says no", got.get("guarded"),
                              "no")
        failures += not check("counted", tags.missing.get("nosuchreading"),
                              1)
        failures += not check("and reported",
                              "nosuchreading" in tags.report(), True)
        failures += not check("the page still got written",
                              (out / "index.html").exists(), True)

        print("\nwhat the skin ships alongside comes too")
        failures += not check("its stylesheet", (out / "site.css").exists(), True)
        failures += not check("but not its templates or its config",
                              (out / "index.html.tmpl").exists()
                              or (out / "skin.conf").exists(), False)

        print("\nstale_age is honoured on the second run")
        again = CheetahFeed(reader, skin, tags, encoding="utf8")
        again.produce(out)
        failures += not check("the fresh page was skipped", again.skipped, 1)
        failures += not check("the other one was not", again.rendered, 1)

        print("\nand the operator can overrule the skin's units")
        chosen = Tags(reader, target=units.Target(units.US),
                      unit_system=reader.system)
        forced = CheetahFeed(reader, skin, chosen, encoding="utf8")
        forced.skin_units = False
        forced.produce(tmp / "forced")
        forced_page = (tmp / "forced" / "index.html").read_text(encoding="utf-8")
        failures += not check("Fahrenheit, as asked",
                              "°F" in forced_page, True)
        # A skin's decimals are keyed to a unit, not to a reading, so its
        # "%.3f for Celsius" says nothing about Fahrenheit and the default
        # applies. That is WeeWX's arrangement, and it is the honest one: a
        # skin cannot have an opinion about a unit it never expected.
        forced_temp = dict(
            line.split("=", 1) for line in forced_page.splitlines()
            if "=" in line).get("temp", "")
        failures += not check("and the decimals are ours again, not its",
                              _decimals(forced_temp), 1)

        conn.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{'PASS' if not failures else 'FAIL'} ({failures} failure(s))")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
