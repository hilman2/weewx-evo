"""Charts as pictures, and the one set of numbers behind them.

The thing worth guarding here is not that a PNG comes out. It is that the
picture and the JSON are the *same chart*. WeeWX works that arithmetic out
twice -- once in its ImageGenerator, once in whatever writes JSON -- and the
two drift apart in the third decimal place, which nobody ever finds because
each of them is right on its own.

So the first check is that both feeds go through `chartdata`, and it is
written so that pulling the calculation back into either of them fails it.

The rest are the ones that look fine in a browser and are wrong:

- `scale` has to reach the file. A chart written at the logical size looks
  correct next to a chart written at twice it, until somebody opens both.
- A vector chart's axis has to straddle zero, or every arrow sits on the
  floor and the southerly half is drawn off the bottom.
- A bar chart's axis has to start at zero, or a bar is a lie about its own
  length.
- A plot with no data must be left out, not written as an empty picture.

    python tools/image_test.py
"""

from __future__ import annotations

import json
import math
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


def _utc_year_start() -> float:
    """The first of January of the current year, locally."""
    import datetime

    return datetime.datetime(time.localtime().tm_year, 1, 1).timestamp()


def check(label: str, got: object, want: object) -> bool:
    ok = got == want
    # Some of these compare a few hundred readings. Printing all of them
    # buries the twenty lines somebody actually reads.
    said = repr(got)
    if len(said) > 70:
        said = f"{said[:60]}... ({len(got)} of them)"  # type: ignore[arg-type]
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: {said}"
          + ("" if ok else f" != {want!r}"[:200]))
    return ok


def archive(path: Path) -> int:
    """Two days of readings, and one sensor this station never had."""
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE archive (dateTime INTEGER PRIMARY KEY, "
                 "usUnits INTEGER, `interval` INTEGER, outTemp REAL, "
                 "dewpoint REAL, rain REAL, windSpeed REAL, windDir REAL, "
                 "windGust REAL, windGustDir REAL, radiation REAL)")
    midnight = int(time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1)))
    when = midnight - 86400
    last = when
    while when < time.time():
        hour = (when % 86400) / 3600.0
        conn.execute("INSERT INTO archive VALUES "
                     "(?, 1, 5, ?, ?, ?, ?, ?, ?, ?, NULL)",
                     (when, 50.0 + hour, 40.0 + hour / 2, 0.01,
                      2.0 + (hour % 3), 180.0 + hour * 5,
                      3.0 + (hour % 4), 190.0 + hour * 5))
        last = when
        when += 300
    conn.commit()
    conn.close()
    return last


