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

from weewx_evo import derive
from weewx_evo.units import US


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


def moisture_tests() -> int:
    """What the air is carrying, rather than how close to full it is.

    Checked against textbook numbers rather than against each other: two
    formulas that agree with one another and with nothing else is the
    failure mode here, and it is invisible.
    """
    print("\nwhat the air is actually carrying")
    failures = 0

    # 20 C: the saturation vapour pressure is about 23.4 mbar. Magnus, with
    # the coefficients `dewpoint_c` already uses, read forwards.
    failures += not close("saturation vapour pressure at 20 C",
                          derive.sat_vapor_pressure_mbar(20.0), 23.4, 0.2)
    failures += not close("and at 0 C",
                          derive.sat_vapor_pressure_mbar(0.0), 6.11, 0.05)
    # At 50 % it is half of that, by definition.
    failures += not close("half of it at 50 %",
                          derive.vapor_pressure_mbar(20.0, 50.0), 11.7, 0.15)

    # 20 C at 50 % holds about 8.6 g of water per cubic metre.
    failures += not close("absolute humidity at 20 C and 50 %",
                          derive.absolute_humidity(20.0, 50.0), 8.65, 0.1)
    failures += not close("twice that when saturated",
                          derive.absolute_humidity(20.0, 100.0), 17.3, 0.2)
    # Cold air holds far less at the same relative humidity, which is the
    # entire reason absolute humidity is a different question.
    failures += not close("cold air at the same relative humidity",
                          derive.absolute_humidity(0.0, 50.0), 2.4, 0.1)

    # 20 C, 50 %, 1013 mbar is about 7.3 g of water per kg of dry air.
    failures += not close("mixing ratio",
                          derive.mixing_ratio(20.0, 50.0, 1013.25), 7.3, 0.1)
    # A sensor reporting saturation past the ambient pressure is broken.
    # Nothing is better than a division that explodes.
    failures += not check("impossible air gives nothing",
                          derive.mixing_ratio(60.0, 100.0, 100.0), None)
    return failures


def sunshine_tests() -> int:
    """Seconds of sunshine in an interval, worked out from the radiation."""
    print("\nsunshine, from the radiation against the clear-sky maximum")
    failures = 0

    failures += not check("a bright interval counts in full",
                          derive.sunshine_seconds(700.0, 800.0, 300.0), 300.0)
    failures += not check("an overcast one counts for nothing",
                          derive.sunshine_seconds(200.0, 800.0, 300.0), 0.0)
    # The boundary somebody will sit on for an hour in March.
    failures += not check("exactly at the threshold counts",
                          derive.sunshine_seconds(600.0, 800.0, 300.0), 300.0)
    # Night is zero, definitely, rather than absent: "no sunshine" is a fact
    # worth recording and a gap is not.
    failures += not check("night is zero, not absent",
                          derive.sunshine_seconds(0.0, 0.0, 300.0), 0.0)
    # At dawn the clear-sky maximum is tiny, so a fraction of it is met by a
    # bright overcast. The floor is what stops that counting as sunshine.
    failures += not check("a bright overcast at dawn does not count",
                          derive.sunshine_seconds(15.0, 18.0, 300.0), 0.0)
    failures += not check("no radiation reading means no answer",
                          derive.sunshine_seconds(None, 800.0, 300.0), None)
    return failures


def new_reading_tests() -> int:
    """And that they reach a record, in the right unit system."""
    from weewx_evo.units import METRICWX

    print("\nand they reach a record")
    failures = 0
    station = derive.Station(latitude=48.4, longitude=11.7, altitude_m=440.0)

    metric = {"dateTime": 1756308600, "usUnits": METRICWX, "interval": 5,
              "outTemp": 20.0, "outHumidity": 50.0, "barometer": 1013.25,
              "radiation": 700.0, "maxSolarRad": 800.0}
    got = derive.Deriver(station=station).apply(dict(metric))
    failures += not close("absolute humidity", got.get("absoluteHumidity"),
                          8.65, 0.1)
    failures += not close("mixing ratio", got.get("mixingRatio"), 7.3, 0.15)
    failures += not close("vapour pressure in millibars",
                          got.get("vaporPressure"), 11.7, 0.15)
    failures += not check("sunshine", got.get("sunshine_time"), 300.0)

    # The same air in US units. A vapour pressure is a pressure, so it comes
    # back in inches of mercury the way the barometer does.
    imperial = {"dateTime": 1756308600, "usUnits": US, "interval": 5,
                "outTemp": 68.0, "outHumidity": 50.0, "barometer": 29.92}
    got = derive.Deriver(station=station).apply(dict(imperial))
    failures += not close("vapour pressure in inches of mercury",
                          got.get("vaporPressure"), 0.345, 0.01)
    # Grams per cubic metre in every system: there is no customary unit for
    # it, and WeeWX has no group for one either.
    failures += not close("absolute humidity stays metric",
                          got.get("absoluteHumidity"), 8.65, 0.15)

    # A live packet has no interval, so there is no span to attribute
    # sunshine to. Nothing, rather than a guess.
    live = {"dateTime": 1756308600, "usUnits": METRICWX, "outTemp": 20.0,
            "outHumidity": 50.0, "radiation": 700.0, "maxSolarRad": 800.0}
    got = derive.Deriver(station=station).apply(dict(live))
    failures += not check("a packet with no interval gets no sunshine",
                          "sunshine_time" in got, False)
    failures += not check("while the moisture still follows",
                          "absoluteHumidity" in got, True)

    # A station that sends its own is not overruled.
    record = dict(metric, absoluteHumidity=99.0)
    got = derive.Deriver(station=station).apply(dict(record))
    failures += not check("the station's own value stands",
                          got["absoluteHumidity"], 99.0)
    always = derive.Deriver(station=station,
                            how={"absoluteHumidity": "software"})
    got = always.apply(dict(record))
    failures += not close("and is replaced when told to",
                          got["absoluteHumidity"], 8.65, 0.1)
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
    failures += moisture_tests()
    failures += sunshine_tests()
    failures += new_reading_tests()

    print("\n" + ("FAIL" if failures else "PASS") + f" ({failures} failure(s))")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
