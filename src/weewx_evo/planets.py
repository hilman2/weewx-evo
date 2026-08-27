"""Where the planets are, without asking anything outside the standard library.

`sun.py` and `moon.py` answer the two things every weather page shows. This
file answers the rest of `$almanac`: Mercury through Neptune, and Pluto,
which stopped being a planet in 2006 and did not stop being in WeeWX.

The method is Meeus, chapters 32 (the heliocentric position), 33 (turning it
into what somebody here sees) and 22 to 25 (nutation and aberration, the two
corrections between a geometric position and an apparent one). The series
themselves are VSOP87, in `vsop87.py`, cut down to two thousand terms of
thirty thousand by `tools/vsop87trim.py` -- which measures what the cut cost
rather than assuming: six arcseconds at worst over two centuries, and the
worst is Venus at its closest, where the Earth is near enough that a small
error in where Venus is becomes a larger one in which direction it lies.

Pluto is not in VSOP87 -- it was not a planet to Bretagnon and Francou
either. Meeus 37 has its own series for it, forty-three terms in the mean
longitudes of Jupiter, Saturn and Pluto, and it is good from 1885 to 2099.
Outside those years it is not wrong so much as meaningless, and there is no
guard against that here for the same reason there is none on the year 3000:
a weather station is asked about today.

Measured against pyephem at six places from Tromso to Ushuaia, over forty
years and the four turning points of each: three arcseconds of position for
the eight, and rising, setting and culmination within **two seconds**.
Pluto is thirteen arcseconds, which is two theories of a faint thing
disagreeing rather than either being wrong -- its series is held against
Meeus's own worked example instead, where it agrees to the last digit the
book prints. `tools/planetcheck.py` is where all of those numbers come
from.

## Three things that are decisions

**Terrestrial Time, not the clock on the wall.** Every series here is in TT,
which is a bit over a minute ahead of UTC and drifting. A minute is nothing
for Neptune and six arcseconds for Mercury, which moves two degrees a day --
so `delta_t` from `sun.py` is applied before the series is touched.

**The apparent position, not the astrometric one.** Aberration is twenty
arcseconds and nutation seventeen; both are four times the error of the cut
series, so leaving them out would be the largest mistake in the file. What
*is* left out is the FK5 correction of Meeus 32.3, which is under a tenth of
an arcsecond -- two orders below the cut, and saying so is worth more than
four lines that cannot be measured.

**Rising is searched, not solved.** The same shape as `moon.py`: walk the
sky and find where the altitude crosses. But a planet barely moves against
the stars in two days, so the expensive part -- two thousand cosines, three
times over for the light-time -- is done at a handful of moments and
interpolated between. Doing it at every step of the search instead costs
half a second per planet, and half a second in a feed is half a second the
archiver is not archiving.
"""

from __future__ import annotations

import math

from .moon import _gmst
from .sun import delta_t
from .vsop87 import SERIES

#: What a skin can ask for. Earth is in `vsop87.SERIES` because everything
#: else is measured from it, and it is not in here because nobody standing
#: on it wants to know when it rises.
PLANETS = ("mercury", "venus", "mars", "jupiter", "saturn", "uranus",
           "neptune", "pluto")

#: The astronomical unit in kilometres, for the parallax.
AU = 149597870.7
#: Earth's equatorial radius, in kilometres. Same figure as `moon.py`.
EARTH_RADIUS = 6378.14
#: How far refraction lifts something on the horizon, in degrees.
REFRACTION = 0.5667
#: Days light takes to cross one astronomical unit. Meeus 33: a planet is
#: seen where it was, not where it is, and for Neptune that is four hours.
LIGHT_TIME = 0.0057755183