def main() -> int:
    from weewx_evo import chartdata, plots as plot_defs, units
    from weewx_evo.feeds.imagegenerator import ImageGenerator
    from weewx_evo.feeds.jsongenerator import JSONGenerator
    from weewx_evo.series import Reader

    tmp = Path(tempfile.mkdtemp(prefix="weewx-evo-images-"))
    failures = 0
    try:
        try:
            from PIL import Image
        except ImportError:
            print("Pillow is not installed; nothing to test here.")
            return 0

        db = tmp / "weewx.sdb"
        last = archive(db)
        conn = sqlite3.connect(db)
        reader = Reader(conn)

        charts = plot_defs.PlotSet([
            plot_defs.Plot("daytemp", "day", 86400, [
                plot_defs.Line("outTemp", label="Temperature"),
                plot_defs.Line("dewpoint", label="Dew point"),
            ]),
            plot_defs.Plot("dayrain", "day", 86400, [
                plot_defs.Line("rain", kind="bar", aggregate="sum",
                               interval=3600, label="Rain"),
            ]),
            plot_defs.Plot("daywindvec", "day", 86400, [
                plot_defs.Line("windvec", kind="vector"),
            ]),
            # A sensor this station has never had, over a span it has never
            # had it for.
            plot_defs.Plot("dayradiation", "day", 86400,
                           [plot_defs.Line("radiation")],
                           skip_if_empty="year"),
        ])

        target = units.Target(units.METRICWX)
        images = ImageGenerator(reader, charts, target=target,
                                unit_system=reader.system,
                                latitude=48.46, longitude=11.65)
        made = images.produce(tmp / "png", now=last)

        print("\nthe charts are drawn")
        failures += not check("nothing failed", images.failed, [])
        failures += not check("three of the four", images.written, 3)
        failures += not check("and the empty one was left out, not drawn",
                              images.skipped, 1)
        failures += not check("no picture for it",
                              (tmp / "png" / "dayradiation.png").exists(),
                              False)
        failures += not check("the files are named after the plots",
                              sorted(p.name for p in made.files),
                              ["dayrain.png", "daytemp.png",
                               "daywindvec.png"])

        print("\nand written at twice the size a page shows them at")
        with Image.open(tmp / "png" / "daytemp.png") as picture:
            failures += not check("2x by default", picture.size,
                                  (images.width * 2, images.height * 2))
        smaller = ImageGenerator(reader, charts, target=target,
                                 unit_system=reader.system, scale=1)
        smaller.produce(tmp / "png1", now=last)
        with Image.open(tmp / "png1" / "daytemp.png") as picture:
            failures += not check("1x when asked", picture.size,
                                  (images.width, images.height))

        print("\nthe picture and the JSON are the same chart")
        # Both must go through chartdata. Written this way on purpose: move
        # the calculation back into either feed and this stops passing.
        JSONGenerator(reader, charts, target=target,
                      unit_system=reader.system, latitude=48.46,
                      longitude=11.65).produce(tmp / "json", now=last)
        document = json.loads((tmp / "json" / "daytemp.json")
                              .read_text(encoding="utf-8"))
        chart = chartdata.build(charts.plots[0], reader, last, target=target,
                                unit_system=reader.system,
                                latitude=48.46, longitude=11.65)
        failures += not check("same number of lines",
                              len(document["series"]), len(chart.lines))
        failures += not check("same values, to the last decimal",
                              document["series"][0]["values"],
                              chart.lines[0].values)
        failures += not check("same timestamps",
                              document["series"][0]["time"],
                              chart.lines[0].time)
        failures += not check("same unit", document["unit"], chart.unit)

        print("\nevery chart says what it is")
        # This was the visible fault: thirty charts on a page, not one
        # of them headed. A plot definition imported from a skin carries
        # no label unless somebody wrote one, so the reading's own name
        # has to stand in -- "Outside Temperature", not "outTemp", and
        # not nothing.
        bare = plot_defs.PlotSet([
            plot_defs.Plot("daybare", "day", 86400,
                           [plot_defs.Line("outTemp"),
                            plot_defs.Line("dewpoint")]),
        ])
        plain = ImageGenerator(reader, bare, target=target,
                               unit_system=reader.system)
        chart = chartdata.build(bare.plots[0], reader, last, target=target,
                                unit_system=reader.system)
        heading = plain._heading(chart)
        failures += not check("both readings are named",
                              [said for said, _c in heading],
                              ["Outside Temperature", "Dew Point"])
        failures += not check("each in its own colour",
                              len({c for _s, c in heading}), 2)
        # The heading and the legend are one line, so a plot with a title
        # of its own replaces the lot rather than being printed above it.
        titled = plot_defs.Plot("x", "day", 86400,
                                [plot_defs.Line("outTemp")],
                                title="Rain (hourly total)")
        chart = chartdata.build(titled, reader, last, target=target,
                                unit_system=reader.system)
        failures += not check("a plot title wins outright",
                              plain._heading(chart),
                              [("Rain (hourly total)", "")])

        print("\na wind vector answers as a wind speed does")
        # `windvec` is not a column, and `aggregate` did not know it.
        # A template asking `check_for_data('windvec')` got nothing
        # back and left the chart off the page -- while the file sat
        # there, drawn and correct, which is why it took a while to see.
        for obs in ("windvec", "windgustvec"):
            failures += not check(f"{obs} has data",
                                  bool(reader.aggregate(
                                      obs, last - 86400, last,
                                      "not_null")), True)

        print("\nthe axis suits what is drawn on it")
        bars = chartdata.build(charts.plots[1], reader, last, target=target,
                               unit_system=reader.system)
        low, high = images._range(bars)
        failures += not check("a bar chart starts at zero", low <= 0.0, True)
        arrows = chartdata.build(charts.plots[2], reader, last, target=target,
                                 unit_system=reader.system)
        low, high = images._range(arrows)
        failures += not check("a vector chart straddles it",
                              low < 0.0 < high, True)
        failures += not check("and symmetrically, so north reads like south",
                              round(low + high, 6), 0.0)

        print("\nthe labels grow with the picture")
        # The one that shipped broken. A container has no system fonts,
        # Pillow fell back to a face of one fixed size, and every label
        # on every chart came out the same small height whatever the
        # scale -- which reads as a styling decision. Measured rather
        # than assumed: ask for a size and see what comes back.
        from weewx_evo.feeds.imagegenerator import canvas as drawing
        from weewx_evo.feeds.imagegenerator import theme as theming

        sheet = drawing.Canvas(200, 100, theming.resolve(theming.Theme()))
        small = sheet.measure("Outside Temperature", 10)[0]
        large = sheet.measure("Outside Temperature", 20)[0]
        failures += not check("twice the size is about twice as wide",
                              1.7 < large / max(small, 1) < 2.3, True)

        # And with no typeface at all, which is what a slim container is.
        bare = theming.Theme(font_path="", bold_path="")
        blind = drawing.Canvas(200, 100, bare)
        blind.theme = theming.replace(bare, font_path="", bold_path="")
        blind._fonts.clear()
        small = blind.measure("Outside Temperature", 10)[0]
        large = blind.measure("Outside Temperature", 20)[0]
        failures += not check("even without one installed",
                              large > small * 1.5, True)

        print("\nan arrow points where WeeWX points it")
        # Two sign conventions meet here and both are easy to invert.
        # WeeWX builds the components the same way we do:
        #
        #     east  = mag * cos(radians(90 - direction))
        #     north = mag * sin(radians(90 - direction))
        #
        # then draws with a NEGATIVE yscale and subtracts the x term
        # (weeplot/utilities.py, ScaledDraw.vector). Worked through,
        # that comes to:
        #
        #     screen_dx =  east*cos(r) - north*sin(r)
        #     screen_dy = -east*sin(r) - north*cos(r)
        #
        # with r the plot's vector_rotate, positive anticlockwise. The
        # rotation used to be stored already negated, so at r = 90 --
        # which is WeeWX's own default -- every arrow pointed exactly
        # the opposite way, and nothing about one chart looked wrong.
        from weewx_evo.feeds.imagegenerator import _turned

        def weewx_says(east, north, degrees):
            r = math.radians(degrees)
            return (east * math.cos(r) - north * math.sin(r),
                    -east * math.sin(r) - north * math.cos(r))

        for degrees in (0, 90, 180, -90, 37):
            for east, north in ((0.0, 1.0), (1.0, 0.0), (0.6, -0.8)):
                want = weewx_says(east, north, degrees)
                got = _turned(0.0, 0.0, east, north,
                              math.radians(degrees))
                failures += not check(
                    f"east {east}, north {north}, turned {degrees}",
                    (round(got[0], 9), round(got[1], 9)),
                    (round(want[0], 9), round(want[1], 9)))

        print("\na wind chart says which way is north")
        # Without it a field of arrows has no key, and a plot may turn
        # them -- WeeWX's own default rotates by ninety degrees.
        #
        # Found by changing the letter and diffing, rather than by
        # counting dark pixels in a corner: the arrows and the axis
        # labels are in that corner too, and a count says nothing about
        # which of them it found.
        from PIL import ImageChops

        marked = ImageGenerator(reader, charts, target=target,
                                unit_system=reader.system,
                                rose_label="X")
        marked.produce(tmp / "rose", now=last)
        one = Image.open(tmp / "png" / "daywindvec.png").convert("RGB")
        other = Image.open(tmp / "rose" / "daywindvec.png").convert("RGB")
        where = ImageChops.difference(one, other).getbbox()
        failures += not check("the letter is drawn", where is not None,
                              True)
        if where:
            failures += not check("in the bottom left, out of the data",
                                  where[2] < one.width * 0.15
                                  and where[1] > one.height * 0.55, True)
        one.close()
        other.close()

        print("\nand it is written in the station's language")
        # One setting for the whole station. A chart has no skin behind
        # it, so without this it says "Outside Temperature" on a page
        # where everything else says Aussentemperatur.
        from weewx_evo import language as language_module
        from weewx_evo.feeds.imagegenerator import canvas as drawing

        german = language_module.get("de")
        spoken = ImageGenerator(reader, charts, target=target,
                                unit_system=reader.system,
                                language=german)
        chart = chartdata.build(charts.plots[0], reader, last,
                                target=target,
                                unit_system=reader.system)
        # The plot names its lines, and a plot that names them wins --
        # so this asks the layer underneath, which is what a plot with
        # no labels falls through to.
        failures += not check("readings are named in it",
                              units.obs_label("outTemp", german),
                              "Aussentemperatur")
        failures += not check("including the numbered families",
                              units.obs_label("soilMoist3", german),
                              "Bodenfeuchte 3")
        failures += not check("and the compass turns with it",
                              german.compass()[1], "NNO")

        # The one that is easy to miss: strftime follows the PROCESS
        # locale, not this setting. A container with nothing set says
        # "May" on a German page, and setting LC_TIME globally to fix
        # one chart changes how the whole program formats everything.
        import locale as locale_module

        try:
            locale_module.setlocale(locale_module.LC_TIME, "C")
        except locale_module.Error:
            pass
        year = _utc_year_start()
        ticks = drawing.time_ticks(year, year + 330 * 86400,
                                   language=german)
        said = [name for _when, name in ticks]
        failures += not check("months come from the file, not the locale",
                              "Mär" in said or "Mai" in said, True)
        failures += not check("and not from English",
                              "May" in said or "Mar" in said, False)
        plain = drawing.time_ticks(year, year + 330 * 86400)
        failures += not check("English still reads as English",
                              "May" in [n for _w, n in plain], True)
        failures += not check("the rose says north in it",
                              spoken.rose_label, "N")

        print("\na chart is a picture, not a blank one")
        with Image.open(tmp / "png" / "daytemp.png") as picture:
            colors = picture.convert("RGB").getcolors(maxcolors=1 << 20)
        failures += not check("more than a background in it",
                              len(colors) > 20, True)
        # The most common colour is the background: a chart that came out
        # all one colour would pass every check above it.
        commonest = max(colors)[1]
        failures += not check("and it is drawn on white", commonest,
                              (255, 255, 255))

        conn.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + ("FAIL" if failures else "PASS") + f" ({failures} failure(s))")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
