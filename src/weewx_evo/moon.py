"""Where the moon is, without asking anything outside the standard library.

`sun.py` works the sun out from NOAA's algorithm and lands within 37 seconds
of pyephem. The moon is the harder half: its orbit is tilted, elliptical, and
pulled about by the sun badly enough that the simple two-body answer is out
by degrees. That is why this file has two tables of sixty terms in it rather
than thirty lines of geometry -- the terms *are* the perturbations, and
leaving them out is how an almanac comes to be quietly wrong by a quarter of
an hour.

The source is Meeus, *Astronomical Algorithms*, chapters 47 (position), 49
(the phases) and 15 (rising and setting). Transcribed, in the same order, for
the same reason `units.py` and `aggregate.py` are transcriptions: a tidier
rearrangement of somebody else's numerical series is a series that is subtly
different, and finding out which term went wrong costs an afternoon.

Measured against pyephem at six places from Tromso to Ushuaia, in
`tools/mooncheck.py`.

## What is deliberately not here

The moon's rising is found by walking the day and looking for the moment its
altitude crosses the horizon, rather than by the closed-form hour angle the
sun uses. The moon moves thirteen degrees a day and its declination with it,
so the closed form needs iterating anyway -- and on the days it rises twice,
or not at all, a search has an answer where a formula has a special case.
"""

from __future__ import annotations

import math

#: Earth's equatorial radius, in kilometres. For the parallax: the moon is
#: close enough that where you stand on the planet moves it by up to a degree,
#: which is two minutes of rising time.
EARTH_RADIUS = 6378.14

#: The moon's radius as an angle, in units of its horizontal parallax. Both
#: are the same distance divided into: the disc is 0.2725 Earth radii across
#: as seen from here, and the parallax is one Earth radius.
SEMIDIAMETER = 0.2725
#: How far refraction lifts something on the horizon, in degrees. 34 minutes
#: of arc, which is slightly more than the sun or the moon is wide -- both
#: are fully visible at the moment they are geometrically still below.
REFRACTION = 0.5667

#: Meeus 47.A. Each row is the multiple of D, M, M' and F, then the
#: coefficient of the longitude term in millionths of a degree and of the
#: distance term in thousandths of a kilometre.
LONGITUDE_TERMS = (
    (0, 0, 1, 0, 6288774, -20905355),
    (2, 0, -1, 0, 1274027, -3699111),
    (2, 0, 0, 0, 658314, -2955968),
    (0, 0, 2, 0, 213618, -569925),
    (0, 1, 0, 0, -185116, 48888),
    (0, 0, 0, 2, -114332, -3149),
    (2, 0, -2, 0, 58793, 246158),
    (2, -1, -1, 0, 57066, -152138),
    (2, 0, 1, 0, 53322, -170733),
    (2, -1, 0, 0, 45758, -204586),
    (0, 1, -1, 0, -40923, -129620),
    (1, 0, 0, 0, -34720, 108743),
    (0, 1, 1, 0, -30383, 104755),
    (2, 0, 0, -2, 15327, 10321),
    (0, 0, 1, 2, -12528, 0),
    (0, 0, 1, -2, 10980, 79661),
    (4, 0, -1, 0, 10675, -34782),
    (0, 0, 3, 0, 10034, -23210),
    (4, 0, -2, 0, 8548, -21636),
    (2, 1, -1, 0, -7888, 24208),
    (2, 1, 0, 0, -6766, 30824),
    (1, 0, -1, 0, -5163, -8379),
    (1, 1, 0, 0, 4987, -16675),
    (2, -1, 1, 0, 4036, -12831),
    (2, 0, 2, 0, 3994, -10445),
    (4, 0, 0, 0, 3861, -11650),
    (2, 0, -3, 0, 3665, 14403),
    (0, 1, -2, 0, -2689, -7003),
    (2, 0, -1, 2, -2602, 0),
    (2, -1, -2, 0, 2390, 10056),
    (1, 0, 1, 0, -2348, 6322),
    (2, -2, 0, 0, 2236, -9884),
    (0, 1, 2, 0, -2120, 5751),
    (0, 2, 0, 0, -2069, 0),
    (2, -2, -1, 0, 2048, -4950),
    (2, 0, 1, -2, -1773, 4130),
    (2, 0, 0, 2, -1595, 0),
    (4, -1, -1, 0, 1215, -3958),
    (0, 0, 2, 2, -1110, 0),
    (3, 0, -1, 0, -892, 3258),
    (2, 1, 1, 0, -810, 2616),
    (4, -1, -2, 0, 759, -1897),
    (0, 2, -1, 0, -713, -2117),
    (2, 2, -1, 0, -700, 2354),
    (2, 1, -2, 0, 691, 0),
    (2, -1, 0, -2, 596, 0),
    (4, 0, 1, 0, 549, -1423),
    (0, 0, 4, 0, 537, -1117),
    (4, -1, 0, 0, 520, -1571),
    (1, 0, -2, 0, -487, -1739),
    (2, 1, 0, -2, -399, 0),
    (0, 0, 2, -2, -381, -4421),
    (1, 1, 1, 0, 351, 0),
    (3, 0, -2, 0, -340, 0),
    (4, 0, -3, 0, 330, 0),
    (2, -1, 2, 0, 327, 0),
    (0, 2, 1, 0, -323, 1165),
    (1, 1, -1, 0, 299, 0),
    (2, 0, 3, 0, 294, 0),
    (2, 0, -1, -2, 0, 8752),
)