#: Meeus 37.A. Each row is the multiple of the mean longitudes of Jupiter,
#: Saturn and Pluto, then the sine and cosine coefficients of the longitude,
#: the latitude and the radius vector. Longitude and latitude are in
#: millionths of a degree, the radius in ten-millionths of an astronomical
#: unit.
PLUTO_TERMS = (
    (0, 0, 1, -19799805, 19850055, -5452852, -14974862, 66865439, 68951812),
    (0, 0, 2, 897144, -4954829, 3527812, 1672790, -11827535, -332538),
    (0, 0, 3, 611149, 1211027, -1050748, 327647, 1593179, -1438890),
    (0, 0, 4, -341243, -189585, 178690, -292153, -18444, 483220),
    (0, 0, 5, 129287, -34992, 18650, 100340, -65977, -85431),
    (0, 0, 6, -38164, 30893, -30697, -25823, 31174, -6032),
    (0, 1, -1, 20442, -9987, 4878, 11248, -5794, 22161),
    (0, 1, 0, -4063, -5071, 226, -64, 4601, 4032),
    (0, 1, 1, -6016, -3336, 2030, -836, -1729, 234),
    (0, 1, 2, -3956, 3039, 69, -604, -415, 702),
    (0, 1, 3, -667, 3572, -247, -567, 239, 723),
    (0, 2, -2, 1276, 501, -57, 1, 67, -67),
    (0, 2, -1, 1152, -917, -122, 175, 1034, -451),
    (0, 2, 0, 630, -1277, -49, -164, -129, 504),
    (1, -1, 0, 2571, -459, -197, 199, 480, -231),
    (1, -1, 1, 899, -1449, -25, 217, 2, -441),
    (1, 0, -3, -1016, 1043, 589, -248, -3359, 265),
    (1, 0, -2, -2343, -1012, -269, 711, 7856, -7832),
    (1, 0, -1, 7042, 788, 185, 193, 36, 45763),
    (1, 0, 0, 1199, -338, 315, 807, 8663, 8547),
    (1, 0, 1, 418, -67, -130, -43, -809, -769),
    (1, 0, 2, 120, -274, 5, 3, 263, -144),
    (1, 0, 3, -60, -159, 2, 17, -126, 32),
    (1, 0, 4, -82, -29, 2, 5, -35, -16),
    (1, 1, -3, -36, -29, 2, 3, -19, -4),
    (1, 1, -2, -40, 7, 3, 1, -15, 8),
    (1, 1, -1, -14, 22, 2, -1, -4, 12),
    (1, 1, 0, 4, 13, 1, -1, 5, 6),
    (1, 1, 1, 5, 2, 0, -1, 3, 1),
    (1, 1, 3, -1, 0, 0, 0, 6, -2),
    (2, 0, -6, 2, 0, 0, -2, 2, 2),
    (2, 0, -5, -4, 5, 2, 2, -2, -2),
    (2, 0, -4, 4, -7, -7, 0, 14, 13),
    (2, 0, -3, 14, 24, 10, -8, -63, 13),
    (2, 0, -2, -49, -34, -3, 20, 136, -236),
    (2, 0, -1, 163, -48, 6, 5, 273, 1065),
    (2, 0, 0, 9, -24, 14, 17, 251, 149),
    (2, 0, 1, -4, 1, -2, 0, -25, -9),
    (2, 0, 2, -3, 1, 0, 0, 9, -2),
    (2, 0, 3, 1, 3, 0, 0, -8, 7),
    (3, 0, -2, -3, -1, 0, 1, 2, -10),
    (3, 0, -1, 5, -3, 0, 0, 19, 35),
    (3, 0, 0, 0, 0, 1, 0, 10, 3),
)


def heliocentric(when: float, body: str) -> tuple[float, float, float]:
    """Where a planet is as seen from the sun.

    Longitude and latitude in degrees, distance in astronomical units, in
    the mean ecliptic and equinox of the date -- which is what VSOP87
    version D is in, and why that is the version used.
    """
    longitude, latitude, radius = _heliocentric(_julian(when), body)
    return math.degrees(longitude) % 360.0, math.degrees(latitude), radius


