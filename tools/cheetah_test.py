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


def _with_extensions(skin, named):
    """Rewrite the test skin's config to name some search list extensions."""
    (skin / "skin.conf").write_text(
        SKIN_CONF.replace(
            "[CheetahGenerator]",
            "[CheetahGenerator]" + chr(10)
            + "    search_list_extensions = " + named),
        encoding="utf-8")


def _read_page(path):
    """A rendered page as key=value pairs, which is how these templates are
    written so that a check can name one line."""
    return dict(line.split("=", 1)
                for line in path.read_text(encoding="utf-8").splitlines()
                if "=" in line)


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
                 "barometer REAL, rain REAL, windDir REAL)")
    # Three days up to now, so `$day` has something in it. Whole days in
    # local time, because degree days are counted per calendar day and a
    # bucket of 86400 seconds is not one.
    midnight = int(time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1)))
    start = midnight - 2 * 86400
    while start < time.time():
        # Around 50 F, below the 65 F base, so there are heating degree days
        # and no cooling ones.
        # 160 degrees is SSE, which is SSO in German -- a point whose name
        # differs, so the test can tell a translated compass from an
        # untranslated one.
        conn.execute("INSERT INTO archive VALUES (?, 1, 5, ?, ?, ?, ?)",
                     (start, 45.0 + (start % 28800) / 2880.0, 29.9, 0.0,
                      160.0))
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

[CopyGenerator]
    copy_once = site.css, assets

[CheetahGenerator]
    encoding = utf8
    [[ToDate]]
        [[[index]]]
            template = index.html.tmpl
        [[[fresh]]]
            template = fresh.html.tmpl
            stale_age = 86400
"""

GERMAN = """
unit_system = metricwx

[Units]
    [[Labels]]
        degree_C = " Grad"
    [[Ordinates]]
        directions = N, NNO, NO, ONO, O, OSO, SO, SSO, S, SSW, SW, WSW, W, WNW, NW, NNW, keiner

[Labels]
    [[Generic]]
        outTemp = Aussentemperatur
        barometer = Luftdruck

[Texts]
    "Current Conditions" = "Aktuelle Werte"
    "Sunrise" = "Sonnenaufgang"
"""

#: A skin's own Python, in the shape WeeWX defines. Two things are checked
#: by its shape rather than its content: it inherits from
#: `weewx.cheetahgenerator.SearchList` and does *not* override
#: `get_extension_list`, so the default has to return `[self]` and its
#: methods have to become tags; and it uses the pieces of `weewx.units` and
#: `weeutil` that every real extension uses.
EXTENSION = """
from weewx.cheetahgenerator import SearchList
from weewx.units import ValueHelper, ValueTuple, UnitInfoHelper, ObsInfoHelper
from weeutil.weeutil import TimeSpan, to_bool, rounder, startOfDay
from weeutil.config import search_up, accumulateLeaves
import weewx.xtypes


class Extras(SearchList):
    def __init__(self, generator):
        SearchList.__init__(self, generator)
        self.unit = UnitInfoHelper(generator.formatter, generator.converter)
        self.obs = ObsInfoHelper(generator.skin_dict)

    def greeting(self):
        return "from the skin's own code"

    def temperature_unit(self):
        return self.unit.unit_type.outTemp

    def what_it_is_called(self):
        return self.obs.label.outTemp


