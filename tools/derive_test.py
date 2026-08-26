"""Check the derived readings against what WeeWX actually wrote.

These formulas decide numbers that go into a database WeeWX will read back,
so agreeing with WeeWX matters more than being right in the abstract. The
reference database has years of records where WeeWX computed dew point, heat
index and the rest from readings that are in the same row -- which makes it a
test oracle nobody had to write.

    python tools/derive_test.py reference/weewx.sdb

The one that is not a convenience is `rain`. Almost no console sends it: they
send running totals and expect the difference to be taken. Without it there is
no rainfall in the record at all, and the daily rain summary is a sum of
nothing.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from weewx_evo import derive  # noqa: E402
from weewx_evo.units import US  # noqa: E402


def check(label: str, got: object, want: object) -> bool:
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: {got!r}" + ("" if ok else f" != {want!r}"))
    return ok


def close(label: str, got: float | None, want: float | None,
          tolerance: float) -> bool:
    if got is None or want is None:
        ok = got is None and want is None
        print(f"  {'ok  ' if ok else 'FAIL'} {label}: {got!r} vs {want!r}")
        return ok
    off = abs(got - want)
    ok = off <= tolerance
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: {got:.3f} vs {want:.3f} "
          f"(off by {off:.4f}, allowed {tolerance})")
    return ok


def against_weewx(path: Path) -> int:
    """Recompute what WeeWX computed, from the same row, and compare."""
    failures = 0
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)

    # A row with everything the formulas need, and everything they produce.
    row = conn.execute(
        "SELECT dateTime, usUnits, outTemp, outHumidity, windSpeed, pressure,"
        " dewpoint, heatindex, windchill, humidex, appTemp, altimeter,"
        " cloudbase, inTemp, inHumidity, inDewpoint"
        " FROM archive WHERE outTemp IS NOT NULL AND outHumidity IS NOT NULL"
        " AND windSpeed IS NOT NULL AND dewpoint IS NOT NULL"
        " AND heatindex IS NOT NULL AND humidex IS NOT NULL"
        " ORDER BY dateTime DESC LIMIT 1").fetchone()
    if row is None:
        print("  -- no row in this database has both the inputs and the "
              "outputs; skipping")
        return 0

    (ts, units, t, rh, wind, pressure, dewpoint, heatindex, windchill,
     humidex, apptemp, altimeter, cloudbase, in_t, in_rh, in_dewpoint) = row
    print(f"  against the record of {ts}: outTemp={t}, outHumidity={rh}, "
          f"windSpeed={wind}")
    print()

    # Tolerances are generous by design. WeeWX stores what it computed at
    # full precision; small differences come from the order of operations,
    # not from a different formula. A tenth of a degree would be a different
    # formula and is what this is looking for.
    ours = derive.dewpoint_c(derive._f_to_c(t) if units == US else t, rh)
    failures += not close("dewpoint", derive._from_c(ours, units), dewpoint, 0.05)

    ours = derive.heatindex_f(t if units == US else derive._c_to_f(t), rh)
    failures += not close("heatindex", derive._from_f(ours, units), heatindex,
                          0.05)

    ours = derive.humidex_c(derive._f_to_c(t) if units == US else t, rh)
    failures += not close("humidex", derive._from_c(ours, units), humidex, 0.05)

    ours = derive.windchill_c(derive._f_to_c(t) if units == US else t,
                              derive._speed_kph(wind, units))
    failures += not close("windchill", derive._from_c(ours, units), windchill,
                          0.05)

    ours = derive.apptemp_c(derive._f_to_c(t) if units == US else t, rh,
                            derive._speed_mps(wind, units))
    failures += not close("appTemp", derive._from_c(ours, units), apptemp, 0.05)

    if in_t is not None and in_rh is not None and in_dewpoint is not None:
        ours = derive.dewpoint_c(derive._f_to_c(in_t) if units == US else in_t,
                                 in_rh)
        failures += not close("inDewpoint", derive._from_c(ours, units),
                              in_dewpoint, 0.05)

    if cloudbase is not None:
        feet = derive.cloudbase_ft(t if units == US else derive._c_to_f(t), rh,
                                   440.0 * 3.280839895)
        got = feet if units == US else (feet / 3.280839895 if feet else None)
        # Cloud base multiplies the spread by 1000/4.4, so a hundredth of a
        # degree in the dew point becomes a couple of feet here.
        failures += not close("cloudbase", got, cloudbase, 15.0)

    # maxSolarRad is the one where a simplification is invisible until it is
    # measured: leaving out Earth's distance and the refraction term in the
    # air mass was 1.8% out, which looks like a plausible number.
    solar = conn.execute(
        "SELECT dateTime, maxSolarRad FROM archive WHERE maxSolarRad > 100"
        " ORDER BY dateTime DESC LIMIT 1").fetchone()
    if solar:
        when, theirs = solar
        ours = derive.max_solar_rad(48.4596, 11.6539, 440.0, when)
        failures += not close("maxSolarRad", ours, theirs, theirs * 0.005)

    if pressure is not None and altimeter is not None:
        inhg = pressure if units == US else pressure * 0.0295299830714
        value = derive.altimeter_inhg(inhg, 440.0 * 3.280839895)
        got = value if units == US else (value / 0.0295299830714 if value else None)
        failures += not close("altimeter", got, altimeter, 0.01)

    return failures


def rain_tests() -> int:
    """The one that is a measurement rather than a convenience."""
    print("\nrain, which is a difference and not a reading")
    failures = 0

    # A console sending running totals, which is what almost all of them do.
    deriver = derive.Deriver()
    packets = [
        {"dateTime": 1000, "usUnits": US, "dayRain": 0.10},
        {"dateTime": 1300, "usUnits": US, "dayRain": 0.10},
        {"dateTime": 1600, "usUnits": US, "dayRain": 0.14},
        {"dateTime": 1900, "usUnits": US, "dayRain": 0.14},
    ]
    got = [deriver.apply(dict(p)).get("rain") for p in packets]
    # The first has no predecessor: no delta, rather than posting the whole
    # day's rain as having fallen in one interval.
    failures += not check("the first packet has no delta", got[0], None)
    failures += not check("no change is zero, not missing", got[1], 0.0)
    failures += not check("and a change is the difference",
                          round(got[2], 4), 0.04)
    failures += not check("then zero again", got[3], 0.0)

    print("\n  midnight, when the total resets")
    deriver = derive.Deriver()
    deriver.apply({"dateTime": 1000, "usUnits": US, "dayRain": 2.50})
    after = deriver.apply({"dateTime": 1300, "usUnits": US, "dayRain": 0.02})
    # The total went down. The new value is what has fallen since the reset --
    # treating it as a negative delta would subtract a day's rain from the
    # month.
    failures += not check("the new total is the amount", after.get("rain"), 0.02)

    print("\n  a station that sends rain itself is left alone")
    deriver = derive.Deriver()
    deriver.apply({"dateTime": 1000, "usUnits": US, "dayRain": 0.10})
    sent = deriver.apply({"dateTime": 1300, "usUnits": US, "dayRain": 0.20,
                          "rain": 0.09})
    failures += not check("its value stands", sent["rain"], 0.09)
    # But the total is still remembered, so a later packet without `rain`
    # still produces a delta.
    later = deriver.apply({"dateTime": 1600, "usUnits": US, "dayRain": 0.25})
    failures += not check("and the running total was still followed",
                          round(later["rain"], 4), 0.05)

    print("\n  a restart takes no delta rather than inventing one")
    deriver.forget()
    first = deriver.apply({"dateTime": 1900, "usUnits": US, "dayRain": 0.30})
    failures += not check("nothing", first.get("rain"), None)
    return failures


def policy_tests() -> int:
    print("\nwhat wins: the station or us")
    failures = 0

    warm = {"dateTime": 1000, "usUnits": US, "outTemp": 70.0,
            "outHumidity": 50.0, "windSpeed": 5.0}

    prefer = derive.Deriver()
    filled = prefer.apply(dict(warm))
    failures += not check("prefer_hardware fills what is missing",
                          "dewpoint" in filled, True)

    theirs = dict(warm, dewpoint=99.0)
    failures += not check("and leaves what was sent",
                          prefer.apply(theirs)["dewpoint"], 99.0)

    always = derive.Deriver(how={"dewpoint": "software"})
    failures += not check("software overrides the station",
                          always.apply(dict(warm, dewpoint=99.0))["dewpoint"] != 99.0,
                          True)

    never = derive.Deriver(how={"dewpoint": "hardware"})
    failures += not check("hardware never calculates",
                          never.apply(dict(warm)).get("dewpoint"), None)
    return failures


def edge_tests() -> int:
    print("\nthe edges, where a formula stops applying")
    failures = 0

    # Wind chill is not defined above 10 C or below 4.8 km/h, and heat index
    # is not defined below 40 F. Both return the temperature there, which is
    # WeeWX's convention -- returning None instead would leave gaps in a
    # series that has no gap.
    failures += not check("no wind chill in mild weather",
                          derive.windchill_c(15.0, 20.0), 15.0)
    failures += not check("nor in still air", derive.windchill_c(-5.0, 2.0), -5.0)
    failures += not check("no heat index when cold",
                          derive.heatindex_f(30.0, 50.0), 30.0)

    failures += not check("no dew point without humidity",
                          derive.dewpoint_c(20.0, None), None)
    failures += not check("nor at zero humidity", derive.dewpoint_c(20.0, 0), None)
    failures += not check("windrun needs a span", derive.windrun(5.0, 0), None)
    failures += not check("and is speed times time",
                          derive.windrun(6.0, 3600), 6.0)

    print("\n  the sun, which nothing measures")
    # Kirchdorf, midsummer noon UTC. Not a precise figure -- what matters is
    # that it is a plausible clear-sky value and zero at night.
    noon = derive.max_solar_rad(48.46, 11.65, 440.0, 1750248000)
    failures += not check("a plausible midday value",
                          noon is not None and 700 < noon < 1100, True)
    night = derive.max_solar_rad(48.46, 11.65, 440.0, 1750204800)
    failures += not check("and nothing at night", night, 0.0)
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("database", nargs="?", type=Path,
                        default=Path("reference/weewx.sdb"))
    args = parser.parse_args()

    failures = 0
    if args.database.exists():
        print(f"against {args.database}, which WeeWX wrote")
        failures += against_weewx(args.database)
    else:
        print(f"-- {args.database} is not here; skipping the comparison with "
              "WeeWX")

    failures += rain_tests()
    failures += policy_tests()
    failures += edge_tests()

    print("\n" + ("FAIL" if failures else "PASS") + f" ({failures} failure(s))")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