def position(when: float, body: str) -> tuple[float, float, float]:
    """A planet's apparent longitude, latitude and distance.

    Degrees, degrees, and astronomical units, seen from the centre of the
    Earth. Apparent: corrected for the time its light took to arrive, for
    the Earth's own motion across that light, and for the wobble of the
    Earth's axis.
    """
    return _apparent(_julian(when), body)


def equatorial(when: float, body: str) -> tuple[float, float, float]:
    """A planet's apparent right ascension, declination and distance.

    Degrees, degrees, astronomical units. The obliquity is the true one --
    the mean tilt plus the nutation in it -- because the longitude it is
    applied to already carries the nutation in longitude, and using one
    without the other puts the answer half an arcsecond out in a way that
    looks like a mistyped constant.
    """
    jd = _julian(when)
    longitude, latitude, distance = _apparent(jd, body)
    return _to_equatorial(longitude, latitude, _centuries(jd)) + (distance,)


def hour_angle(when: float, longitude: float, body: str) -> float:
    """How far past the meridian a planet is, in degrees, -180 to 180.

    Zero at culmination, which is the meridian crossing rather than the top
    of the altitude curve. The two are seconds apart for a planet and
    pyephem means this one.
    """
    right_ascension, _dec, _distance = equatorial(when, body)
    angle = (_gmst(when) + longitude - right_ascension) % 360.0
    return angle - 360.0 if angle > 180.0 else angle


def altitude(when: float, latitude: float, longitude: float,
             body: str) -> float:
    """How high a planet is, in degrees, from where somebody is standing."""
    right_ascension, declination, distance = equatorial(when, body)
    return _horizontal(right_ascension, declination, distance, when,
                       latitude, longitude)[0]


def horizontal(when: float, latitude: float, longitude: float,
               body: str) -> tuple[float, float]:
    """A planet's altitude and azimuth in degrees, from a place.

    Azimuth from north through east, the way a compass rose reads.
    """
    right_ascension, declination, distance = equatorial(when, body)
    return _horizontal(right_ascension, declination, distance, when,
                       latitude, longitude)


def horizon_for(_body: str) -> float:
    """The altitude of a planet's centre when it is taken to be rising.

    Just the refraction. The moon needs a figure that changes because its
    disc is half a degree across and swells; Venus at its closest is a third
    of an arcminute, which is two seconds of rising time, and no planet ever
    gets bigger than that.
    """
    return -REFRACTION


def events(from_ts: float, latitude: float, longitude: float,
           body: str) -> dict[str, float | None]:
    """The next rising, setting and culmination of a planet after a moment.

    The next one, not "today's" -- the same question `moon.events` answers
    and the one pyephem's `next_rising` answers, so a skin brought over from
    WeeWX says what it always said. None where there is none: a planet far
    enough north stays up for weeks at Tromso, and a page that invented a
    time for that would be lying rather than blank.
    """
    out: dict[str, float | None] = {"rise": None, "set": None,
                                    "transit": None}
    if latitude is None or longitude is None:
        return out

    # Two days. A planet drifts about four minutes a day against the stars,
    # so unlike the moon it very nearly always has a rising tomorrow if it
    # had one today; the second day is for the handful that do not.
    stop = from_ts + 2 * 86400
    sky = _Track(body, from_ts, stop)
    edge = horizon_for(body)

    step = 600
    previous_t = from_ts
    previous_h = sky.altitude(from_ts, latitude, longitude) - edge
    previous_angle = sky.hour_angle(from_ts, longitude)

    when = from_ts + step
    while when <= stop:
        height = sky.altitude(when, latitude, longitude) - edge
        if out["rise"] is None and previous_h < 0 <= height:
            out["rise"] = _cross(sky, previous_t, when, latitude, longitude,
                                 edge)
        if out["set"] is None and previous_h >= 0 > height:
            out["set"] = _cross(sky, previous_t, when, latitude, longitude,
                                edge)

        angle = sky.hour_angle(when, longitude)
        # Crossing the meridian is the hour angle going from behind to
        # ahead. The other sign change, from +180 to -180, is the far side
        # of the sky and is not a transit; the size test tells them apart.
        if (out["transit"] is None and previous_angle < 0 <= angle
                and angle - previous_angle < 180.0):
            out["transit"] = _meridian(sky, previous_t, when, longitude)

        if all(v is not None for v in out.values()):
            break
        previous_t, previous_h, previous_angle = when, height, angle
        when += step
    return out