class Numbers(SearchList):
    def get_extension_list(self, timespan, db_lookup):
        manager = db_lookup()
        row = manager.getSql(
            "SELECT COUNT(*) FROM archive WHERE dateTime > ? AND dateTime <= ?",
            (timespan[0], timespan[1]))
        start, stop, values = weewx.xtypes.get_series(
            "outTemp", TimeSpan(timespan[0], timespan[1]), manager,
            aggregate_type="max", aggregate_interval=3600)
        # A whole series through the converter, which is what an extension
        # does before drawing one. Given a list, a converter that only
        # knows how to convert a number multiplies the list by a float:
        # "can't multiply sequence by non-int of type 'float'", and only on
        # a station whose archive is not already in the page's own unit.
        series_shown = self.generator.converter.convert(values)
        warmest = max((v for v in values[0] if v is not None), default=None)
        # Converted first, as WeeWX's own extensions do: get_series hands
        # back what the archive holds, and turning that into what the page
        # shows is the converter's job, not the helper's.
        shown = self.generator.converter.convert(
            ValueTuple(warmest, values[1], values[2]))
        return [{
            "rows": row[0] if row else 0,
            "buckets": len(values[0]),
            "series_unit": series_shown[1],
            "series_first": series_shown[0][0] if series_shown[0] else None,
            "warmest": ValueHelper(shown, "day", self.generator.formatter,
                                   self.generator.converter),
            "rounded": rounder(1.23456, 2),
            "settled": to_bool("yes"),
            "midnight": startOfDay(timespan[1]),
            "looked_up": search_up(self.generator.skin_dict,
                                   "SKIN_NAME", "none"),
            "flattened": len(accumulateLeaves(self.generator.skin_dict)),
        }]
"""

#: A broken one, to check that it costs only its own names.
BROKEN = """

class Broken(SearchList):
    def get_extension_list(self, timespan, db_lookup):
        raise RuntimeError("this extension is broken")
"""

#: What a template asks the extension for.
EXTENSION_TAGS = """greeting=$greeting()
unit_of=$temperature_unit()
called=$what_it_is_called()
rows=$rows
buckets=$buckets
series_unit=$series_unit
series_first=$series_first
warmest=$warmest
rounded=$rounded
settled=$settled
looked_up=$looked_up
"""

AUSTRIAN = """
[Labels]
    [[Generic]]
        barometer = Luftdruck (AT)
