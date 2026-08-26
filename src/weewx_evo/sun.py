"""Where the sun is, and when it rises.

Two things need this. A reading: `maxSolarRad` is what a sensor would see with
no cloud above it, and that depends on the sun's elevation. And a chart: the
hours of darkness are shaded, because a temperature trace makes no sense
without knowing which part of it was night.

pyephem when it is installed and the arithmetic below when it is not, which is
the arrangement WeeWX has (it falls back to `weeutil.Sun`). pyephem is not a
dependency for the same reason nothing else is: a station runs for years
untouched, and every package is something that can stop working while nobody
is looking.

The fallback is not a poor relation. Measured against pyephem over six places
from Tromso to Ushuaia and the four turning points of the year, its
declination is within 0.002 degrees and its sunrise within forty seconds --
worst case, at a solstice; a few seconds the rest of the year. For comparison,
`weeutil.Sun`, which is what WeeWX itself falls back to, is out by up to six
and a half minutes over the same set. `tools/suncheck.py` is where those
numbers come from.

## Dusk is not an edge

WeeWX shades night against the moment the sun crosses the horizon. But the
light does not stop there: it fades over the half hour of civil twilight, and
over a great deal longer at high latitude in summer. So the boundaries of
dawn and dusk are reported as well, and a chart can draw the real thing
instead of a step.
"""

from __future__ import annotations

import datetime
import logging
import math
import time

log = logging.getLogger(__name__)

try:  # pragma: no cover - depends on the machine
    import ephem as _ephem
except ImportError:  # pragma: no cover
    _ephem = None

#: The sun's centre is this far below the horizon when its upper edge appears
#: to touch it: half its diameter, plus the refraction that lifts the image.
HORIZON = -0.833

#: Civil twilight: light enough to read outside, dark enough for the first
#: stars. The threshold everybody means by "dusk".
CIVIL = -6.0


def solar(when: float) -> tuple[float, float, float]:
    """The sun's declination, the equation of time, and Earth's distance.

    Declination in degrees, the equation of time in minutes, the distance in
    astronomical units. NOAA's algorithm, which is the one WeeWX's fallback
    uses and is good to a few seconds of arc for any year anybody will run
    this in.

    Everything else in this file is these three numbers and some geometry.
    """
    # Julian centuries since J2000.0.
    jd = when / 86400.0 + 2440587.5
    t = (jd - 2451545.0) / 36525.0

    mean_long = (280.46646 + t * (36000.76983 + t * 0.0003032)) % 360.0
    mean_anomaly = 357.52911 + t * (35999.05029 - 0.0001537 * t)
    eccentricity = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)

    m = math.radians(mean_anomaly)
    centre = (math.sin(m) * (1.914602 - t * (0.004817 + 0.000014 * t))
              + math.sin(2 * m) * (0.019993 - 0.000101 * t)
              + math.sin(3 * m) * 0.000289)
    true_long = mean_long + centre
    true_anomaly = mean_anomaly + centre

    # Earth's distance in AU. Over a year this is +-1.7%, and it enters the
    # radiation squared -- which is the 3.4% that leaving it out costs.
    distance = ((1.000001018 * (1 - eccentricity ** 2))
                / (1 + eccentricity * math.cos(math.radians(true_anomaly))))

    omega = 125.04 - 1934.136 * t
    apparent = true_long - 0.00569 - 0.00478 * math.sin(math.radians(omega))

    obliquity = (23.0 + (26.0 + (21.448 - t * (46.815 + t * (0.00059
                 - t * 0.001813))) / 60.0) / 60.0)
    obliquity += 0.00256 * math.cos(math.radians(omega))

    declination = math.degrees(math.asin(
        math.sin(math.radians(obliquity)) * math.sin(math.radians(apparent))))

    # The equation of time, in minutes: the difference between the sun and a
    # clock, which is up to a quarter of an hour either way.
    y = math.tan(math.radians(obliquity / 2.0)) ** 2
    l0 = math.radians(mean_long)
    eot = 4.0 * math.degrees(
        y * math.sin(2 * l0)
        - 2 * eccentricity * math.sin(m)
        + 4 * eccentricity * y * math.sin(m) * math.cos(2 * l0)
        - 0.5 * y * y * math.sin(4 * l0)
        - 1.25 * eccentricity ** 2 * math.sin(2 * m))

    return declination, eot, distance