# -- the search ------------------------------------------------------------

def _cross(sky: _Track, before: float, after: float, latitude: float,
           longitude: float, edge: float) -> float:
    """The moment between two samples when a planet crosses the horizon."""
    start = sky.altitude(before, latitude, longitude) - edge
    for _ in range(40):
        middle = (before + after) / 2.0
        height = sky.altitude(middle, latitude, longitude) - edge
        if (height < 0) == (start < 0):
            before = middle
        else:
            after = middle
        if after - before < 1.0:
            break
    return round((before + after) / 2.0)


def _meridian(sky: _Track, before: float, after: float,
              longitude: float) -> float:
    """The moment between two samples when a planet crosses the meridian."""
    for _ in range(40):
        middle = (before + after) / 2.0
        if sky.hour_angle(middle, longitude) < 0:
            before = middle
        else:
            after = middle
        if after - before < 1.0:
            break
    return round((before + after) / 2.0)


class _Track:
    """Where a planet is over a span, from a few full positions.

    The search above asks for the altitude a few hundred times. Working out
    the full apparent position each time means the whole VSOP87 series four
    times over -- once for the Earth and three for the light-time loop --
    and that is half a second per planet.

    So the position is worked out every four hours and interpolated
    between. A planet moves at most two degrees a day against the stars, so
    three points fit a parabola through four hours to well under an
    arcsecond; the fast part of the motion, fifteen degrees an hour, is the
    Earth turning, and that is in `_gmst` where it is exact at every moment.

    Right ascension is unwrapped as it is collected. Interpolating between
    359 and 1 the short way is the difference between a planet in Pisces and
    one nowhere at all.
    """

    #: Four hours. Halving it moves nothing measurable and doubles the cost.
    STEP = 14400.0

    __slots__ = ("body", "samples", "start")

    def __init__(self, body: str, start: float, stop: float) -> None:
        self.body = body
        self.start = start
        count = math.ceil((stop - start) / self.STEP) + 2
        self.samples: list[tuple[float, float, float]] = []
        previous = None
        for i in range(count):
            right_ascension, declination, distance = equatorial(
                start + i * self.STEP, body)
            if previous is not None:
                right_ascension += 360.0 * round(
                    (previous - right_ascension) / 360.0)
            previous = right_ascension
            self.samples.append((right_ascension, declination, distance))

    def _at(self, when: float) -> tuple[float, float, float]:
        """Right ascension, declination and distance at a moment."""
        place = (when - self.start) / self.STEP
        # The middle of three points, held one in from each end so the
        # parabola is always interpolating rather than running off.
        middle = min(max(round(place), 1), len(self.samples) - 2)
        n = place - middle
        one, two, three = self.samples[middle - 1:middle + 2]
        return (_between(one[0], two[0], three[0], n),
                _between(one[1], two[1], three[1], n),
                _between(one[2], two[2], three[2], n))

    def altitude(self, when: float, latitude: float,
                 longitude: float) -> float:
        right_ascension, declination, distance = self._at(when)
        return _horizontal(right_ascension % 360.0, declination, distance,
                           when, latitude, longitude)[0]

    def hour_angle(self, when: float, longitude: float) -> float:
        right_ascension = self._at(when)[0] % 360.0
        angle = (_gmst(when) + longitude - right_ascension) % 360.0
        return angle - 360.0 if angle > 180.0 else angle


def _between(before: float, middle: float, after: float, n: float) -> float:
    """Meeus 3.3: a parabola through three evenly spaced values.

    `n` is where the answer sits between them, in units of one spacing, and
    zero is the middle one.
    """
    return middle + n * ((after - before) / 2.0
                         + n * (before + after - 2.0 * middle) / 2.0)