#: Meeus 47.B. The same four multiples, then the latitude term in millionths
#: of a degree.
LATITUDE_TERMS = (
    (0, 0, 0, 1, 5128122),
    (0, 0, 1, 1, 280602),
    (0, 0, 1, -1, 277693),
    (2, 0, 0, -1, 173237),
    (2, 0, -1, 1, 55413),
    (2, 0, -1, -1, 46271),
    (2, 0, 0, 1, 32573),
    (0, 0, 2, 1, 17198),
    (2, 0, 1, -1, 9266),
    (0, 0, 2, -1, 8822),
    (2, -1, 0, -1, 8216),
    (2, 0, -2, -1, 4324),
    (2, 0, 1, 1, 4200),
    (2, 1, 0, -1, -3359),
    (2, -1, -1, 1, 2463),
    (2, -1, 0, 1, 2211),
    (2, -1, -1, -1, 2065),
    (0, 1, -1, -1, -1870),
    (4, 0, -1, -1, 1828),
    (0, 1, 0, 1, -1794),
    (0, 0, 0, 3, -1749),
    (0, 1, -1, 1, -1565),
    (1, 0, 0, 1, -1491),
    (0, 1, 1, 1, -1475),
    (0, 1, 1, -1, -1410),
    (0, 1, 0, -1, -1344),
    (1, 0, 0, -1, -1335),
    (0, 0, 3, 1, 1107),
    (4, 0, 0, -1, 1021),
    (4, 0, -1, 1, 833),
    (0, 0, 1, -3, 777),
    (4, 0, -2, 1, 671),
    (2, 0, 0, -3, 607),
    (2, 0, 2, -1, 596),
    (2, -1, 1, -1, 491),
    (2, 0, -2, 1, -451),
    (0, 0, 3, -1, 439),
    (2, 0, 2, 1, 422),
    (2, 0, -3, -1, 421),
    (2, 1, -1, 1, -366),
    (2, 1, 0, 1, -351),
    (4, 0, 0, 1, 331),
    (2, -1, 1, 1, 315),
    (2, -2, 0, -1, 302),
    (0, 0, 1, 3, -283),
    (2, 1, 1, -1, -229),
    (1, 1, 0, -1, 223),
    (1, 1, 0, 1, 223),
    (0, 1, -2, -1, -220),
    (2, 1, -1, -1, -220),
    (1, 0, 1, 1, -185),
    (2, -1, -2, -1, 181),
    (0, 1, 2, 1, -177),
    (4, 0, -2, -1, 176),
    (4, -1, -1, -1, 166),
    (1, 0, 1, -1, -164),
    (4, 0, 1, -1, 132),
    (1, 0, -1, -1, -119),
    (4, -1, 0, -1, 115),
    (2, -2, 0, 1, 107),
)


def julian_centuries(when: float) -> float:
    """Julian centuries since J2000.0, which every series below is in."""
    return ((when / 86400.0 + 2440587.5) - 2451545.0) / 36525.0


