"""Check sunrise and sunset, against pyephem and against WeeWX's fallback.

A chart shades night against these. A minute out is invisible; ten minutes out
is a band that visibly does not line up with the temperature falling.

There are three answers and they are not equally good:

  * **pyephem** is the accurate one, and is what WeeWX uses when it is there.
    It is the reference here.
  * **`weewx_evo.sun`'s own arithmetic**, which is what a station without
    pyephem runs. This must match pyephem closely, or installing a package
    would silently move the night bands.
  * **`weeutil.Sun`**, Paul Schlyter's algorithm, which is what WeeWX falls
    back to. It is a simplification and drifts several minutes at high
    latitude. Reported for context, not as a verdict -- holding this project
    to it would mean copying its error.

    wsl -d Ubuntu -- bash -lc 'source ~/venvs/weewx/bin/activate &&
        cd /mnt/d/Git/weewx-evo && PYTHONPATH=/mnt/d/Git/weewx/src:src
        python3 tools/suncheck.py'
"""

from __future__ import annotations

import calendar
import math
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

os.environ["TZ"] = "UTC"
time.tzset()

import weewx_evo.sun as sun  # noqa: E402

#: Somewhere ordinary, somewhere far north where the answer is hard, somewhere
#: on the equator, and two south of it -- one of them far enough south that
#: midsummer is in December.
PLACES = [
    ("Kirchdorf", 52.0, 9.0),
    ("Seattle", 47.6, -122.3),
    ("Tromso", 69.65, 18.96),
    ("Quito", -0.18, -78.47),
    ("Wellington", -41.29, 174.78),
    ("Ushuaia", -54.8, -68.3),
]

#: Midsummer, midwinter and the two equinoxes, where the errors are largest.
DAYS = ["2026-03-20", "2026-06-21", "2026-09-22", "2026-12-21", "2026-08-26"]

#: Against pyephem. A minute is below anything a chart can show, and it is
#: what the simple formula gives: a few seconds most of the year, worst around
#: forty at a solstice, where it leaves out the small terms pyephem carries.
TOLERANCE = 60.0

#: Against weeutil.Sun, which is a different algorithm and drifts. Only
#: reported; nothing fails on it.
LOOSE = 600.0


def stamp(day: str) -> int:
    y, m, d = (int(p) for p in day.split("-"))
    return calendar.timegm((y, m, d, 0, 0, 0, 0, 0, 0))


def clock(ts: float | None) -> str:
    return "--:--:--" if ts is None else time.strftime("%H:%M:%S",
                                                       time.gmtime(ts))


def apart(ours: float | None, theirs: float | None) -> float | None:
    """How far apart two moments are, allowing for the day they land in.

    `weeutil.Sun` returns hours relative to a UTC day, so a sunset in Seattle
    comes back as 02:27 on the following one. Compared straight, that is a
    whole day out; compared as clock times, it is five seconds.
    """
    if ours is None or theirs is None:
        return None
    gap = abs(ours - theirs) % 86400.0
    return min(gap, 86400.0 - gap)