def position(when: float, latitude: float, longitude: float,
             altitude_m: float = 0.0) -> tuple[float, float]:
    """The sun's elevation in degrees, and Earth's distance in AU."""
    if _ephem is not None:
        try:
            observer = _ephem.Observer()
            observer.lat = str(latitude)
            observer.lon = str(longitude)
            observer.elevation = altitude_m
            observer.date = _ephem.Date(
                _ephem.Date("1970/1/1 00:00:00") + when / 86400.0)
            sun = _ephem.Sun(observer)
            return math.degrees(float(sun.alt)), float(sun.earth_distance)
        except Exception:
            # Anything at all: a version that renamed something, a date it
            # will not take. The arithmetic below is right here and works.
            log.debug("pyephem could not place the sun; using the built-in "
                      "calculation", exc_info=True)

    declination, eot, distance = solar(when)
    minutes = (when % 86400) / 60.0
    true_solar = (minutes + eot + 4.0 * longitude) % 1440.0
    hour_angle = true_solar / 4.0 - 180.0

    lat, dec = math.radians(latitude), math.radians(declination)
    cos_zenith = (math.sin(lat) * math.sin(dec)
                  + math.cos(lat) * math.cos(dec)
                  * math.cos(math.radians(hour_angle)))
    cos_zenith = max(-1.0, min(1.0, cos_zenith))
    return 90.0 - math.degrees(math.acos(cos_zenith)), distance