def position(when: float) -> tuple[float, float, float]:
    """The moon's apparent longitude, latitude and distance.

    Degrees, degrees, and kilometres. Meeus 47, with the full sixty terms of
    each table: good to about ten seconds of arc in longitude, which is what
    a rising time to the minute needs.
    """
    t = julian_centuries(when)

    # Meeus 47.1 to 47.5. Every one of these is a polynomial in T, and the
    # fourth-order terms matter over a century.
    mean_long = (218.3164477 + 481267.88123421 * t - 0.0015786 * t ** 2
                 + t ** 3 / 538841.0 - t ** 4 / 65194000.0)
    elongation = (297.8501921 + 445267.1114034 * t - 0.0018819 * t ** 2
                  + t ** 3 / 545868.0 - t ** 4 / 113065000.0)
    sun_anomaly = (357.5291092 + 35999.0502909 * t - 0.0001536 * t ** 2
                   + t ** 3 / 24490000.0)
    moon_anomaly = (134.9633964 + 477198.8675055 * t + 0.0087414 * t ** 2
                    + t ** 3 / 69699.0 - t ** 4 / 14712000.0)
    argument = (93.2720950 + 483202.0175233 * t - 0.0036539 * t ** 2
                - t ** 3 / 3526000.0 + t ** 4 / 863310000.0)

    # Venus, Jupiter, and the flattening of the Earth's orbit. Three small
    # corrections Meeus adds by name rather than through the tables.
    a1 = 119.75 + 131.849 * t
    a2 = 53.09 + 479264.290 * t
    a3 = 313.45 + 481266.484 * t

    # The eccentricity of the Earth's orbit, which is slowly falling. Terms
    # that depend on the sun's anomaly are scaled by it -- once for M, twice
    # for 2M -- because the sun's pull varies with the distance to it.
    e = 1.0 - 0.002516 * t - 0.0000074 * t ** 2

    d = math.radians(elongation)
    m = math.radians(sun_anomaly)
    mp = math.radians(moon_anomaly)
    f = math.radians(argument)

    sum_l = 0.0
    sum_r = 0.0
    for cd, cm, cmp, cf, coeff_l, coeff_r in LONGITUDE_TERMS:
        angle = cd * d + cm * m + cmp * mp + cf * f
        scale = e ** abs(cm)
        sum_l += coeff_l * scale * math.sin(angle)
        sum_r += coeff_r * scale * math.cos(angle)

    sum_b = 0.0
    for cd, cm, cmp, cf, coeff_b in LATITUDE_TERMS:
        angle = cd * d + cm * m + cmp * mp + cf * f
        sum_b += coeff_b * (e ** abs(cm)) * math.sin(angle)

    sum_l += (3958.0 * math.sin(math.radians(a1))
              + 1962.0 * math.sin(math.radians(mean_long) - f)
              + 318.0 * math.sin(math.radians(a2)))
    sum_b += (-2235.0 * math.sin(math.radians(mean_long))
              + 382.0 * math.sin(math.radians(a3))
              + 175.0 * math.sin(math.radians(a1) - f)
              + 175.0 * math.sin(math.radians(a1) + f)
              + 127.0 * math.sin(math.radians(mean_long) - mp)
              - 115.0 * math.sin(math.radians(mean_long) + mp))

    longitude = (mean_long + sum_l / 1000000.0) % 360.0
    latitude = sum_b / 1000000.0
    distance = 385000.56 + sum_r / 1000.0
    return longitude, latitude, distance


def equatorial(when: float) -> tuple[float, float, float]:
    """The moon's right ascension, declination and horizontal parallax.

    Degrees throughout. The parallax is what makes the moon rise earlier for
    somebody standing on the Earth than for somebody at its centre -- up to a
    degree, which is minutes of time.
    """
    longitude, latitude, distance = position(when)
    obliquity = _obliquity(julian_centuries(when))

    lam = math.radians(longitude)
    beta = math.radians(latitude)
    eps = math.radians(obliquity)

    right_ascension = math.degrees(math.atan2(
        math.sin(lam) * math.cos(eps) - math.tan(beta) * math.sin(eps),
        math.cos(lam))) % 360.0
    declination = math.degrees(math.asin(
        math.sin(beta) * math.cos(eps)
        + math.cos(beta) * math.sin(eps) * math.sin(lam)))
    parallax = math.degrees(math.asin(EARTH_RADIUS / distance))
    return right_ascension, declination, parallax


def hour_angle(when: float, longitude: float) -> float:
    """How far the moon is past the meridian, in degrees, -180 to 180.

    Zero at culmination. This is what a transit is, and it is not quite the
    moment the moon is highest: its declination moves while it crosses, so
    the peak of the altitude curve is minutes away from the meridian. Both
    are defensible and pyephem means this one.
    """
    right_ascension, _dec, _parallax = equatorial(when)
    angle = (_gmst(when) + longitude - right_ascension) % 360.0
    return angle - 360.0 if angle > 180.0 else angle