def main() -> int:
    try:
        import ephem
    except ImportError:
        ephem = None
    try:
        from weeutil import Sun as schlyter
    except ImportError:
        schlyter = None

    failures = 0
    print(f"pyephem: {'installed' if ephem else 'not installed'}")

    # The one that matters. Everything else in this file is context.
    print("\nthe built-in arithmetic against pyephem")
    if ephem is None:
        print("  skipped: pyephem is not installed here, so there is nothing"
              " to hold it against")
    else:
        print(f"  {'place':<11} {'day':<11} {'own rise':<9} {'pyephem':<9}"
              f" {'own set':<9} {'pyephem':<9}  apart")
        worst = 0.0
        keep = sun._ephem
        sun._ephem = None
        try:
            for name, lat, lon in PLACES:
                for day in DAYS:
                    ts = stamp(day)
                    ours = sun.events(ts, lat, lon)
                    sun._ephem = keep
                    theirs = sun.events(ts, lat, lon)
                    sun._ephem = None

                    if ours["sunrise"] is None or theirs["sunrise"] is None:
                        agree = (ours["sunrise"] is None) == \
                            (theirs["sunrise"] is None)
                        failures += not agree
                        print(f"  {name:<11} {day:<11} no crossing"
                              f"   {'-- and pyephem agrees' if agree else 'FAIL: pyephem found one'}")
                        continue

                    gap = max(apart(ours["sunrise"], theirs["sunrise"]),
                              apart(ours["sunset"], theirs["sunset"]))
                    worst = max(worst, gap)
                    failures += gap > TOLERANCE
                    print(f"  {name:<11} {day:<11} {clock(ours['sunrise']):<9}"
                          f" {clock(theirs['sunrise']):<9}"
                          f" {clock(ours['sunset']):<9}"
                          f" {clock(theirs['sunset']):<9} {gap:6.1f}s"
                          + ("" if gap <= TOLERANCE else "  <--"))
        finally:
            sun._ephem = keep
        print(f"  worst: {worst:.1f}s  (allowed {TOLERANCE:.0f}s)")

        print("\n  and the declination underneath it")
        biggest = 0.0
        for day in DAYS:
            y, m, d = (int(p) for p in day.split("-"))
            ts = calendar.timegm((y, m, d, 12, 0, 0, 0, 0, 0))
            mine, _, distance = sun.solar(ts)
            body = ephem.Sun(ephem.Date(
                ephem.Date("1970/1/1 00:00:00") + ts / 86400.0))
            theirs = math.degrees(float(body.dec))
            biggest = max(biggest, abs(mine - theirs))
            print(f"    {day}  own {mine:8.4f}deg  pyephem {theirs:8.4f}deg"
                  f"  {abs(mine - theirs):.4f} apart"
                  f"   distance {distance:.5f} AU")
        failures += biggest > 0.01
        print(f"    worst: {biggest:.4f} degrees")

    print("\nfor context: weeutil.Sun, which is WeeWX's own fallback")
    print("  It is a simplification, and this is how far it drifts from")
    print("  pyephem. Nothing here fails -- matching it would mean copying it.")
    if schlyter is None or ephem is None:
        print("  skipped")
    else:
        worst_theirs = 0.0
        for name, lat, lon in PLACES:
            for day in DAYS:
                ts = stamp(day)
                y, m, d = (int(p) for p in day.split("-"))
                accurate = sun.events(ts, lat, lon)
                if accurate["sunrise"] is None:
                    continue
                try:
                    rise_h, set_h = schlyter.sunRiseSet(y, m, d, lon, lat)
                except Exception:  # noqa: BLE001
                    continue
                theirs_rise, theirs_set = ts + rise_h * 3600.0, ts + set_h * 3600.0
                gap = max(apart(accurate["sunrise"], theirs_rise),
                          apart(accurate["sunset"], theirs_set))
                worst_theirs = max(worst_theirs, gap)
                mark = "" if gap <= LOOSE else "  <-- and that is theirs"
                if gap > 120:
                    print(f"  {name:<11} {day:<11} weeutil.Sun is {gap:6.1f}s"
                          f" from pyephem{mark}")
        print(f"  worst: {worst_theirs:.1f}s")

    print("\nwhat a chart gets: a day in Kirchdorf")
    start = stamp("2026-08-26")
    bands = sun.day_night(start, start + 86400, 52.0, 9.0)
    if not bands:
        print("  FAIL nothing came back")
        failures += 1
    else:
        print(f"  starts in {bands['first']}")
        for moment in bands["transitions"]:
            print(f"    crosses at {clock(moment)}")
        for band in bands["twilight"]:
            print(f"    {band['dir']:<5} {clock(band['from'])}"
                  f" -> {clock(band['to'])}")
        ok = (bands["first"] == "night" and len(bands["transitions"]) == 2
              and bands["transitions"][0] < bands["transitions"][1]
              and len(bands["twilight"]) == 2)
        failures += not ok
        print(f"  {'ok' if ok else 'FAIL'}: night, sunrise, sunset,"
              f" one dawn and one dusk")

    print("\na week in Tromso in June, where the sun does not set")
    start = stamp("2026-06-18")
    bands = sun.day_night(start, start + 7 * 86400, 69.65, 18.96)
    ok = bands is None
    failures += not ok
    print(f"  {'ok' if ok else 'FAIL'}: "
          + ("nothing to shade -- polar day" if ok
             else f"got {bands['first']},"
                  f" {len(bands['transitions'])} crossing(s)"))

    print("\na week in Tromso in December, where it does not rise")
    start = stamp("2026-12-15")
    bands = sun.day_night(start, start + 7 * 86400, 69.65, 18.96)
    ok = bands is None
    failures += not ok
    print(f"  {'ok' if ok else 'FAIL'}: "
          + ("nothing to shade -- polar night" if ok
             else f"got {bands['first']}, "
                  f"{len(bands['transitions'])} crossing(s)"))

    print("\na week in Kirchdorf, which is the ordinary case")
    start = stamp("2026-08-23")
    bands = sun.day_night(start, start + 7 * 86400, 52.0, 9.0)
    ok = bands is not None and len(bands["transitions"]) == 14 \
        and bands["transitions"] == sorted(set(bands["transitions"]))
    failures += not ok
    print(f"  {'ok' if ok else 'FAIL'}: "
          + ("nothing" if bands is None
             else f"{len(bands['transitions'])} crossing(s) over seven days,"
                  f" {len(bands['twilight'])} twilight band(s)"))

    print("\n" + ("FAIL" if failures else "PASS") + f" ({failures} failure(s))")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