"""

INDEX = """#from datetime import datetime
#include "header.inc"
year=$datetime(2021, 3, 4).year
name=$SKIN_NAME/$SKIN_VERSION
temp=$current.outTemp
label=$obs.label.outTemp
press_label=$obs.label.barometer
press=$day.barometer.avg
heat=$year.heatdeg.sum
cool=$year.cooldeg.sum
extras=$Extras.radar_url
walk=#for $x in $observations#$getattr($current, $x) #end for#
said=$gettext("Current Conditions")
also=$gettext("Sunrise")
point=$day.windDir.avg.ordinal_compass
missing=$current.nosuchreading
guarded=#if $day.nosuchreading.has_data#yes#else#no#end if#
"""

HEADER = ('#import datetime' + chr(10)
          + '#include "deeper.inc"' + chr(10)
          + 'header=yes' + chr(10)
          + 'stamped=$datetime.datetime(2020, 1, 2).year' + chr(10))
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
        # A whole directory, which is how a skin ships its typefaces.
        (skin / "assets").mkdir(exist_ok=True)
        (skin / "assets" / "face.woff2").write_bytes(b"not really a font")
        (skin / "assets" / "deeper").mkdir(exist_ok=True)
        (skin / "assets" / "deeper" / "more.woff").write_bytes(b"nor this")

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

        print("\nan include is included, however deep")
        # Cheetah would resolve these against the process's directory. If
        # that ever comes back, this is where it shows.
        failures += not check("one level", got.get("header"), "yes")
        failures += not check("two levels", got.get("deeper"), "yes")
        # And each part keeps its own imports. Splicing them into one file
        # was the first way this worked, and it puts two meanings of the
        # name `datetime` in one namespace: one file says `#import
        # datetime` and another `#from datetime import datetime`, and
        # whichever loses takes the page down with "module 'datetime' has
        # no attribute 'now'". Both spellings are here on purpose.
        failures += not check("the includer's import still means what it did",
                              got.get("year"), "2021")
        failures += not check("and so does the included file's",
                              got.get("stamped"), "2020")

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
        failures += not check("its stylesheet", (out / "site.css").exists(),
                              True)
        # `copy_once = assets` names a directory, and a directory means all
        # of it. Taking only the files that matched directly left weewx-wdc
        # asking the browser for four typefaces that were never published.
        failures += not check("a whole directory it named",
                              (out / "assets" / "face.woff2").exists(), True)
        failures += not check("and what is under that",
                              (out / "assets" / "deeper" / "more.woff")
                              .exists(), True)
        failures += not check("but not its templates or its config",
                              (out / "index.html.tmpl").exists()
                              or (out / "skin.conf").exists(), False)

        print("\nthe operator can set the skin's own Extras")
        # A skin keeps the things its author meant an operator to
        # change in [Extras]. Editing the skin to change them loses it
        # at the next update, so they are a feed setting -- which is
        # where WeeWX keeps them too. weewx-wdc needs `base_path` here
        # or its stylesheet and its charts are looked for at the root
        # of the site instead of where it was published.
        theirs = Tags(reader, target=units.Target(reader.system),
                      unit_system=reader.system)
        overridden = CheetahFeed(reader, skin, theirs, encoding="utf8",
                                 extras={"radar_url": "/mine.png",
                                         "base_path": "/wdc/"})
        overridden.produce(tmp / "extras")
        got = _read_page(tmp / "extras" / "index.html")
        failures += not check("the operator's value wins",
                              got.get("extras"), "/mine.png")
        failures += not check("and one the skin never had is added too",
                              theirs.extras.get("base_path"), "/wdc/")

        print("\nand a skin's own Python runs, and becomes tags")
        # A WeeWX skin may ship code: `search_list_extensions` names
        # classes, each is handed the generator and asked what it wants
        # to add. weewx-wdc ships eight of them and 2851 lines, and
        # without this not one of its thirteen pages renders -- not
        # "renders with gaps", not at all.
        code = skin / "bin" / "user"
        code.mkdir(parents=True, exist_ok=True)
        (code / "myskin.py").write_text(EXTENSION, encoding="utf-8")
        _with_extensions(skin, "user.myskin.Extras, user.myskin.Numbers")
        (skin / "index.html.tmpl").write_text(
            INDEX + EXTENSION_TAGS, encoding="utf-8")

        coded = Tags(reader, target=units.Target(reader.system),
                     unit_system=reader.system)
        with_code = CheetahFeed(reader, skin, coded, encoding="utf8")
        with_code.produce(tmp / "coded")
        failures += not check("nothing failed", with_code.failed, [])
        got = _read_page(tmp / "coded" / "index.html")

        # An extension that does not override get_extension_list returns
        # itself, and then its methods are the tags. Returning an empty
        # list instead cost weewx-wdc eight pages, all with the same
        # unhelpful "'Unknown' object is not iterable".
        failures += not check("its methods are tags",
                              got.get("greeting"),
                              "from the skin's own code")
        failures += not check("UnitInfoHelper answers",
                              got.get("unit_of"), "degree_C")
        failures += not check("ObsInfoHelper answers",
                              got.get("called"), "Aussentemperatur")

        print("  and one that returns a dictionary adds those names")
        failures += not check("its own SQL ran",
                              int(got.get("rows", "0")) > 0, True)
        failures += not check("get_series came back",
                              int(got.get("buckets", "0")) > 0, True)
        failures += not check("a whole series converts too",
                              got.get("series_unit"), "degree_C")
        failures += not check("and its values with it",
                              float(got.get("series_first", "99")) < 30.0,
                              True)
        # In the skin's own unit and the skin's own word for it: an
        # extension that converts with the generator's converter gets what
        # the page is set to, which is the whole point of handing it one.
        failures += not check("a ValueHelper prints itself, converted",
                              got.get("warmest", "").endswith(" Grad"),
                              True)
        failures += not check("rounder", got.get("rounded"), "1.23")
        failures += not check("to_bool", got.get("settled"), "True")
        failures += not check("search_up found the skin's own key",
                              got.get("looked_up"), "Testing")

        print("  and one that raises costs its own names, not the site")
        (code / "myskin.py").write_text(EXTENSION + BROKEN,
                                        encoding="utf-8")
        _with_extensions(
            skin, "user.myskin.Broken, user.myskin.Extras, "
                  "user.myskin.Numbers")
        survived = CheetahFeed(
            reader, skin,
            Tags(reader, target=units.Target(reader.system),
                 unit_system=reader.system), encoding="utf8")
        survived.produce(tmp / "broken")
        got = _read_page(tmp / "broken" / "index.html")
        failures += not check("the other one still ran",
                              got.get("greeting"),
                              "from the skin's own code")

        # Put the skin back for the checks that follow.
        (skin / "skin.conf").write_text(SKIN_CONF, encoding="utf-8")
        (skin / "index.html.tmpl").write_text(INDEX, encoding="utf-8")

        print("\nand it runs in the language the skin was translated into")
        # A WeeWX skin keeps its translations in lang/de.conf, and those
        # files are not word lists: they carry the unit system, the
        # labels, the compass points and the texts together. Seasons
        # ships eighteen of them. Reading `lang = de` and not loading
        # the file is a page that renders perfectly and is entirely in
        # English.
        (skin / "lang").mkdir(exist_ok=True)
        (skin / "lang" / "de.conf").write_text(GERMAN, encoding="utf-8")
        (skin / "lang" / "de_AT.conf").write_text(AUSTRIAN,
                                                  encoding="utf-8")

        spoken = Tags(reader, target=units.Target(reader.system),
                      unit_system=reader.system)
        german = CheetahFeed(reader, skin, spoken, encoding="utf8",
                             language="de")
        german.produce(tmp / "de")
        page = (tmp / "de" / "index.html").read_text(encoding="utf-8")
        got = dict(line.split("=", 1) for line in page.splitlines()
                   if "=" in line)
        failures += not check("its texts are translated",
                              got.get("said"), "Aktuelle Werte")
        failures += not check("and so are its labels",
                              got.get("press_label"), "Luftdruck")
        failures += not check("and the points of the compass",
                              got.get("point"), "SSO")

        # `unit_system = metricwx` at the top of a translation is a
        # shorthand for a whole [Units][[Groups]] section, and every
        # German translation starts with one: somebody reading German
        # almost certainly wants millimetres.
        failures += not check("its unit system took effect",
                              got.get("temp", "").endswith(" Grad"), True)

        print("  and the skin still wins over its own translation")
        # skin.conf says three decimals of Celsius; the translation says
        # nothing about that, and its own label for degree_C is the same
        # word. What the skin states explicitly stays stated.
        failures += not check("three decimals, as skin.conf says",
                              _decimals(got.get("temp")), 3)

        print("  and a regional file is read on top of its language")
        austrian = CheetahFeed(reader, skin,
                               Tags(reader,
                                    target=units.Target(reader.system),
                                    unit_system=reader.system),
                               encoding="utf8", language="de_AT")
        austrian.produce(tmp / "at")
        page = (tmp / "at" / "index.html").read_text(encoding="utf-8")
        got = dict(line.split("=", 1) for line in page.splitlines()
                   if "=" in line)
        failures += not check("de_AT reads de.conf first",
                              got.get("said"), "Aktuelle Werte")
        # A key the skin does not set itself, so the regional file is the
        # last word on it. `outTemp` would not do: skin.conf names that one,
        # and skin.conf beats both translations, which is the point above.
        failures += not check("then its own on top",
                              got.get("press_label"), "Luftdruck (AT)")

        print("  and a language with no file is said out loud, not guessed")
        klingon = CheetahFeed(reader, skin,
                              Tags(reader,
                                   target=units.Target(reader.system),
                                   unit_system=reader.system),
                              encoding="utf8", language="tlh")
        klingon.produce(tmp / "tlh")
        page = (tmp / "tlh" / "index.html").read_text(encoding="utf-8")
        got = dict(line.split("=", 1) for line in page.splitlines()
                   if "=" in line)
        failures += not check("it renders as written",
                              got.get("label"), "Aussentemperatur")

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