def altitude(when: float, latitude: float, longitude: float) -> float:
    """How high the moon is, in degrees, from where somebody is standing.

    Topocentric: the parallax is taken off, because at moonrise the
    difference between the centre of the Earth and the surface of it is most
    of a degree.
    """
    right_ascension, declination, parallax = equatorial(when)
    hour_angle = (_gmst(when) + longitude - right_ascension) % 360.0

    lat = math.radians(latitude)
    dec = math.radians(declination)
    ha = math.radians(hour_angle)
    geocentric = math.asin(math.sin(lat) * math.sin(dec)
                           + math.cos(lat) * math.cos(dec) * math.cos(ha))
    # Meeus 40.1, near enough at this altitude: the parallax pushes the moon
    # down by the parallax times the cosine of where it is.
    return math.degrees(geocentric - math.radians(parallax) *
                        math.cos(geocentric))


def horizon_for(when: float) -> float:
    """The altitude of the moon's *centre* when its upper limb is rising.

    Negative, and not a constant: the disc is about a quarter of a degree
    across and swells and shrinks between perigee and apogee, and refraction
    lifts it another 34 minutes of arc.

    Meeus 15.1 gives this as `0.7275 * parallax - 34'`, a positive number --
    but that is for an altitude measured from the centre of the Earth, and
    the 0.7275 is the parallax putting the moon *down* and the semidiameter
    putting its edge *up*, folded into one figure. `altitude()` here has
    already taken the parallax off, so using Meeus's number would take it off
    twice: a whole degree, which is a quarter of an hour of moonrise in
    Munich and half an hour in Tromso.
    """
    _ra, _dec, parallax = equatorial(when)
    return -(REFRACTION + SEMIDIAMETER * parallax)


def events(from_ts: float, latitude: float,
           longitude: float) -> dict[str, float | None]:
    """The next rising, setting and culmination after a moment.

    The next one, not "today's". The moon rises about fifty minutes later
    each day, so roughly once a month a calendar day contains no moonrise at
    all, and once a month no culmination -- and a page that printed N/A on
    those days would be reporting our choice of window rather than the sky.
    pyephem's `next_rising` answers this question and WeeWX asks it that way,
    so a skin brought over says what it always said.

    Two days are searched. That is one more than the longest gap between two
    risings, so each of the three is always found.
    """
    out: dict[str, float | None] = {"rise": None, "set": None,
                                    "transit": None}
    if latitude is None or longitude is None:
        return out

    # Ten minutes: the moon climbs at most about a sixth of a degree in that,
    # so no crossing hides between two samples.
    step = 600
    stop = from_ts + 2 * 86400
    previous_t = from_ts
    previous_h = altitude(from_ts, latitude, longitude) - horizon_for(from_ts)
    previous_angle = hour_angle(from_ts, longitude)

    when = from_ts + step
    while when <= stop:
        height = altitude(when, latitude, longitude) - horizon_for(when)
        if out["rise"] is None and previous_h < 0 <= height:
            out["rise"] = _cross(previous_t, when, latitude, longitude)
        if out["set"] is None and previous_h >= 0 > height:
            out["set"] = _cross(previous_t, when, latitude, longitude)

        angle = hour_angle(when, longitude)
        # Crossing the meridian is the hour angle going from behind to
        # ahead. The other sign change, from +180 to -180, is the far side
        # of the sky and is not a transit; the size test tells them apart.
        if (out["transit"] is None and previous_angle < 0 <= angle
                and angle - previous_angle < 180.0):
            out["transit"] = _meridian(previous_t, when, longitude)

        if all(v is not None for v in out.values()):
            break
        previous_t, previous_h, previous_angle = when, height, angle
        when += step
    return out


def _cross(before: float, after: float, latitude: float,
           longitude: float) -> float:
    """The moment between two samples when the moon crosses the horizon."""
    for _ in range(40):
        middle = (before + after) / 2.0
        height = (altitude(middle, latitude, longitude)
                  - horizon_for(middle))
        start = (altitude(before, latitude, longitude)
                 - horizon_for(before))
        if (height < 0) == (start < 0):
            before = middle
        else:
            after = middle
        if after - before < 1.0:
            break
    return round((before + after) / 2.0)


