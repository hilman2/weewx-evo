"""Check every unit conversion against WeeWX's own.

`weewx_evo.units` is a transcription: the same expressions, constant by
constant. A transcription is only worth anything if something checks it, and
the failure mode it guards against is quiet -- a factor off in the fourth
decimal produces a chart that looks right and disagrees with WeeWX's chart of
the same day.

So: every conversion pair, at several magnitudes and at zero, compared exactly.
Then every reading's group, and every label.

    wsl -d Ubuntu -- bash -lc 'source ~/venvs/weewx/bin/activate &&
        cd /mnt/d/Git/weewx-evo && PYTHONPATH=/mnt/d/Git/weewx/src:src
        python3 tools/unitcheck.py'
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import weewx_evo.units as ours

#: Where a conversion could go wrong differently: zero (an offset shows up
#: here and nowhere else), small, ordinary, large, negative.
SAMPLES = (0.0, 1.0, -1.0, 7.5, 100.0, -40.0, 1013.25, 0.001, 98765.4321)

#: Units this project has and WeeWX does not, with the reason. Listed rather
#: than reported as failures, because a check that calls a deliberate
#: addition a failure is one people learn to skip -- and because this list is
#: then the documentation of exactly how far the transcription goes beyond
#: its original.
#:
#: Every one of these exists because `derive.py` can now work out a reading
#: WeeWX leaves to an extension. `weewx-GTS` adds the same units at run time;
#: the names are its, so a skin written against it works here untouched.
OURS = {
    "gram_per_meter_cubed": "absolute humidity, which weewx-GTS adds",
    "milligram_per_meter_cubed": "the same, at a scale a sensor reports in",
    "gram_per_kilogram": "the mixing ratio, which weewx-GTS adds",
    "astronomical_unit": "how far away a planet is; planets.py needs it",
}

#: Pairs where WeeWX and this differ, with why. Named one by one, because a
#: category would let the next one in without anybody looking at it.
KNOWN = {
    # Both spellings, because the pair is missing under one name and extra
    # under the other, and both are the same one difference.
    ("degree_K", "degreeF"):
        "WeeWX writes the target as 'degreeF' here and 'degree_F' everywhere "
        "else, so its own convert() raises on Kelvin to Fahrenheit. Ours "
        "spells it the way the rest of the table does and works. Their typo, "
        "not our deviation.",
    ("degree_K", "degree_F"): "the same entry, spelled as the rest of the "
                              "table spells it.",
}

#: Readings the same applies to.
OUR_READINGS = {
    "absoluteHumidity": "derive.py works it out",
    "outHumAbs": "what weewx-GTS calls the same thing",
    "mixingRatio": "derive.py works it out",
    "vaporPressure": "derive.py works it out",
    "satVaporPressure": "derive.py works it out",
    "sunshine_time": "derive.py works it out; sunduration's name",
    "cloudCover": "the forecast publishes it; WeeWX has only 'cloudcover'",
    "rainProbability": "only a forecast has one",
}


def main() -> int:
    import weewx.defaults
    import weewx.units as theirs

    failures = 0

    print("conversions")
    pairs = missing = extra = 0
    for from_unit, targets in theirs.conversionDict.items():
        for to_unit in targets:
            pairs += 1
            if to_unit not in ours.CONVERT.get(from_unit, {}):
                if (from_unit, to_unit) in KNOWN:
                    continue
                print(f"  MISSING {from_unit} -> {to_unit}")
                missing += 1
                failures += 1
                continue
            for x in SAMPLES:
                want = theirs.conversionDict[from_unit][to_unit](x)
                got = ours.CONVERT[from_unit][to_unit](x)
                if got != want:
                    print(f"  FAIL {from_unit} -> {to_unit} at {x}:"
                          f" evo={got!r} weewx={want!r}")
                    failures += 1
                    break
    for from_unit, targets in ours.CONVERT.items():
        for to_unit in targets:
            if to_unit in theirs.conversionDict.get(from_unit, {}):
                continue
            if from_unit in OURS or to_unit in OURS:
                # Ours on purpose. Named rather than counted as a failure.
                extra += 1
                continue
            if (from_unit, to_unit) in KNOWN:
                extra += 1
                continue
            print(f"  EXTRA {from_unit} -> {to_unit} (WeeWX has no such)")
            extra += 1
            failures += 1
    print(f"  {pairs} pair(s) x {len(SAMPLES)} value(s), exact"
          f"{f', {missing} missing' if missing else ''}"
          f"{f', {extra} extra' if extra else ''}")

    print("\nround trips drift exactly as WeeWX's do")
    # WeeWX's table is not self-inverse: mph -> kph uses 1.609344 while
    # kph -> mph uses 1000/1609.34, so a value sent there and back is a couple
    # of parts in a million out. That is inherited on purpose -- the check is
    # that our drift is *their* drift, not that there is none.
    drifting = mismatched = 0
    for from_unit, targets in ours.CONVERT.items():
        for to_unit in targets:
            if from_unit not in ours.CONVERT.get(to_unit, {}):
                continue
            # Asked of WeeWX's own table rather than of a list of names.
            # A pair we have and WeeWX does not has nothing to drift the same
            # way as -- and looking it up there anyway is a KeyError, which is
            # how this read as a broken unit table rather than a missing one.
            if (to_unit not in theirs.conversionDict.get(from_unit, {})
                    or from_unit not in theirs.conversionDict.get(to_unit, {})):
                continue
            for x in (1.0, 100.0, -40.0):
                mine = ours.CONVERT[to_unit][from_unit](
                    ours.CONVERT[from_unit][to_unit](x))
                yours = theirs.conversionDict[to_unit][from_unit](
                    theirs.conversionDict[from_unit][to_unit](x))
                if mine != yours:
                    print(f"  FAIL {from_unit} -> {to_unit} -> {from_unit}"
                          f" at {x}: evo={mine!r} weewx={yours!r}")
                    mismatched += 1
                    failures += 1
                    break
                if mine != x:
                    drifting += 1
                    break
    print(f"  {drifting} pair(s) do not come back exactly, every one of them"
          f" the same way WeeWX does; {mismatched} differ")

    if KNOWN:
        print()
        print("known differences, one line each")
        for (from_unit, to_unit), why in sorted(KNOWN.items()):
            print(f"  {from_unit} -> {to_unit}: {why}")

    print("\nwhich group each reading is in")
    wrong = 0
    for obs_type, group in theirs.obs_group_dict.items():
        if ours.GROUPS.get(obs_type) != group:
            print(f"  FAIL {obs_type}: evo={ours.GROUPS.get(obs_type)!r}"
                  f" weewx={group!r}")
            wrong += 1
            failures += 1
    for obs_type in ours.GROUPS:
        if obs_type in theirs.obs_group_dict or obs_type in OUR_READINGS:
            continue
        print(f"  EXTRA {obs_type}")
        wrong += 1
        failures += 1
    print(f"  {len(ours.GROUPS)} reading(s), {wrong} wrong")
    print(f"\n{len(OURS)} unit(s) and {len(OUR_READINGS)} reading(s) are "
          f"ours rather than WeeWX's:")
    for name, why in sorted(OURS.items()):
        print(f"  {name:<28} {why}")
    for name, why in sorted(OUR_READINGS.items()):
        print(f"  {name:<28} {why}")

    print("\nwhich unit each group uses")
    wrong = 0
    for system, table in ((ours.US, theirs.USUnits),
                          (ours.METRIC, theirs.MetricUnits),
                          (ours.METRICWX, theirs.MetricWXUnits)):
        for group, unit in table.items():
            if ours.SYSTEMS[system].get(group) != unit:
                print(f"  FAIL {ours.name(system)}/{group}:"
                      f" evo={ours.SYSTEMS[system].get(group)!r} weewx={unit!r}")
                wrong += 1
                failures += 1
    print(f"  3 system(s) x {len(theirs.USUnits)} group(s), {wrong} wrong")

    print("\naggregates that change the group")
    wrong = 0
    for aggregate, group in theirs.agg_group.items():
        if ours.AGGREGATE_GROUPS.get(aggregate) != group:
            print(f"  FAIL {aggregate}: evo={ours.AGGREGATE_GROUPS.get(aggregate)!r}"
                  f" weewx={group!r}")
            wrong += 1
            failures += 1
    print(f"  {len(theirs.agg_group)} aggregate(s), {wrong} wrong")

    print("\nlabels and formats")
    wrong = 0
    skin = weewx.defaults.defaults["Units"]
    for unit, text in skin["Labels"].items():
        mine = ours.LABELS.get(unit)
        want = list(text) if not isinstance(text, str) else text
        if mine != want:
            print(f"  FAIL label {unit}: evo={mine!r} weewx={want!r}")
            wrong += 1
            failures += 1
    for unit, fmt in skin["StringFormats"].items():
        if ours.FORMATS.get(unit) != fmt:
            print(f"  FAIL format {unit}: evo={ours.FORMATS.get(unit)!r}"
                  f" weewx={fmt!r}")
            wrong += 1
            failures += 1
    print(f"  {len(skin['Labels'])} label(s), {len(skin['StringFormats'])}"
          f" format(s), {wrong} wrong")

    print("\nreading a US database and showing it in metric")
    # The case this whole file exists for: a console that reports Fahrenheit
    # and a site published in Celsius.
    target = ours.Target(ours.METRICWX)
    checks = [
        ("outTemp", 77.9, "degree_C"), ("barometer", 30.0, "mbar"),
        ("windSpeed", 10.0, "meter_per_second"), ("rain", 0.05, "mm"),
        ("altimeter", 29.92, "mbar"), ("radiation", 500.0,
                                       "watt_per_meter_squared"),
    ]
    for obs_type, value, want_unit in checks:
        values, unit, group = target.convert([value], obs_type, ours.US)
        stored, _ = ours.unit_of(obs_type, ours.US)
        expect = theirs.convert(
            theirs.ValueTuple(value, stored, group), want_unit)[0]
        ok = unit == want_unit and values[0] == expect
        failures += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {obs_type}: {value} {stored}"
              f" -> {values[0]!r} {unit}"
              + ("" if ok else f"   weewx says {expect!r} {want_unit}"))

    print("\n" + ("FAIL" if failures else "PASS") + f" ({failures} failure(s))")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