# -- the position ----------------------------------------------------------

def _julian(when: float) -> float:
    """The Julian day of a unix timestamp, in Terrestrial Time.

    Every series in this file is in TT and a timestamp is not. The gap is a
    bit over a minute now, which is nothing for Neptune and six arcseconds
    for Mercury.
    """
    jd = when / 86400.0 + 2440587.5
    year = 2000.0 + (jd - 2451545.0) / 365.25
    return jd + delta_t(year) / 86400.0


def _centuries(jd: float) -> float:
    return (jd - 2451545.0) / 36525.0


def _series(powers, tau: float) -> float:
    """One VSOP87 variable: a polynomial in tau whose coefficients are sums.

    Horner's way round, which is one multiplication per power rather than
    one exponentiation, and does not lose digits at the far end.
    """
    total = 0.0
    for power in range(len(powers) - 1, -1, -1):
        part = 0.0
        for a, b, c in powers[power]:
            part += a * math.cos(b + c * tau)
        total = total * tau + part
    return total


def _heliocentric(jd: float, body: str) -> tuple[float, float, float]:
    """Heliocentric longitude, latitude (radians) and radius (AU)."""
    if body == "pluto":
        return _pluto(jd)
    try:
        tables = SERIES[body]
    except KeyError:
        # Named rather than shrugged at, because the two names most likely
        # to arrive here are the two that belong somewhere else.
        raise ValueError(
            f"{body!r} is not one of the planets. The sun is in sun.py and "
            f"the moon is in moon.py; here it is {', '.join(PLANETS)}."
        ) from None
    tau = (jd - 2451545.0) / 365250.0
    return (_series(tables[0], tau) % (2.0 * math.pi),
            _series(tables[1], tau), _series(tables[2], tau))


def _pluto(jd: float) -> tuple[float, float, float]:
    """Meeus 37, moved into the frame everything else here works in.

    Meeus gives Pluto in the ecliptic of J2000 and VSOP87 version D gives
    the planets in the ecliptic of the date. Precessing one to meet the
    other (Meeus 21.7) is a quarter of a degree in 2026 -- a constant
    offset, which is exactly what a mistyped coefficient looks like.
    """
    longitude, latitude, radius = _pluto_j2000(jd)
    longitude, latitude = _precess(longitude, latitude, _centuries(jd))
    return longitude % (2.0 * math.pi), latitude, radius


def _pluto_j2000(jd: float) -> tuple[float, float, float]:
    """Pluto from the mean longitudes of Jupiter, Saturn and itself.

    Radians and astronomical units, in the ecliptic of J2000, which is the
    frame Meeus 37 is written in. Kept separate from the precession above so
    that `tools/planetcheck.py` can hold it against the worked example in
    the book -- three numbers that check all three hundred and eighty-seven
    coefficients, and the only test here that does not go through pyephem.

    Good from 1885 to 2099, and only there: the series is a fit to a century
    of observations rather than a theory, and outside its window it does not
    degrade so much as stop meaning anything. There is no guard against that
    for the same reason there is none on the year 3000 -- a weather station
    is asked about today.
    """
    t = _centuries(jd)
    jupiter = math.radians(34.35 + 3034.9057 * t)
    saturn = math.radians(50.08 + 1222.1138 * t)
    pluto = math.radians(238.96 + 144.96 * t)

    sum_l = sum_b = sum_r = 0.0
    for (cj, cs, cp, l_sin, l_cos, b_sin, b_cos, r_sin, r_cos) in PLUTO_TERMS:
        angle = cj * jupiter + cs * saturn + cp * pluto
        sine, cosine = math.sin(angle), math.cos(angle)
        sum_l += l_sin * sine + l_cos * cosine
        sum_b += b_sin * sine + b_cos * cosine
        sum_r += r_sin * sine + r_cos * cosine

    return (math.radians(238.958116 + 144.96 * t + sum_l / 1000000.0),
            math.radians(-3.908239 + sum_b / 1000000.0),
            40.7241346 + sum_r / 10000000.0)