def _meridian(before: float, after: float, longitude: float) -> float:
    """The moment between two samples when the moon crosses the meridian."""
    for _ in range(40):
        middle = (before + after) / 2.0
        if hour_angle(middle, longitude) < 0:
            before = middle
        else:
            after = middle
        if after - before < 1.0:
            break
    return round((before + after) / 2.0)


# -- the phases ------------------------------------------------------------

def phase_event(when: float, phase: float, forwards: bool = True) -> float:
    """When the moon is next (or was last) at a given point in its cycle.

    `phase` is 0 for new, 0.25 for the first quarter, 0.5 for full, 0.75 for
    the last. Meeus 49, which is a series in the lunation number rather than
    a search: the answer is good to a few seconds and does not depend on
    where the search started.
    """
    # Meeus 49.2, inverted: which lunation the moment falls in. 2000.0 is
    # k = 0, at the new moon of 6 January 2000.
    year = 2000.0 + (when / 86400.0 + 2440587.5 - 2451545.0) / 365.25
    k = math.floor((year - 2000.0) * 12.3685) + phase

    # Step until the answer is on the side that was asked for. Two turns at
    # most: the first guess is never more than a lunation out.
    for _ in range(4):
        found = _phase_moment(k)
        if forwards and found > when:
            return found
        if not forwards and found < when:
            return found
        k += 1.0 if forwards else -1.0
    return _phase_moment(k)


def _phase_moment(k: float) -> float:
    """Meeus 49: the moment of a phase, from its lunation number."""
    t = k / 1236.85

    jde = (2451550.09766 + 29.530588861 * k
           + 0.00015437 * t ** 2 - 0.000000150 * t ** 3
           + 0.00000000073 * t ** 4)

    e = 1.0 - 0.002516 * t - 0.0000074 * t ** 2
    sun_anomaly = math.radians(
        2.5534 + 29.10535670 * k - 0.0000014 * t ** 2 - 0.00000011 * t ** 3)
    moon_anomaly = math.radians(
        201.5643 + 385.81693528 * k + 0.0107582 * t ** 2
        + 0.00001238 * t ** 3 - 0.000000058 * t ** 4)
    argument = math.radians(
        160.7108 + 390.67050284 * k - 0.0016118 * t ** 2
        - 0.00000227 * t ** 3 + 0.000000011 * t ** 4)
    node = math.radians(
        124.7746 - 1.56375588 * k + 0.0020672 * t ** 2 + 0.00000215 * t ** 3)

    quarter = round((k % 1.0) * 4.0) % 4
    if quarter == 0:
        correction = (
            -0.40720 * math.sin(moon_anomaly)
            + 0.17241 * e * math.sin(sun_anomaly)
            + 0.01608 * math.sin(2 * moon_anomaly)
            + 0.01039 * math.sin(2 * argument)
            + 0.00739 * e * math.sin(moon_anomaly - sun_anomaly)
            - 0.00514 * e * math.sin(moon_anomaly + sun_anomaly)
            + 0.00208 * e * e * math.sin(2 * sun_anomaly)
            - 0.00111 * math.sin(moon_anomaly - 2 * argument)
            - 0.00057 * math.sin(moon_anomaly + 2 * argument)
            + 0.00056 * e * math.sin(2 * moon_anomaly + sun_anomaly)
            - 0.00042 * math.sin(3 * moon_anomaly)
            + 0.00042 * e * math.sin(sun_anomaly + 2 * argument)
            + 0.00038 * e * math.sin(sun_anomaly - 2 * argument)
            - 0.00024 * e * math.sin(2 * moon_anomaly - sun_anomaly)
            - 0.00017 * math.sin(node)
            - 0.00007 * math.sin(moon_anomaly + 2 * sun_anomaly))
    elif quarter == 2:
        correction = (
            -0.40614 * math.sin(moon_anomaly)
            + 0.17302 * e * math.sin(sun_anomaly)
            + 0.01614 * math.sin(2 * moon_anomaly)
            + 0.01043 * math.sin(2 * argument)
            + 0.00734 * e * math.sin(moon_anomaly - sun_anomaly)
            - 0.00515 * e * math.sin(moon_anomaly + sun_anomaly)
            + 0.00209 * e * e * math.sin(2 * sun_anomaly)
            - 0.00111 * math.sin(moon_anomaly - 2 * argument)
            - 0.00057 * math.sin(moon_anomaly + 2 * argument)
            + 0.00056 * e * math.sin(2 * moon_anomaly + sun_anomaly)
            - 0.00042 * math.sin(3 * moon_anomaly)
            + 0.00042 * e * math.sin(sun_anomaly + 2 * argument)
            + 0.00038 * e * math.sin(sun_anomaly - 2 * argument)
            - 0.00024 * e * math.sin(2 * moon_anomaly - sun_anomaly)
            - 0.00017 * math.sin(node)
            - 0.00007 * math.sin(moon_anomaly + 2 * sun_anomaly))
    else:
        correction = (
            -0.62801 * math.sin(moon_anomaly)
            + 0.17172 * e * math.sin(sun_anomaly)
            - 0.01183 * e * math.sin(moon_anomaly + sun_anomaly)
            + 0.00862 * math.sin(2 * moon_anomaly)
            + 0.00804 * math.sin(2 * argument)
            + 0.00454 * e * math.sin(moon_anomaly - sun_anomaly)
            + 0.00204 * e * e * math.sin(2 * sun_anomaly)
            - 0.00180 * math.sin(moon_anomaly - 2 * argument)
            - 0.00070 * math.sin(moon_anomaly + 2 * argument)
            - 0.00040 * math.sin(3 * moon_anomaly)
            - 0.00034 * e * math.sin(2 * moon_anomaly - sun_anomaly)
            + 0.00032 * e * math.sin(sun_anomaly + 2 * argument)
            + 0.00032 * e * math.sin(sun_anomaly - 2 * argument)
            - 0.00028 * e * e * math.sin(moon_anomaly + 2 * sun_anomaly)
            + 0.00027 * e * math.sin(2 * moon_anomaly + sun_anomaly)
            - 0.00017 * math.sin(node))
        # The quarters get a further term whose sign says which quarter.
        w = (0.00306
             - 0.00038 * e * math.cos(sun_anomaly)
             + 0.00026 * math.cos(moon_anomaly)
             - 0.00002 * math.cos(moon_anomaly - sun_anomaly)
             + 0.00002 * math.cos(moon_anomaly + sun_anomaly)
             + 0.00002 * math.cos(2 * argument))
        correction += w if quarter == 1 else -w

    jde += correction + _additional(k, t)
    # JDE is Terrestrial Time; a unix timestamp is not. Over the years this
    # runs in, the difference is a bit over a minute.
    return (jde - 2440587.5) * 86400.0 - _delta_t(k)


