"""The planets, measured against pyephem.

Two thousand periodic terms are six thousand numbers, and the way they go
wrong is not by producing nonsense: a dropped digit in a coefficient worth a
tenth of an arcsecond moves Mars by an amount no reading finds and no
eyeball catches. Only measuring does. This is the same argument as
`mooncheck.py` and `unitcheck.py`, and in both of those it found real
mistakes.

Six places, from Tromso inside the Arctic circle to Ushuaia near the bottom
of the world, and the four turning points of the year. Position is checked
over a longer stretch than one year, because Jupiter takes twelve to go
round once and Neptune a hundred and sixty -- a series checked at one point
of an orbit is a series checked nowhere.

    PYTHONPATH=/path/to/weewx/src:src python3 tools/planetcheck.py

## What pyephem means by each of these

Three things had to be found out rather than assumed, and each one was
wrong-looking arithmetic until it was:

- **`ephem.Ecliptic(body)` is astrometric, not apparent.** It is built from
  `a_ra` and `a_dec` -- the position with neither aberration nor nutation --
  and `epoch=` only precesses that. `planets.position` is the apparent
  place, so comparing the two directly reports twenty arcseconds of
  aberration as our error. The comparison here goes through `g_ra` and
  `g_dec`, which are what "apparent geocentric" means in pyephem.
- **`earth_distance` is geometric.** It is how far away the planet is now,
  where `planets.position` returns how far the light travelled -- the
  distance to where the planet *was*. For Mars that is fourteen thousand
  kilometres, which is a real difference between two honest answers and not
  an error in either.
- **pyephem models refraction itself.** Handing it a horizon that already
  contains refraction counts it twice. The recipe is its own: pressure off,
  horizon at 34 arcminutes, and the centre of the disc, which is what
  `planets.horizon_for` means by rising.
"""

from __future__ import annotations

import datetime
import math
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

#: Where, and how far north. The two poles of the list are the point: a
#: method that works in Munich and not in Tromso is a method that has not
#: been tested.
PLACES = (
    ("Tromso", 69.6496, 18.9560, "Europe/Oslo"),
    ("Reykjavik", 64.1466, -21.9426, "Atlantic/Reykjavik"),
    ("Kirchdorf", 48.4596, 11.6539, "Europe/Berlin"),
    ("Singapore", 1.3521, 103.8198, "Asia/Singapore"),
    ("Wellington", -41.2866, 174.7756, "Pacific/Auckland"),
    ("Ushuaia", -54.8019, -68.3030, "America/Argentina/Ushuaia"),
)

#: Days of the year to look at. The four turning points and eight between,
#: so a planet is caught at every declination it reaches.
DAYS = (15, 46, 79, 111, 142, 172, 203, 234, 265, 296, 327, 355)

#: The four on their own, for the rising times -- six places times eight
#: planets times three events is enough work already.
TURNS = (79, 172, 265, 355)

#: Years the position is checked over. Spread rather than consecutive: the
#: outer planets barely move in one year, and three points fifteen years
#: apart say more about Saturn than thirty consecutive days do.
YEARS = (2004, 2012, 2020, 2026, 2034, 2042)

#: What counts as a pass, in arcseconds. The cut series is worth six of
#: them at worst (`tools/vsop87trim.py` measures that), pyephem has its own
#: truncation, and the two do not cancel.
POSITION_TOLERANCE = 15.0
#: Pluto is not VSOP87. Meeus 37 is a fit to a hundred years of
#: observations, pyephem uses something else entirely, and half an
#: arcminute between two different theories of the same faint thing is
#: agreement rather than error.
PLUTO_TOLERANCE = 60.0
#: Astronomical units, for the distance. Five thousand kilometres, which is
#: what the cut series is worth at Neptune's range.
DISTANCE_TOLERANCE = 5e-5
#: And Pluto again, for the same reason: two different theories of where it
#: is disagree by a hundred and fifty thousand kilometres out of five
#: billion. Meeus's own worked example, checked below, is what says our
#: half of that disagreement is transcribed right.
PLUTO_DISTANCE_TOLERANCE = 1.5e-3
#: Seconds, for a rising. A minute is already past what anybody reads off a
#: page.
RISE_TOLERANCE = 120.0


