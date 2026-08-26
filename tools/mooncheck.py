"""The moon, measured against pyephem.

Two tables of sixty terms are two hundred and forty numbers, and a single
digit wrong in any of them produces an answer that looks entirely reasonable
and is minutes out. Reading them again does not find that; only measuring
does -- which is the same reason `unitcheck.py` exists, and it found three
real transcription errors there.

Six places, from Tromso inside the Arctic circle to Ushuaia near the bottom
of the world, over a year. The far north is where a small error in position
becomes a large one in time: the moon crosses the horizon so obliquely that
a hundredth of a degree is minutes.

    PYTHONPATH=/path/to/weewx/src:src python3 tools/mooncheck.py
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

#: Days of the year to look at. Solstices, equinoxes, and a few between, so
#: the moon is caught at every declination it reaches.
DAYS = (15, 46, 79, 111, 142, 172, 203, 234, 265, 296, 327, 355)

#: What counts as a pass. A minute on a rising time is well past what
#: anybody reads off a page, and past what the difference between one
#: definition of the horizon and another is worth arguing about.
RISE_TOLERANCE = 120.0
#: Degrees, for the position itself.
POSITION_TOLERANCE = 0.02


def main() -> int:
    try:
        import ephem
    except ImportError:
        print("pyephem is not installed, so there is nothing to compare "
              "against. Install it in the checking environment only:")
        print("    pip install ephem")
        return 2

    from weewx_evo import moon

    epoch = ephem.Date("1970/1/1 00:00:00")

    def to_ts(value: object) -> float:
        return (float(value) - float(epoch)) * 86400.0

    def to_date(when: float) -> object:
        return ephem.Date(epoch + when / 86400.0)

    failures = 0
    year = 2026

    print("where the moon is")
    gaps = {"longitude": [], "latitude": [], "distance": []}
    for day in DAYS:
        for hour in (0, 6, 12, 18):
            when = _utc(year, day, hour)
            body = ephem.Moon()
            body.compute(to_date(when))
            # Of the date, not of J2000. pyephem defaults its Ecliptic to
            # the J2000 equinox and Meeus 47 produces the equinox of the
            # date; compared without saying so, every longitude is out by
            # the precession since 2000, which in 2026 is 0.36 degrees --
            # a constant offset that looks exactly like a mistyped term.
            got_lon, got_lat, got_km = moon.position(when)
            here = ephem.Ecliptic(body, epoch=to_date(when))
            want_lon = _degrees(here.lon)
            # No modulo on the latitude: it runs -5 to +5, and wrapping it
            # into 0..360 turns every southern one into 355 and every
            # comparison into nonsense.
            want_lat = math.degrees(float(here.lat))
            want_km = body.earth_distance * ephem.meters_per_au / 1000.0

            gaps["longitude"].append(_apart(got_lon, want_lon))
            gaps["latitude"].append(abs(got_lat - want_lat))
            gaps["distance"].append(abs(got_km - want_km))

    for name, found in gaps.items():
        worst = max(found)
        limit = POSITION_TOLERANCE if name != "distance" else 30.0
        unit = "deg" if name != "distance" else "km"
        ok = worst <= limit
        failures += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {name:10} worst {worst:.4f} "
              f"{unit}, median {statistics.median(found):.4f}")

    print("\nwhen it rises, sets and is highest")
    for place, latitude, longitude, zone in PLACES:
        os.environ["TZ"] = zone
        try:
            time.tzset()
        except AttributeError:  # pragma: no cover - Windows
            print("  (needs a POSIX platform for the local day; skipping)")
            return 0

        watcher = ephem.Observer()
        watcher.lat, watcher.lon = str(latitude), str(longitude)
        watcher.pressure = 0
        # pyephem's own moonrise convention: the upper limb, refracted.
        watcher.horizon = "-0:34"

        found: dict[str, list[float]] = {"rise": [], "set": [], "transit": []}
        missing = 0
        for day in DAYS:
            midnight = _local_midnight(year, day)
            ours = moon.events(midnight, latitude, longitude)
            watcher.date = to_date(midnight)
            body = ephem.Moon()

            for key, call in (("rise", watcher.next_rising),
                              ("set", watcher.next_setting),
                              ("transit", watcher.next_transit)):
                try:
                    want = to_ts(call(body, start=to_date(midnight)))
                except Exception:
                    continue
                got = ours.get(key)
                if got is None:
                    missing += 1
                    continue
                found[key].append(abs(got - want))

        for key, apart in found.items():
            if not apart:
                continue
            worst = max(apart)
            ok = worst <= RISE_TOLERANCE
            failures += not ok
            print(f"  {'ok  ' if ok else 'FAIL'} {place:11} {key:8} "
                  f"worst {worst:5.1f}s, median "
                  f"{statistics.median(apart):5.1f}s, {len(apart)} day(s)")
        if missing:
            print(f"       {place:11} {missing} event(s) we did not find")

    print("\nwhen it is new and full")
    os.environ["TZ"] = "UTC"
    try:
        time.tzset()
    except AttributeError:  # pragma: no cover - Windows
        pass
    apart_by_phase: dict[str, list[float]] = {}
    for day in DAYS:
        when = _utc(year, day, 12)
        for name, fraction, call in (
                ("new", 0.0, ephem.next_new_moon),
                ("first quarter", 0.25, ephem.next_first_quarter_moon),
                ("full", 0.5, ephem.next_full_moon),
                ("last quarter", 0.75, ephem.next_last_quarter_moon)):
            want = to_ts(call(to_date(when)))
            got = moon.phase_event(when, fraction)
            apart_by_phase.setdefault(name, []).append(abs(got - want))

    for name, apart in apart_by_phase.items():
        worst = max(apart)
        ok = worst <= RISE_TOLERANCE
        failures += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {name:14} worst {worst:5.1f}s, "
              f"median {statistics.median(apart):5.1f}s")

    print("\n" + ("FAIL" if failures else "PASS") + f" ({failures} failure(s))")
    return 1 if failures else 0


def _utc(year: int, day: int, hour: int) -> float:
    return datetime.datetime(year, 1, 1, hour, tzinfo=datetime.timezone.utc) \
        .timestamp() + (day - 1) * 86400


def _local_midnight(year: int, day: int) -> float:
    start = datetime.datetime(year, 1, 1) + datetime.timedelta(days=day - 1)
    return start.replace(hour=0, minute=0, second=0,
                         microsecond=0).timestamp()


def _degrees(angle: object) -> float:
    return math.degrees(float(angle)) % 360.0


def _apart(one: float, other: float) -> float:
    """How far apart two bearings are, the short way round."""
    gap = abs(one - other) % 360.0
    return min(gap, 360.0 - gap)


if __name__ == "__main__":
    raise SystemExit(main())