def _additional(k: float, t: float) -> float:
    """Meeus 49: fourteen planetary terms, worth about a minute between them."""
    a = (
        (299.77 + 0.107408 * k - 0.009173 * t ** 2, 0.000325),
        (251.88 + 0.016321 * k, 0.000165),
        (251.83 + 26.651886 * k, 0.000164),
        (349.42 + 36.412478 * k, 0.000126),
        (84.66 + 18.206239 * k, 0.000110),
        (141.74 + 53.303771 * k, 0.000062),
        (207.14 + 2.453732 * k, 0.000060),
        (154.84 + 7.306860 * k, 0.000056),
        (34.52 + 27.261239 * k, 0.000047),
        (207.19 + 0.121824 * k, 0.000042),
        (291.34 + 1.844379 * k, 0.000040),
        (161.72 + 24.198154 * k, 0.000037),
        (239.56 + 25.513099 * k, 0.000035),
        (331.55 + 3.592518 * k, 0.000023),
    )
    return sum(size * math.sin(math.radians(angle)) for angle, size in a)


def _delta_t(k: float) -> float:
    """Terrestrial Time minus UTC at a lunation, in seconds."""
    from .sun import delta_t

    return delta_t(2000.0 + k / 12.3685)


# -- shared geometry -------------------------------------------------------

def _obliquity(t: float) -> float:
    """The tilt of the Earth's axis, in degrees, with the main nutation term."""
    mean = (23.0 + (26.0 + (21.448 - t * (46.8150 + t * (0.00059
            - t * 0.001813))) / 60.0) / 60.0)
    omega = math.radians(125.04452 - 1934.136261 * t)
    return mean + 0.00256 * math.cos(omega)


def _gmst(when: float) -> float:
    """Greenwich mean sidereal time, in degrees. Meeus 12.4."""
    jd = when / 86400.0 + 2440587.5
    t = (jd - 2451545.0) / 36525.0
    return (280.46061837 + 360.98564736629 * (jd - 2451545.0)
            + 0.000387933 * t ** 2 - t ** 3 / 38710000.0) % 360.0