def _precess(longitude: float, latitude: float,
             t: float) -> tuple[float, float]:
    """Ecliptic coordinates from J2000 to the equinox of the date.

    Meeus 21.5 and 21.7, with the starting epoch fixed at J2000 -- which
    drops every term in T0 and leaves three short polynomials.
    """
    eta = math.radians((47.0029 * t - 0.03302 * t ** 2
                        + 0.000060 * t ** 3) / 3600.0)
    node = math.radians(174.876384 - (869.8089 * t
                                      - 0.03536 * t ** 2) / 3600.0)
    drift = math.radians((5029.0966 * t + 1.11113 * t ** 2
                          - 0.000006 * t ** 3) / 3600.0)

    turn = node - longitude
    a = (math.cos(eta) * math.cos(latitude) * math.sin(turn)
         - math.sin(eta) * math.sin(latitude))
    b = math.cos(latitude) * math.cos(turn)
    c = (math.cos(eta) * math.sin(latitude)
         + math.sin(eta) * math.cos(latitude) * math.sin(turn))
    return drift + node - math.atan2(a, b), math.asin(c)


def _apparent(jd: float, body: str) -> tuple[float, float, float]:
    """The apparent geocentric ecliptic position. Degrees, degrees, AU.

    Meeus 33. The Earth is taken where it is now and the planet where it
    was when the light left it, which is the whole of the planetary
    aberration; what the Earth's own motion does to the direction the light
    arrives from is the other kind, and that is added below.

    The distance returned is the geometric one -- how far away the planet is
    now, not how far the light travelled to say where it was. Those differ
    by fourteen thousand kilometres for Mars and a hundred thousand for
    Pluto, and pyephem's `earth_distance` means the first, so a skin that
    has printed that number for years keeps printing it. It costs nothing:
    the first turn of the loop below has no light-time in it yet, so it is
    already the geometric answer.
    """
    if body == "earth":
        # The series is here because everything else is measured against
        # it, so this asks where the Earth is from the Earth. It comes out
        # as a distance of zero, which divides by zero two functions later
        # and looks like a bug in the parallax.
        raise ValueError("the Earth has no geocentric position")

    earth_l, earth_b, earth_r = _heliocentric(jd, "earth")
    earth_x = earth_r * math.cos(earth_b) * math.cos(earth_l)
    earth_y = earth_r * math.cos(earth_b) * math.sin(earth_l)
    earth_z = earth_r * math.sin(earth_b)

    distance = geometric = 0.0
    longitude = latitude = 0.0
    # Three turns. The first has no light-time at all, the second is within
    # a few metres of the answer, and the third is there.
    for turn in range(3):
        planet_l, planet_b, planet_r = _heliocentric(
            jd - distance * LIGHT_TIME, body)
        x = planet_r * math.cos(planet_b) * math.cos(planet_l) - earth_x
        y = planet_r * math.cos(planet_b) * math.sin(planet_l) - earth_y
        z = planet_r * math.sin(planet_b) - earth_z
        distance = math.sqrt(x * x + y * y + z * z)
        longitude = math.atan2(y, x)
        latitude = math.atan2(z, math.hypot(x, y))
        if turn == 0:
            geometric = distance

    t = _centuries(jd)
    # The sun's geometric longitude is the Earth's, turned around.
    sun = earth_l + math.pi
    aberration_l, aberration_b = _aberration(longitude, latitude, sun, t)
    longitude += aberration_l + math.radians(_nutation(t)[0])
    latitude += aberration_b
    return math.degrees(longitude) % 360.0, math.degrees(latitude), geometric


