"""Cut the VSOP87 series down to what a weather page can tell apart, once.

VSOP87 is thirteen thousand periodic terms per planet. It is that long
because it is meant for an ephemeris good to a milliarcsecond over six
thousand years; a page that prints "Mars rises 04:17" needs about six orders
of magnitude less than that. So the series is cut, and the cut is measured
rather than guessed: this tool drops every term below a threshold, then
computes the geocentric position both ways over two centuries and reports
what the cut actually cost.

The output is `src/weewx_evo/vsop87.py`, which is data and nothing else.
`planets.py` is the part that was written; this part was transcribed by a
program, and it is regenerated rather than edited.

The source files are not in the repository -- four megabytes of them, and
they never change. Fetch them next to each other:

    mkdir vsop87 && cd vsop87
    curl --remote-name-all \\
      "https://cdsarc.cds.unistra.fr/ftp/VI/81/VSOP87D.{mer,ven,ear,mar,jup,sat,ura,nep}"

Then:

    python tools/vsop87trim.py vsop87/ --write

Version D is the one to use: heliocentric, spherical, and referred to the
mean ecliptic and equinox *of the date*, which is the frame everything
downstream already works in. Version A is rectangular and B is J2000; both
would need a conversion that this way does not.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

#: The eight, and the three-letter ending each one's file has. Pluto is not
#: in VSOP87 at all -- it was not a planet to Bretagnon and Francou either,
#: and `planets.py` carries Meeus's own series for it.
BODIES = (
    ("mercury", "mer"), ("venus", "ven"), ("earth", "ear"), ("mars", "mar"),
    ("jupiter", "jup"), ("saturn", "sat"), ("uranus", "ura"),
    ("neptune", "nep"),
)

#: Terms smaller than this are dropped. In radians for the longitude and
#: latitude, in astronomical units for the radius -- the same number for all
#: three because they are all of order one and the cut is about what shows
#: on a page, not about the units.
#:
#: A microradian is a fifth of an arcsecond. That sounds far finer than
#: needed, and the measurement below says otherwise: two thousand dropped
#: terms of a tenth of that size still add up to a few arcseconds once the
#: heliocentric position is turned into a geocentric one, because a planet
#: near opposition is closer than it is far, and the error is magnified by
#: exactly that ratio.
CUT = 1e-6

#: How exactly each surviving coefficient is written out. Every one is
#: shortened to the fewest digits that stay within this of the published
#: value, which is what keeps the generated file half the size it would
#: otherwise be. Two thousand terms a hundredth of an arcsecond -- the
#: rounding is four orders below the cut, so it contributes nothing.
DIGIT_TOLERANCE = 1e-11

#: Where the measurement is taken. Two centuries around now, stepped by a
#: number of days that is prime and close to no planet's period, so the
#: sample does not sit on the same part of any orbit twice.
FIRST_JD = 2415020.0
STEP_DAYS = 251.0
SAMPLES = 291


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path,
                        help="directory holding the VSOP87D.* files")
    parser.add_argument("--cut", type=float, default=CUT,
                        help=f"drop terms below this (default {CUT:g})")
    parser.add_argument("--write", action="store_true",
                        help="write src/weewx_evo/vsop87.py")
    args = parser.parse_args()

    missing = [end for _name, end in BODIES
               if not (args.source / f"VSOP87D.{end}").exists()]
    if missing:
        print(f"{args.source} has no VSOP87D.{missing[0]}. The files are "
              "not in the repository; the module docstring says where they "
              "come from.")
        return 2

    full = {name: _read(args.source / f"VSOP87D.{end}")
            for name, end in BODIES}
    trimmed = {name: [[[t for t in terms if abs(t[0]) >= args.cut]
                       for terms in variable] for variable in tables]
               for name, tables in full.items()}

    print(f"cut at {args.cut:g}")
    kept = total = 0
    for name, _end in BODIES:
        one = sum(len(terms) for v in trimmed[name] for terms in v)
        was = sum(len(terms) for v in full[name] for terms in v)
        kept += one
        total += was
        print(f"  {name:9} {one:5} terms of {was:5}")
    print(f"  {'':9} {kept:5} terms of {total:5} kept")

    print("\nwhat that costs, 1900 to 2100")
    days = [FIRST_JD + STEP_DAYS * i for i in range(SAMPLES)]
    worst_seen = 0.0
    for name, _end in BODIES:
        if name == "earth":
            continue
        worst = worst_km = 0.0
        for jd in days:
            want = _geocentric(full[name], full["earth"], jd)
            got = _geocentric(trimmed[name], trimmed["earth"], jd)
            # Along the sky, not in longitude alone: a degree of longitude
            # is a small thing near the ecliptic pole and a whole one at the
            # equator, and the number that matters is the angle between two
            # directions.
            worst = max(worst, math.hypot(
                (got[0] - want[0]) * math.cos(want[1]), got[1] - want[1]))
            worst_km = max(worst_km, abs(got[2] - want[2]))
        worst_seen = max(worst_seen, worst)
        print(f"  {name:9} {math.degrees(worst) * 3600:6.2f} arcsec, "
              f"{worst_km * 149597870.7:8.0f} km")
    print(f"  {'':9} {math.degrees(worst_seen) * 3600:6.2f} arcsec at worst, "
          f"which is {math.degrees(worst_seen):.5f} degrees")

    if not args.write:
        print("\nNothing written. Pass --write to replace "
              "src/weewx_evo/vsop87.py.")
        return 0

    out = Path(__file__).resolve().parent.parent / "src/weewx_evo/vsop87.py"
    out.write_text(_render(trimmed, args.cut, kept), encoding="utf-8")
    print(f"\nwrote {out} ({out.stat().st_size / 1024:.0f} KB)")
    return 0


# -- reading ---------------------------------------------------------------

def _read(path: Path) -> list[list[list[tuple[float, float, float]]]]:
    """One VSOP87D file as [variable][power][term], each term (A, B, C).

    The files are Fortran output: a header line for every series naming its
    variable and its power of time, then one line per term with the three
    coefficients in fixed columns at the end. Read by column rather than by
    splitting on spaces -- some of the integer multipliers run together.
    """
    tables: list[list[list[tuple[float, float, float]]]] = [[], [], []]
    variable = power = 0
    for line in path.read_text(encoding="ascii").splitlines():
        if "VSOP87" in line:
            variable = int(line.split("VARIABLE")[1].split()[0]) - 1
            power = int(line.split("*T**")[1].split()[0])
            while len(tables[variable]) <= power:
                tables[variable].append([])
            continue
        if not line.strip():
            continue
        tables[variable][power].append(
            (float(line[79:97]), float(line[97:111]), float(line[111:131])))
    return tables


# -- the geometry, only far enough to measure the cut ----------------------

def _sum(series: list[list[tuple[float, float, float]]], tau: float) -> float:
    total = 0.0
    for power in range(len(series) - 1, -1, -1):
        part = 0.0
        for a, b, c in series[power]:
            part += a * math.cos(b + c * tau)
        total = total * tau + part
    return total


def _heliocentric(tables, jd: float) -> tuple[float, float, float]:
    tau = (jd - 2451545.0) / 365250.0
    return _sum(tables[0], tau), _sum(tables[1], tau), _sum(tables[2], tau)


def _geocentric(planet, earth, jd: float) -> tuple[float, float, float]:
    """Ecliptic longitude, latitude and distance, seen from here.

    The same light-time loop `planets.py` runs, and no more: this is here to
    compare two versions of one series against each other, not to be an
    almanac.
    """
    el, eb, er = _heliocentric(earth, jd)
    ex = er * math.cos(eb) * math.cos(el)
    ey = er * math.cos(eb) * math.sin(el)
    ez = er * math.sin(eb)

    distance = 0.0
    longitude = latitude = 0.0
    for _ in range(3):
        pl, pb, pr = _heliocentric(planet, jd - distance * 0.0057755183)
        x = pr * math.cos(pb) * math.cos(pl) - ex
        y = pr * math.cos(pb) * math.sin(pl) - ey
        z = pr * math.sin(pb) - ez
        distance = math.sqrt(x * x + y * y + z * z)
        longitude = math.atan2(y, x)
        latitude = math.atan2(z, math.hypot(x, y))
    return longitude, latitude, distance


# -- writing ---------------------------------------------------------------

def _shortest(value: float, tolerance: float) -> str:
    """The fewest digits of a number that still mean the same number."""
    for digits in range(1, 18):
        text = f"{value:.{digits}g}"
        if abs(float(text) - value) <= tolerance:
            # "0" and "5" are ints to anybody reading the file, and every
            # other number in the table is a float. Keep them the same
            # shape.
            return text if ("." in text or "e" in text) else text + ".0"
    return repr(value)


def _term(a: float, b: float, c: float) -> str:
    # B and C only ever appear multiplied by A, so how exactly they need to
    # be written depends on how big A is: a term worth a millionth of a
    # radian does not need its phase to eleven places. Tau stays inside
    # plus or minus one over the years this is for, so C is worth no more
    # than C itself.
    room = DIGIT_TOLERANCE / max(abs(a), 1e-12)
    return (f"({_shortest(a, DIGIT_TOLERANCE)}, {_shortest(b, room)}, "
            f"{_shortest(c, room)})")


def _render(trimmed: dict, cut: float, kept: int) -> str:
    lines = [
        '"""The VSOP87 planetary series, cut down. Generated -- do not edit.',
        "",
        "Bretagnon and Francou, VSOP87 version D: heliocentric longitude,",
        "latitude and radius vector, referred to the mean ecliptic and",
        f"equinox of the date. Every term worth less than {cut:g} was",
        f"dropped, leaving {kept} of them.",
        "",
        "`tools/vsop87trim.py` made this file and measures what the cut",
        "cost. `planets.py` is what uses it.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
    ]
    names = []
    for name, _end in BODIES:
        constant = name.upper()
        names.append((name, constant))
        lines.append(f"#: {name.title()}. "
                     f"{sum(len(t) for v in trimmed[name] for t in v)} terms.")
        lines.append(f"{constant} = (")
        for variable, what in enumerate(("longitude", "latitude",
                                         "radius vector")):
            lines.append(f"    (  # {what}")
            for power, terms in enumerate(trimmed[name][variable]):
                lines.append(f"        (  # tau^{power}")
                for a, b, c in terms:
                    lines.append(f"            {_term(a, b, c)},")
                lines.append("        ),")
            lines.append("    ),")
        lines.append(")")
        lines.append("")

    lines.append("#: Every one of them, by the name a skin asks for.")
    lines.append("SERIES = {")
    for name, constant in names:
        lines.append(f'    "{name}": {constant},')
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
