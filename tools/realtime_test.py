#!/usr/bin/env python3
"""The Cumulus `realtime.txt` and APRS `wxnow.txt` feed.

Both formats are positional and neither is documented anywhere
authoritative, so what this checks is position and width: a field in the
wrong place is a wrong reading rather than an error, and nothing downstream
complains.

The other thing it checks is the unit handling, which is the part that will
bite somebody. Cumulus puts no unit in the file -- the reader has to be
configured to match -- so a station that switches this feed from metric to US
has silently changed what every consumer of it reads.

    python tools/realtime_test.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from weewx_evo import units
from weewx_evo.feeds.realtime import RealtimeFeed, _compass

FAILURES: list[str] = []
CHECKS = 0


def check(what: str, got: object, want: object) -> None:
    global CHECKS
    CHECKS += 1
    if got != want:
        FAILURES.append(f"{what}\n    got  {got!r}\n    want {want!r}")


def ok(what: str, condition: bool) -> None:
    check(what, bool(condition), True)


class FakeReader:
    """Stands in for the live table."""

    def __init__(self, record: dict | None) -> None:
        self._record = record

    def packet(self) -> dict | None:
        return self._record


# 2026-08-27 15:30:00 UTC. The line carries local time, so the test only
# looks at the shape of those two fields rather than their value.
RECORD = {
    "dateTime": 1756308600, "usUnits": units.METRICWX,
    "outTemp": 23.4, "outHumidity": 61.0, "dewpoint": 15.6,
    "windSpeed": 3.2, "windGust": 7.1, "windDir": 245.0,
    "rainRate": 2.4, "dayRain": 2.6, "hourRain": 1.4,
    "barometer": 1013.2,
}


def test_field_order() -> None:
    """Positional: the reader counts spaces."""
    feed = RealtimeFeed(FakeReader(RECORD), unit_system=units.METRICWX,
                        target=units.Target(units.METRICWX),
                        station="Kirchdorf")
    parts = feed.line(RECORD).split(" ")

    # Cumulus's own date and time formats. Not ISO, not a four-digit year:
    # readers parse them by length.
    check("the date is dd/mm/yy", len(parts[0]), 8)
    ok("with slashes", parts[0].count("/") == 2)
    check("the time is HH:MM:SS", len(parts[1]), 8)
    ok("with colons", parts[1].count(":") == 2)

    check("temperature is third", parts[2], "23.4")
    check("humidity fourth", parts[3], "61")
    check("dew point fifth", parts[4], "15.6")
    check("wind speed sixth", parts[5], "3.2")
    check("gust seventh", parts[6], "7.1")
    check("bearing eighth", parts[7], "245")
    check("rain rate ninth", parts[8], "2.4")
    check("today's rain tenth", parts[9], "2.6")
    check("pressure eleventh", parts[10], "1013.2")
    check("and the bearing as a word after that", parts[11], "WSW")

    # The unit letters. Not a conversion -- a note for whoever reads the file.
    ok("the units are named", "C" in parts and "m/s" in parts)
    ok("and the station is last", parts[-1] == "Kirchdorf")


def test_units_follow_the_setting() -> None:
    """Cumulus puts no unit in the file, so this has to match the consumer."""
    metric = RealtimeFeed(FakeReader(RECORD), target=units.Target(units.METRICWX))
    imperial = RealtimeFeed(FakeReader(RECORD), target=units.Target(units.US))

    check("metric temperature", metric.line(RECORD).split(" ")[2], "23.4")
    check("US temperature", imperial.line(RECORD).split(" ")[2], "74.1")
    check("metric pressure", metric.line(RECORD).split(" ")[10], "1013.2")
    check("US pressure", imperial.line(RECORD).split(" ")[10], "29.9")

    # The letters have to follow, or a reader configured from them is wrong.
    ok("the metric line says C", " C " in metric.line(RECORD))
    ok("the US line says F", " F " in imperial.line(RECORD))
    ok("and the wind unit follows too", " mph " in imperial.line(RECORD))


def test_absent_readings() -> None:
    """The two formats disagree about how to say "no reading", and both are
    followed rather than picking one."""
    bare = {"dateTime": 1756308600, "usUnits": units.METRICWX, "outTemp": 12.0}
    feed = RealtimeFeed(FakeReader(bare), target=units.Target(units.METRICWX))

    parts = feed.line(bare).split(" ")
    # Cumulus has no way to say it: the position must hold something, so a
    # zero it is. A lie, and the alternative is a line nobody can parse.
    check("realtime.txt writes a zero", parts[3], "0")
    check("and keeps the reading it has", parts[2], "12.0")
    check("a missing bearing has no compass word", parts[11], "---")

    # `wxnow.txt` does have a way, and uses it.
    line = feed.wxnow_line(bare).split("\n")[1]
    ok("wxnow.txt writes dots for the wind", ".../...g..." in line)
    ok("and for the humidity", "h.." in line)
    ok("and for the pressure", "b....." in line)


def test_wxnow_widths() -> None:
    """Fixed width, US customary, whatever the realtime.txt setting says.

    APRS defines the units; they are not the operator's to choose, and a
    metric wxnow.txt is a station reporting a gale as a breeze.
    """
    feed = RealtimeFeed(FakeReader(RECORD), target=units.Target(units.METRICWX))
    line = feed.wxnow_line(RECORD).split("\n")[1]

    # 3.2 m/s is 7.16 mph; 7.1 m/s is 15.88; 23.4 C is 74.1 F.
    check("bearing, speed, gust and temperature",
          line[:15], "245/007g016t074")
    # Rain in hundredths of an inch: 1.4 mm is 0.055 in, 2.6 mm is 0.102 in.
    check("the hour's rain and the day's", line[15:23], "r006P010")
    check("humidity", line[23:26], "h61")
    check("pressure in tenths of a millibar", line[26:32], "b10132")

    # The header line is the date APRS parses: `Aug 27 2026 17:30`.
    header = feed.wxnow_line(RECORD).split("\n")[0]
    check("the header is a month, day, year and time",
          len(header.split(" ")), 4)
    ok("with a two-digit clock", ":" in header.split(" ")[3])


def test_producing(tmp: Path) -> None:
    feed = RealtimeFeed(FakeReader(RECORD), target=units.Target(units.METRICWX))
    made = feed.produce(tmp)
    check("two files", sorted(str(f) for f in made.files),
          ["realtime.txt", "wxnow.txt"])
    ok("realtime.txt is one line", len(
        (tmp / "realtime.txt").read_text(encoding="utf-8").strip().split("\n")) == 1)
    # Written beside and renamed: a consumer reading half a line of
    # positional data parses it as something else rather than failing.
    ok("nothing partial is left behind",
       not list(tmp.glob("*.part")))

    empty = RealtimeFeed(FakeReader(None))
    made = empty.produce(tmp / "empty")
    check("a station with nothing yet writes nothing", made.files, [])
    ok("and says so", "nothing" in made.note)


def test_compass() -> None:
    check("north", _compass(0.0), "N")
    check("just past north", _compass(11.0), "N")
    check("north-north-east", _compass(12.0), "NNE")
    check("east", _compass(90.0), "E")
    check("west-south-west", _compass(245.0), "WSW")
    # 349 rounds up past 348.75, which is back to north.
    check("almost all the way round", _compass(349.0), "N")
    check("and all the way round", _compass(360.0), "N")
    check("nothing at all", _compass(None), "---")


def main() -> int:
    test_field_order()
    test_units_follow_the_setting()
    test_absent_readings()
    test_wxnow_widths()
    test_compass()
    with tempfile.TemporaryDirectory() as tmp:
        test_producing(Path(tmp))

    print()
    for failure in FAILURES:
        print("FAIL", failure)
    print(f"{CHECKS} checks, {len(FAILURES)} failed")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