def main() -> int:
    try:
        import ephem
    except ImportError:
        print("pyephem is not installed, so there is nothing to compare "
              "against. Install it in the checking environment only:")
        print("    pip install ephem")
        return 2

    from weewx_evo import planets

    epoch = ephem.Date("1970/1/1 00:00:00")

    def to_ts(value: object) -> float:
        return (float(value) - float(epoch)) * 86400.0

    def to_date(when: float) -> object:
        return ephem.Date(epoch + when / 86400.0)

    def bodies(name: str) -> object:
        return getattr(ephem, name.title())()

    failures = 0

    # -- the one check that is not against pyephem ------------------------
    #
    # Pluto's table is three hundred and eighty-seven coefficients that
    # nothing else in this file can vouch for: pyephem uses a different
    # theory, so a disagreement with it could be ours or theirs. Meeus works
    # the same date out in the book, and that is a number with no opinion in
    # it. 13 October 1992 at 0h TD, in the ecliptic of J2000 -- before the
    # precession, because that is where Meeus stops.
    print("Meeus 37.a, the worked example in the book")
    got = planets._pluto_j2000(2448908.5)
    for what, mine, theirs, room in (
            ("longitude", math.degrees(got[0]), 232.74071, 0.00001),
            ("latitude", math.degrees(got[1]), 14.58782, 0.00001),
            ("radius", got[2], 29.711111, 0.000001)):
        ok = abs(mine - theirs) <= room
        failures += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {what:10} {mine:12.6f} "
              f"against {theirs:12.6f}")

    # -- where they are ---------------------------------------------------
    print("\nwhere the planets are, seen from the middle of the Earth")
    os.environ["TZ"] = "UTC"
    try:
        time.tzset()
    except AttributeError:  # pragma: no cover - Windows
        pass

    moments = [_utc(year, day, hour)
               for year in YEARS for day in DAYS for hour in (0, 12)]
    for name in planets.PLANETS:
        apart: list[float] = []
        apart_au: list[float] = []
        for when in moments:
            got_ra, got_dec, got_au = planets.equatorial(when, name)
            body = bodies(name)
            body.compute(to_date(when))
            # g_ra and g_dec, not ra and dec: apparent *geocentric*. With no
            # observer they are the same thing, and saying which is meant
            # costs nothing and saves the next reader an hour.
            want_ra = math.degrees(float(body.g_ra))
            want_dec = math.degrees(float(body.g_dec))
            apart.append(3600.0 * math.hypot(
                _apart(got_ra, want_ra) * math.cos(math.radians(want_dec)),
                got_dec - want_dec))
            apart_au.append(abs(got_au - float(body.earth_distance)))

        limit = PLUTO_TOLERANCE if name == "pluto" else POSITION_TOLERANCE
        worst = max(apart)
        ok = worst <= limit
        failures += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {name:9} worst {worst:6.2f}\", "
              f"median {statistics.median(apart):5.2f}\", "
              f"{len(apart)} moment(s)")

        worst_au = max(apart_au)
        ok = worst_au <= (PLUTO_DISTANCE_TOLERANCE if name == "pluto"
                          else DISTANCE_TOLERANCE)
        failures += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {'':9} distance worst "
              f"{worst_au * 149597870.7:8.0f} km, median "
              f"{statistics.median(apart_au) * 149597870.7:8.0f} km")

    # -- the series on its own --------------------------------------------
    print("\nthe heliocentric series, which is VSOP87 with terms dropped")
    for name in planets.PLANETS:
        apart = []
        for when in moments:
            got_lon, got_lat, got_au = planets.heliocentric(when, name)
            body = bodies(name)
            # The equinox of the date on both sides. pyephem defaults its
            # output to J2000, and comparing that against a series in the
            # equinox of the date reports the precession since 2000 -- a
            # third of a degree in 2026 -- as our mistake.
            body.compute(to_date(when), to_date(when))
            want_lon = math.degrees(float(body.hlon))
            want_lat = math.degrees(float(body.hlat))
            apart.append(3600.0 * math.hypot(
                _apart(got_lon, want_lon) * math.cos(math.radians(want_lat)),
                got_lat - want_lat))

        limit = PLUTO_TOLERANCE if name == "pluto" else POSITION_TOLERANCE
        worst = max(apart)
        ok = worst <= limit
        failures += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {name:9} worst {worst:6.2f}\", "
              f"median {statistics.median(apart):5.2f}\"")

    # -- when they rise ---------------------------------------------------
    print("\nwhen they rise, set and are highest")
    for place, latitude, longitude, zone in PLACES:
        os.environ["TZ"] = zone
        try:
            time.tzset()
        except AttributeError:  # pragma: no cover - Windows
            print("  (needs a POSIX platform for the local day; skipping)")
            return 1 if failures else 0

        watcher = ephem.Observer()
        watcher.lat, watcher.lon = str(latitude), str(longitude)
        # Refraction off, and the 34 arcminutes of it that the definition
        # assumes put in by hand. The centre of the disc, because a planet
        # is a point at this scale and `planets.horizon_for` says so.
        watcher.pressure = 0
        watcher.horizon = "-0:34"

        found: dict[str, list[float]] = {"rise": [], "set": [],
                                         "transit": []}
        blamed: dict[str, tuple[float, str]] = {}
        missing: list[str] = []
        for name in planets.PLANETS:
            for day in TURNS:
                midnight = _local_midnight(2026, day)
                ours = planets.events(midnight, latitude, longitude, name)
                for key, call in (("rise", watcher.next_rising),
                                  ("set", watcher.next_setting),
                                  ("transit", watcher.next_transit)):
                    try:
                        want = to_ts(call(
                            bodies(name), start=to_date(midnight),
                            **({} if key == "transit"
                               else {"use_center": True})))
                    except Exception:
                        continue  # never rises, or never sets
                    # Only what our two-day window was asked about. pyephem
                    # searches until it finds one; a planet that next rises
                    # in nine days is outside the question, not a miss.
                    if want > midnight + 2 * 86400:
                        continue
                    got = ours.get(key)
                    if got is None:
                        missing.append(f"{name} {key}")
                        continue
                    gap = abs(got - want)
                    found[key].append(gap)
                    if gap > blamed.get(key, (0.0, ""))[0]:
                        blamed[key] = (gap, name)

        for key, apart in found.items():
            if not apart:
                continue
            worst = max(apart)
            ok = worst <= RISE_TOLERANCE
            failures += not ok
            print(f"  {'ok  ' if ok else 'FAIL'} {place:11} {key:8} "
                  f"worst {worst:5.1f}s ({blamed[key][1]}), median "
                  f"{statistics.median(apart):5.1f}s, {len(apart)} event(s)")
        if missing:
            print(f"       {place:11} {len(missing)} event(s) we did not "
                  f"find: {', '.join(sorted(set(missing))[:4])}")

    print("\n" + ("FAIL" if failures else "PASS") + f" ({failures} failure(s))")
    return 1 if failures else 0


def _utc(year: int, day: int, hour: int) -> float:
    return datetime.datetime(year, 1, 1, hour, tzinfo=datetime.UTC) \
        .timestamp() + (day - 1) * 86400


def _local_midnight(year: int, day: int) -> float:
    start = datetime.datetime(year, 1, 1) + datetime.timedelta(days=day - 1)
    return start.replace(hour=0, minute=0, second=0,
                         microsecond=0).timestamp()


def _apart(one: float, other: float) -> float:
    """How far apart two bearings are, the short way round."""
    gap = abs(one - other) % 360.0
    return min(gap, 360.0 - gap)


if __name__ == "__main__":
    raise SystemExit(main())