def solar_noon(when: float, longitude: float) -> float:
    """The moment the sun is highest, on the sun's day containing `when`.

    Two corrections to clock noon: how far east or west the observer is of
    their zone's meridian, and the equation of time, which is the up to a
    quarter of an hour by which the sun runs ahead of or behind a clock over
    the year.
    """
    # Start from the UTC day, then step whole days until the answer is the
    # noon closest to the moment asked about. Without this a place near the
    # date line gets the wrong day's sun.
    midnight = int(when // 86400) * 86400
    _, eot, _ = solar(midnight + 43200)
    noon = midnight + 43200 - (longitude * 4.0 + eot) * 60.0
    while noon - when > 43200:
        noon -= 86400
    while when - noon > 43200:
        noon += 86400
    return noon


def crossings(day_ts: float, latitude: float, longitude: float,
              angle: float = HORIZON) -> tuple[float | None, float | None]:
    """When the sun passes an elevation on the way up and on the way down.

    Both times are around the solar noon nearest the moment given -- the
    sun's own day rather than a calendar one. That distinction is not
    pedantic: in Wellington solar noon falls twenty minutes after midnight
    UTC, so anchoring on a UTC date would pair one morning's sunrise with the
    previous evening's sunset.

    `(None, None)` where the sun never gets there or never leaves -- a polar
    winter has no sunrise, and saying so is better than returning a time that
    did not happen.

    The rising one first. Both are unix timestamps.
    """
    lat = math.radians(latitude)
    sin_angle = math.sin(math.radians(angle))

    def once(guess: float) -> float | None:
        """The half-day, in seconds, using the sun as it is at `guess`."""
        declination, _, _ = solar(guess)
        dec = math.radians(declination)
        denominator = math.cos(lat) * math.cos(dec)
        if abs(denominator) < 1e-12:
            return None
        cos_h = (sin_angle - math.sin(lat) * math.sin(dec)) / denominator
        if cos_h > 1.0 or cos_h < -1.0:
            return None
        return math.degrees(math.acos(cos_h)) / 15.0 * 3600.0

    noon = solar_noon(day_ts, longitude)
    half = once(noon)
    if half is None:
        return None, None

    # The declination is not the same at sunrise as it is at noon, and near
    # an equinox it moves a quarter of a degree between them. At high
    # latitude the sun crosses the horizon so obliquely that a quarter of a
    # degree is a minute and a half of time. So each end is worked out again
    # using the sun as it is at that end, which brings the whole thing to
    # within a few seconds of pyephem.
    rise = sets = None
    for direction in (-1, 1):
        guess = noon + direction * half
        for _ in range(2):
            adjusted = once(guess)
            if adjusted is None:
                break
            guess = noon + direction * adjusted
        if direction < 0:
            rise = guess
        else:
            sets = guess
    return rise, sets


def events(day_ts: float, latitude: float,
           longitude: float) -> dict[str, float | None]:
    """Sunrise, sunset and the civil twilight around them, for one day.

    Uses pyephem where it is installed: it accounts for the observer's own
    height and for the year's worth of small terms the formula above leaves
    out, which is worth about half a minute.
    """
    if _ephem is not None:
        found = _ephem_events(day_ts, latitude, longitude)
        if found is not None:
            return found

    rise, sets = crossings(day_ts, latitude, longitude, HORIZON)
    dawn, dusk = crossings(day_ts, latitude, longitude, CIVIL)
    return {"sunrise": rise, "sunset": sets, "dawn": dawn, "dusk": dusk}


def _ephem_events(day_ts: float, latitude: float,
                  longitude: float) -> dict[str, float | None] | None:
    """The same four moments, from pyephem. None if it will not say."""
    try:  # pragma: no cover - depends on the machine
        # Anchored on solar noon and looking outwards, so that the pair
        # belongs to one day of the sun's rather than one of the calendar's.
        noon = solar_noon(day_ts, longitude)
        observer = _ephem.Observer()
        observer.lat = str(latitude)
        observer.lon = str(longitude)
        observer.date = _ephem.Date(
            _ephem.Date("1970/1/1 00:00:00") + noon / 86400.0)
        sun = _ephem.Sun()

        def moment(value: object) -> float:
            return (float(value) - float(_ephem.Date("1970/1/1 00:00:00"))) \
                * 86400.0

        # pyephem models refraction itself from the observer's pressure, and
        # subtracts the sun's own radius unless told to use its centre. So the
        # -0.833 used everywhere else in this file must NOT be handed to it:
        # that figure already contains both, and passing it in counts them
        # twice. Four or five minutes' worth, which is a night band visibly
        # out of step with the temperature falling.
        #
        # The recipe pyephem's own documentation gives: turn its refraction
        # off, set the horizon to the 34 arcminutes of it that the standard
        # definition assumes, and let it take the upper limb.
        observer.pressure = 0
        out: dict[str, float | None] = {}
        observer.horizon = "-0:34"
        for key, call in (("sunrise", observer.previous_rising),
                          ("sunset", observer.next_setting)):
            try:
                out[key] = moment(call(sun, start=observer.date))
            except Exception:
                out[key] = None  # never rises, or never sets
        # Twilight is defined by where the sun's centre is, so the limb
        # correction has to come off as well.
        observer.horizon = str(CIVIL)
        for key, call in (("dawn", observer.previous_rising),
                          ("dusk", observer.next_setting)):
            try:
                out[key] = moment(call(sun, start=observer.date,
                                       use_center=True))
            except Exception:
                out[key] = None
        return out
    except Exception:
        log.debug("pyephem could not work out sunrise; using the built-in "
                  "calculation", exc_info=True)
        return None


def day_night(start: float, stop: float, latitude: float | None,
              longitude: float | None) -> dict | None:
    """What a chart needs to shade the hours of darkness.

    Returns which of day or night the span begins in, every crossing of the
    horizon inside it, and the stretches of dawn and dusk around them. None
    where nothing crosses at all, which is a polar summer or winter and is
    better left unshaded than shaded wrongly.
    """
    if latitude is None or longitude is None:
        return None

    start, stop = int(start), int(stop)
    transitions: list[int] = []
    twilight: list[dict] = []
    first: str | None = None

    # A day either side, because the sunset that matters for the first hour
    # of the span happened before it began.
    for ts in range(start - 86400, stop + 86401, 86400):
        found = events(ts, latitude, longitude)
        rise, sets = found["sunrise"], found["sunset"]
        dawn, dusk = found["dawn"], found["dusk"]

        if rise is not None and start < rise < stop:
            transitions.append(int(rise))
            if first is None:
                first = "night"
        if sets is not None and start < sets < stop:
            transitions.append(int(sets))
            if first is None:
                first = "day"

        # Dawn runs from the start of civil twilight to sunrise, getting
        # lighter; dusk from sunset to the end of it, getting darker. Saying
        # which is which saves a client working it out from the crossings.
        if dawn is not None and rise is not None \
                and dawn < stop and rise > start:
            twilight.append({"from": int(dawn), "to": int(rise), "dir": "dawn"})
        if dusk is not None and sets is not None \
                and sets < stop and dusk > start:
            twilight.append({"from": int(sets), "to": int(dusk), "dir": "dusk"})

    if first is None and not transitions:
        return None

    # A day either side means a crossing can be found twice.
    transitions = sorted(set(transitions))
    seen = set()
    unique = []
    for band in sorted(twilight, key=lambda b: b["from"]):
        key = (band["from"], band["to"])
        if key not in seen:
            seen.add(key)
            unique.append(band)

    if first is None:
        # Nothing crossed inside the span, but something is happening around
        # it: work out which side of the horizon the sun is on right now.
        elevation, _ = position(start, latitude, longitude)
        first = "day" if elevation > HORIZON else "night"
    return {"first": first, "transitions": transitions, "twilight": unique}


def rising_setting(after: float, latitude: float, longitude: float,
                   body: str = "sun", horizon: float | None = None,
                   altitude_m: float = 0.0, use_center: bool = False,
                   temperature: float = 15.0,
                   pressure: float = 1010.0) -> dict[str, float | None]:
    """The next rising, setting and transit after a given moment.

    Anchored at an instant rather than at a day, because that is the only
    unambiguous way to ask: "when does the moon rise today" has no answer on
    the days it rises twice and none at all on the days it does not rise. The
    caller passes local midnight and gets what WeeWX's almanac gives.

    Needs pyephem for the moon. For the sun it falls back to the arithmetic
    in this file, which is anchored on solar noon and so answers a slightly
    different question -- close enough for a sunrise, and the difference is
    named in `tools/suncheck.py`.
    """
    out: dict[str, float | None] = {"rise": None, "set": None,
                                    "transit": None}
    if _ephem is not None:
        try:
            observer = _ephem.Observer()
            observer.lat = str(latitude)
            observer.lon = str(longitude)
            # The observer's own height lowers the horizon: from 440 metres
            # the sun rises twenty seconds earlier than at sea level, and a
            # skin that prints seconds shows it.
            observer.elevation = float(altitude_m or 0.0)
            observer.date = _ephem.Date(
                _ephem.Date("1970/1/1 00:00:00") + after / 86400.0)
            # WeeWX's almanac lets pyephem model refraction from the
            # observer's air, with a horizon of zero. The other convention --
            # refraction off, horizon at 34 arcminutes -- is the one used for
            # the night shading in `day_night`, where it matches the
            # arithmetic that runs without pyephem.
            #
            # Twenty seconds apart, and both defensible. This one is here
            # because a skin printing sunrise to the second should print what
            # it printed yesterday under WeeWX.
            observer.temp = temperature
            observer.pressure = pressure
            observer.horizon = math.radians(horizon or 0.0)
            thing = _ephem.Sun() if body == "sun" else _ephem.Moon()

            def moment(value: object) -> float:
                return ((float(value)
                         - float(_ephem.Date("1970/1/1 00:00:00")))
                        * 86400.0)

            for key, call in (("rise", observer.next_rising),
                              ("set", observer.next_setting)):
                try:
                    out[key] = moment(call(thing, start=observer.date,
                                           use_center=use_center))
                except Exception:
                    out[key] = None  # never rises, or never sets
            try:
                # No `use_center` here: a transit is the moment the centre
                # crosses the meridian whatever you asked for the horizon,
                # and passing it raises rather than being ignored.
                out["transit"] = moment(
                    observer.next_transit(thing, start=observer.date))
            except Exception:
                out["transit"] = None
            return out
        except Exception:
            log.debug("pyephem could not work out the %s rising", body,
                      exc_info=True)

    if body != "sun":
        # The moon's path is not something to approximate here. None, so a
        # skin prints its own "N/A" rather than a wrong time.
        return out
    rise, sets = crossings(after + 43200, latitude, longitude,
                           HORIZON if horizon is None else horizon)
    out["rise"], out["set"] = rise, sets
    out["transit"] = solar_noon(after + 43200, longitude)
    return out


# -- the moon --------------------------------------------------------------

#: The eight names a phase is given. WeeWX's defaults exactly, because a
#: skin prints `$almanac.moon_phase` straight into a page and "Full Moon"
#: where it has always said "Full" is a visible change. A skin that names its
#: own overrides these.
MOON_PHASES = ("New", "Waxing crescent", "First quarter", "Waxing gibbous",
               "Full", "Waning gibbous", "Last quarter", "Waning crescent")

#: One synodic month: new moon to new moon, in days. Not the orbital period --
#: the Earth has moved too, and the difference is two and a bit days.
SYNODIC = 29.530588853

#: A new moon that actually happened, as the anchor everything counts from.
#: 2000-01-06 18:14 UTC.
KNOWN_NEW_MOON = 947182440.0


def moon_age(when: float) -> float:
    """Days since the last new moon, 0 to 29.53.

    Good to a few hours, which is what a phase name and a percentage need.
    pyephem is used where it is installed and is good to minutes; this is the
    fallback, and the difference does not show in either of those.
    """
    if _ephem is not None:
        try:
            date = _ephem.Date(_ephem.Date("1970/1/1 00:00:00") + when / 86400.0)
            previous = _ephem.previous_new_moon(date)
            return float(date - previous)
        except Exception:
            log.debug("pyephem could not age the moon; using the built-in "
                      "calculation", exc_info=True)
    return ((when - KNOWN_NEW_MOON) / 86400.0) % SYNODIC


def moon_fullness(when: float) -> int:
    """How much of the disc is lit, as a percentage.

    Not the fraction of the cycle: the moon is half lit a quarter of the way
    through, which is where a linear reading would say 25.
    """
    if _ephem is not None:
        try:
            observer = _ephem.Observer()
            observer.date = _ephem.Date(
                _ephem.Date("1970/1/1 00:00:00") + when / 86400.0)
            moon = _ephem.Moon(observer)
            return int(round(float(moon.moon_phase) * 100.0))
        except Exception:
            log.debug("pyephem could not light the moon; using the built-in "
                      "calculation", exc_info=True)
    angle = 2.0 * math.pi * moon_age(when) / SYNODIC
    return int(round(50.0 * (1.0 - math.cos(angle))))


def moon_phase(when: float) -> tuple[int, str]:
    """Which of the eight phases, and its name.

    The quarters are moments and the crescents are stretches, so the eight
    are not eight equal slices: a name is chosen by which eighth of the cycle
    the moon is in, which is what everybody means by "waxing gibbous".
    """
    index = int((moon_age(when) / SYNODIC) * 8 + 0.5) % 8
    return index, MOON_PHASES[index]


def moon_events(day_ts: float, latitude: float,
                longitude: float) -> dict[str, float | None]:
    """When the moon rises, sets and is highest, for one day.

    Needs pyephem: the moon's path is not the sun's, and an orbit that is
    tilted, elliptical and pulled about by the Earth is not something to
    approximate in thirty lines. Without pyephem these come back as None and
    a skin prints its own "N/A" rather than a wrong time.
    """
    out: dict[str, float | None] = {"rise": None, "set": None, "transit": None}
    if _ephem is None:
        return out
    try:
        noon = solar_noon(day_ts, longitude)
        observer = _ephem.Observer()
        observer.lat = str(latitude)
        observer.lon = str(longitude)
        observer.date = _ephem.Date(
            _ephem.Date("1970/1/1 00:00:00") + noon / 86400.0)
        moon = _ephem.Moon()

        def moment(value: object) -> float:
            return (float(value)
                    - float(_ephem.Date("1970/1/1 00:00:00"))) * 86400.0

        for key, call in (("rise", observer.previous_rising),
                          ("set", observer.next_setting),
                          ("transit", observer.next_transit)):
            try:
                out[key] = moment(call(moon, start=observer.date))
            except Exception:
                out[key] = None
    except Exception:
        log.debug("pyephem could not place the moon", exc_info=True)
    return out


def local_midnight(ts: float) -> int:
    """The start of the local day a timestamp falls in."""
    return int(datetime.datetime.fromtimestamp(ts).replace(
        hour=0, minute=0, second=0, microsecond=0).timestamp())


def describe(day_ts: float, latitude: float, longitude: float) -> str:
    """One day's sun, as a line somebody reads. For the CLI."""
    found = events(day_ts, latitude, longitude)
    parts = []
    for key, name in (("dawn", "dawn"), ("sunrise", "sunrise"),
                      ("sunset", "sunset"), ("dusk", "dusk")):
        value = found[key]
        parts.append(f"{name} {time.strftime('%H:%M', time.localtime(value))}"
                     if value is not None else f"no {name}")
    return ", ".join(parts)