def _aberration(longitude: float, latitude: float, sun: float,
                t: float) -> tuple[float, float]:
    """What the Earth's own motion does to a direction. Meeus 23.2.

    Twenty arcseconds, which is three times the whole error of the cut
    series -- so this is not a refinement, it is the difference between an
    answer and a wrong one. Radians in, radians out.
    """
    kappa = math.radians(20.49552 / 3600.0)
    eccentricity = (0.016708634 - 0.000042037 * t
                    - 0.0000001267 * t ** 2)
    perihelion = math.radians(102.93735 + 1.71946 * t + 0.00046 * t ** 2)
    return (
        (-kappa * math.cos(sun - longitude)
         + eccentricity * kappa * math.cos(perihelion - longitude))
        / math.cos(latitude),
        -kappa * math.sin(latitude) * (math.sin(sun - longitude)
                                       - eccentricity
                                       * math.sin(perihelion - longitude)),
    )


def _nutation(t: float) -> tuple[float, float]:
    """The wobble of the Earth's axis, in degrees. Meeus 22, the short way.

    Four terms of each rather than sixty-three, which is half an arcsecond
    -- a tenth of what the cut series is already worth. The longitude term
    reaches seventeen arcseconds, so it cannot be left out; the rest of the
    table can.
    """
    node = math.radians(125.04452 - 1934.136261 * t)
    sun = math.radians(280.4665 + 36000.7698 * t)
    moon = math.radians(218.3165 + 481267.8813 * t)
    in_longitude = (-17.20 * math.sin(node) - 1.32 * math.sin(2 * sun)
                    - 0.23 * math.sin(2 * moon) + 0.21 * math.sin(2 * node))
    in_obliquity = (9.20 * math.cos(node) + 0.57 * math.cos(2 * sun)
                    + 0.10 * math.cos(2 * moon) - 0.09 * math.cos(2 * node))
    return in_longitude / 3600.0, in_obliquity / 3600.0


def _obliquity(t: float) -> float:
    """The true tilt of the Earth's axis, in degrees. Meeus 22.2 plus 22."""
    mean = (23.0 + (26.0 + (21.448 - t * (46.8150 + t * (0.00059
            - t * 0.001813))) / 60.0) / 60.0)
    return mean + _nutation(t)[1]


def _to_equatorial(longitude: float, latitude: float,
                   t: float) -> tuple[float, float]:
    """Ecliptic degrees to right ascension and declination. Meeus 13.3."""
    lam = math.radians(longitude)
    beta = math.radians(latitude)
    eps = math.radians(_obliquity(t))
    right_ascension = math.degrees(math.atan2(
        math.sin(lam) * math.cos(eps) - math.tan(beta) * math.sin(eps),
        math.cos(lam))) % 360.0
    declination = math.degrees(math.asin(
        math.sin(beta) * math.cos(eps)
        + math.cos(beta) * math.sin(eps) * math.sin(lam)))
    return right_ascension, declination


def _horizontal(right_ascension: float, declination: float, distance: float,
                when: float, latitude: float,
                longitude: float) -> tuple[float, float]:
    """Altitude and azimuth in degrees, topocentric.

    The parallax is taken off. For the moon that is most of a degree; for
    Venus at its closest it is half an arcminute and for Neptune it is
    nothing -- but it is one line, and the alternative is a comment
    explaining which planets it was decided not to bother with.
    """
    hour = math.radians((_gmst(when) + longitude - right_ascension) % 360.0)
    lat = math.radians(latitude)
    dec = math.radians(declination)

    height = math.asin(math.sin(lat) * math.sin(dec)
                       + math.cos(lat) * math.cos(dec) * math.cos(hour))
    azimuth = math.atan2(
        math.sin(hour),
        math.cos(hour) * math.sin(lat) - math.tan(dec) * math.cos(lat))

    parallax = math.asin(EARTH_RADIUS / (distance * AU))
    # atan2 there measures from south through west, which is the older
    # convention and is 180 degrees from what anybody expects to read.
    return (math.degrees(height - parallax * math.cos(height)),
            (math.degrees(azimuth) + 180.0) % 360.0)
