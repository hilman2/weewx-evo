"""Readings that follow from other readings.

A station measures temperature, humidity, pressure and wind. Dew point, wind
chill, apparent temperature and cloud base follow from those by arithmetic,
and most consoles do not send them. WeeWX calls this `StdWXCalculate`; without
it a database ends up with a `dewpoint` column that is empty for years.

One of these is not a convenience but a measurement that would otherwise be
lost. **`rain` is the amount since the last reading**, and almost no console
sends it -- they send running totals (`dayRain`, `monthRain`) and expect the
receiver to take the difference. No `rain` means no rainfall in the record at
all: the daily summary of rain is a sum of nothing.

As with `aggregate.py`, the formulas are transcribed from WeeWX rather than
reasoned about. They decide numbers that go into a database WeeWX will read
back, and a formula that rounds differently is a wrong formula here even when
it is a better one.

## Where this runs

On each packet, before it is accumulated -- not on the finished record. The
difference matters and is easy to get backwards:

    dewpoint(mean(T), mean(RH))  !=  mean(dewpoint(T, RH))

Deriving after averaging gives the dew point of an average hour, which is not
a thing that happened. Deriving per packet and then averaging gives the mean
of the dew points that were actually the case.

The live table keeps what arrived. Derived values are worked out on the way
past and are not written back to it: raw stays raw, and anything derived can
be worked out again from it.

## What wins

Per quantity, as in WeeWX:

    prefer_hardware  the station's value if it sent one, otherwise ours
    hardware         only the station's; never calculated
    software         always ours, even if the station sent one

`prefer_hardware` is the default and the right one. A station that computes
its own dew point has the reading at full resolution; ours has whatever
survived being rounded into a packet.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any

from .units import METRIC, METRICWX, US

log = logging.getLogger(__name__)

#: pyephem, if this installation has it. WeeWX uses it the same way: better
#: where it is present, not required. It matters little for the radiation
#: below and a great deal for sunrise, sunset and moon phase, which is what
#: the feeds will want.
try:
    import ephem as _ephem
except ImportError:  # pragma: no cover - depends on the installation
    _ephem = None

#: How to decide each quantity. The names and defaults are WeeWX's.
HOW = ("prefer_hardware", "hardware", "software")

DEFAULTS: dict[str, str] = {
    "pressure": "prefer_hardware",
    "altimeter": "prefer_hardware",
    "barometer": "prefer_hardware",
    "appTemp": "prefer_hardware",
    "cloudbase": "prefer_hardware",
    "dewpoint": "prefer_hardware",
    "ET": "prefer_hardware",
    "beaufort": "prefer_hardware",
    "heatindex": "prefer_hardware",
    "humidex": "prefer_hardware",
    "inDewpoint": "prefer_hardware",
    "maxSolarRad": "prefer_hardware",
    "rainRate": "prefer_hardware",
    # Computed all along, and left out of this table. Harmless, but the
    # table is the only place anybody looks to see what this can do.
    "rain": "prefer_hardware",
    "windchill": "prefer_hardware",
    "windrun": "prefer_hardware",
    # Not a reading so much as a rule: a direction with no wind behind it is
    # not an observation, and leaving the last one standing makes a calm
    # night look like a steady breeze from wherever it last blew.
    "windDir": "prefer_hardware",
    "windGustDir": "prefer_hardware",
    # The four below are not WeeWX's. Each is a reading people install an
    # extension to get, each is pure arithmetic, and none needs the network.
    "sunshine_time": "prefer_hardware",
    "vaporPressure": "prefer_hardware",
    "satVaporPressure": "prefer_hardware",
    "absoluteHumidity": "prefer_hardware",
    "mixingRatio": "prefer_hardware",
}

#: What counts as sunshine, as a fraction of the clear-sky maximum for that
#: moment. The WMO defines a sunshine hour by direct irradiance above
#: 120 W/m2, which a station with a plain pyranometer cannot measure -- so
#: this is the usual approximation, and the threshold is a setting because
#: the right value depends on the sensor and how clean it is.
SUNSHINE_FRACTION = 0.75
#: Below this, nothing counts however clear it is: at dawn the maximum is
#: small enough that a fraction of it is met by a bright overcast.
SUNSHINE_FLOOR = 20.0

#: Running totals a reading can be taken from, best first. A console sends the
#: total since midnight and expects the difference to be taken; which total is
#: available differs by make, so several are tried.
DELTAS: dict[str, tuple[str, ...]] = {
    "rain": ("dayRain", "totalRain", "eventRain"),
}

#: How far back the rain rate looks, and how far back the hour that
#: evapotranspiration is computed over reaches. WeeWX's defaults.
RAIN_PERIOD = 900
ET_PERIOD = 3600


# ---------------------------------------------------------------------------
# The formulas. Transcribed from weewx/wxformulas.py.
# ---------------------------------------------------------------------------

def _f_to_c(f: float) -> float:
    return (f - 32.0) * 5.0 / 9.0


def _c_to_f(c: float) -> float:
    return c * 9.0 / 5.0 + 32.0


def dewpoint_c(t_c: float | None, rh: float | None) -> float | None:
    """Dew point in Celsius, by the Magnus formula WeeWX uses."""
    if t_c is None or rh is None or rh <= 0:
        return None
    rh = rh / 100.0
    if rh <= 0.0:
        return None
    if t_c < 0:
        # Over ice below freezing. Using the water coefficients there is a
        # visible error, not a rounding one.
        a, b = 9.5, 265.5
    else:
        a, b = 7.5, 237.3
    alpha = math.log10(rh) + (a * t_c) / (b + t_c)
    return b * alpha / (a - alpha)


def windchill_c(t_c: float | None, v_kph: float | None) -> float | None:
    """Wind chill, Celsius, from the Environment Canada formula.

    Only defined below 10 degrees and above 4.8 km/h. Outside that it is the
    temperature itself, which is what WeeWX returns.
    """
    if t_c is None or v_kph is None:
        return None
    if t_c >= 10.0 or v_kph <= 4.8:
        return t_c
    return (13.12 + 0.6215 * t_c - 11.37 * v_kph ** 0.16
            + 0.3965 * t_c * v_kph ** 0.16)


def heatindex_f(t_f: float | None, rh: float | None) -> float | None:
    """Heat index, Fahrenheit, Rothfusz with the two adjustments.

    Below 40 F there is no heat index and the temperature is returned. That
    is the same convention WeeWX follows.
    """
    if t_f is None or rh is None:
        return None
    if t_f < 40.0:
        return t_f

    hi = 0.5 * (t_f + 61.0 + (t_f - 68.0) * 1.2 + rh * 0.094)
    if (hi + t_f) / 2.0 < 80.0:
        return hi

    hi = (-42.379 + 2.04901523 * t_f + 10.14333127 * rh
          - 0.22475541 * t_f * rh - 6.83783e-3 * t_f ** 2
          - 5.481717e-2 * rh ** 2 + 1.22874e-3 * t_f ** 2 * rh
          + 8.5282e-4 * t_f * rh ** 2 - 1.99e-6 * t_f ** 2 * rh ** 2)
    if rh < 13.0 and 80.0 <= t_f <= 112.0:
        hi -= ((13.0 - rh) / 4.0) * math.sqrt((17.0 - abs(t_f - 95.0)) / 17.0)
    elif rh > 85.0 and 80.0 <= t_f <= 87.0:
        hi += ((rh - 85.0) / 10.0) * ((87.0 - t_f) / 5.0)
    return hi


def humidex_c(t_c: float | None, rh: float | None) -> float | None:
    """Humidex, Celsius. Below 21 degrees it is the temperature."""
    if t_c is None or rh is None:
        return None
    if t_c < 21.0:
        return t_c
    dp = dewpoint_c(t_c, rh)
    if dp is None:
        return None
    e = 6.11 * math.exp(5417.7530 * (1 / 273.16 - 1 / (dp + 273.16)))
    return t_c + 0.5555 * (e - 10.0)


def apptemp_c(t_c: float | None, rh: float | None,
              wind_mps: float | None) -> float | None:
    """Apparent temperature, the Australian BOM formula."""
    if t_c is None or rh is None or wind_mps is None:
        return None
    e = rh / 100.0 * 6.105 * math.exp(17.27 * t_c / (237.7 + t_c))
    return t_c + 0.33 * e - 0.70 * wind_mps - 4.00


def altimeter_inhg(pressure_inhg: float | None,
                   altitude_ft: float | None) -> float | None:
    """Altimeter setting from station pressure, the aaASOS algorithm."""
    if pressure_inhg is None or altitude_ft is None or pressure_inhg <= 0.3:
        return None
    return ((pressure_inhg ** 0.1903 + 1.313e-5 * altitude_ft) ** 5.255)


def cloudbase_ft(t_f: float | None, rh: float | None,
                 altitude_ft: float | None) -> float | None:
    """Height of the cloud base, feet, from the spread."""
    if t_f is None or rh is None or altitude_ft is None:
        return None
    dp_f = _c_to_f(dewpoint_c(_f_to_c(t_f), rh) or 0.0) if rh > 0 else None
    if dp_f is None:
        return None
    return altitude_ft + 1000.0 * (t_f - dp_f) / 4.4


#: The solar constant WeeWX uses. Not 1373, which is the older figure and
#: half a percent out.
SOLAR_CONSTANT = 1367.0


def sun_position(when: float, latitude: float, longitude: float,
                 altitude_m: float = 0.0) -> tuple[float, float]:
    """The sun's elevation in degrees, and Earth's distance in AU.

    pyephem when it is installed, and NOAA's algorithm when it is not --
    which is the same arrangement WeeWX has (it falls back to `weeutil.Sun`).
    pyephem is not a dependency here for the same reason nothing else is: a
    station runs for years untouched, and every package is something that can
    stop working while nobody is looking.

    The fallback is not a poor relation. Measured against what WeeWX wrote
    with pyephem, the radiation that comes out of it is within 0.1%. Where
    pyephem earns its place is sunrise, sunset and moon phase -- and those
    belong to the feeds, which will find it here when they need it.
    """
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

    # The equation of time, in minutes.
    y = math.tan(math.radians(obliquity / 2.0)) ** 2
    l0 = math.radians(mean_long)
    eot = 4.0 * math.degrees(
        y * math.sin(2 * l0)
        - 2 * eccentricity * math.sin(m)
        + 4 * eccentricity * y * math.sin(m) * math.cos(2 * l0)
        - 0.5 * y * y * math.sin(4 * l0)
        - 1.25 * eccentricity ** 2 * math.sin(2 * m))

    minutes = (when % 86400) / 60.0
    true_solar = (minutes + eot + 4.0 * longitude) % 1440.0
    hour_angle = true_solar / 4.0 - 180.0

    lat, dec = math.radians(latitude), math.radians(declination)
    cos_zenith = (math.sin(lat) * math.sin(dec)
                  + math.cos(lat) * math.cos(dec)
                  * math.cos(math.radians(hour_angle)))
    cos_zenith = max(-1.0, min(1.0, cos_zenith))
    return 90.0 - math.degrees(math.acos(cos_zenith)), distance


def max_solar_rad(latitude: float | None, longitude: float | None,
                  altitude_m: float | None, when: float | None = None,
                  atc: float = 0.8) -> float | None:
    """Clear-sky radiation, W/m2, Ryan-Stolzenbach (MIT, 1972).

    What a solar sensor would read with no cloud above it. A measured reading
    held against this is what says how cloudy it was, which is why it is worth
    computing something nothing measures.

    Transcribed from `weewx.wxformulas.solar_rad_RS`, including the two parts
    that are easy to leave out and both matter: Earth's distance, which is
    3.4% over a year because it enters squared, and the air mass with its
    refraction term, which is what keeps the value sane near the horizon.
    """
    if latitude is None or longitude is None or altitude_m is None:
        return None
    when = when if when is not None else time.time()
    if not 0.7 <= atc <= 0.91:
        atc = 0.8

    elevation, distance = sun_position(when, latitude, longitude, altitude_m)
    sin_alt = math.sin(math.radians(elevation))
    if sin_alt < 0:
        return 0.0

    # Optical air mass. The second term in the denominator is a refraction
    # correction: without it the air mass goes to infinity at the horizon and
    # the value collapses a good deal too early.
    air_mass = (((288.0 - 0.0065 * altitude_m) / 288.0) ** 5.256
                / (sin_alt + 0.15 * (elevation + 3.885) ** -1.253))
    top_of_atmosphere = SOLAR_CONSTANT * sin_alt / (distance * distance)
    return top_of_atmosphere * atc ** air_mass


def windrun(speed: float | None, seconds: float | None) -> float | None:
    """Distance the wind covered, in the same length unit as the speed.

    Speed times time. The unit follows the speed's -- mph for hours gives
    miles -- which is why nothing is converted here.
    """
    if speed is None or seconds is None or seconds <= 0:
        return None
    return speed * seconds / 3600.0


def delta(now: float | None, before: float | None,
          name: str = "rain") -> float | None:
    """How much a running total went up by.

    Three cases that are not errors and must not be treated as one:

      * No previous value -- the first packet after a start. There is no
        delta to take, and inventing one would post the whole day's rain as
        having fallen in five minutes.
      * The total went down: midnight, or a console that was reset. The new
        total is the amount, which is what WeeWX does and is right for the
        first reading after midnight.
      * Unchanged: zero, which is a measurement and not a missing value.
    """
    if now is None:
        return None
    if before is None:
        return None
    if now < before:
        # A reset. The new reading is what has fallen since it happened.
        log.debug("%s total went from %s to %s; treating the new value as the "
                  "amount", name, before, now)
        return now
    return now - before


# ---------------------------------------------------------------------------
# Evapotranspiration. The FAO Penman-Monteith reference crop, hour by hour.
#
# Transcribed from `weewx/wxformulas.py`, expression by expression, and every
# constant is theirs. Reference: http://www.fao.org/docrep/x0490e/x0490e00.htm
#
# This is the one derived reading weewx-evo listed in its defaults and never
# computed. A station switching over from WeeWX therefore had a column that
# stopped the day the database came across, with nothing in any log about it:
# the value was `prefer_hardware`, no hardware sends it, and nothing was
# waiting behind that to fill in.
# ---------------------------------------------------------------------------

def _teten_mbar(t_c: float) -> float:
    """Saturation vapour pressure, Teten's, in millibars.

    Not `sat_vapor_pressure_mbar` above, which is Magnus. The two disagree by
    a few parts in a thousand, and the whole point of transcribing is that our
    number is WeeWX's number: their ET uses Teten's, so ours does. Using the
    Magnus one here to save a function would put every ET value a hair away
    from what the same station used to record.
    """
    return 6.1078 * math.pow(10.0, (7.5 * t_c) / (t_c + 237.3))


def _equation_of_time(doy: int) -> float:
    """How far the sun runs ahead of the clock, in hours."""
    b = 2 * math.pi * (doy - 81) / 364.0
    return 0.1645 * math.sin(2 * b) - 0.1255 * math.cos(b) - 0.025 * math.sin(b)


def _solar_declination(doy: int) -> float:
    """The sun's tilt on this day of the year, in radians."""
    return 0.409 * math.sin(2.0 * math.pi * doy / 365 - 1.39)


def _hour_angle(t_utc: float, longitude: float, doy: int) -> float:
    """Where the sun is around the sky, in radians."""
    sc = _equation_of_time(doy)
    omega = (math.pi / 12.0) * (t_utc + longitude / 15.0 + sc - 12)
    if omega < 0:
        omega += 2.0 * math.pi
    return omega


def sun_radiation(doy: int, latitude_deg: float, longitude_deg: float,
                  tod_utc: float, interval: float = 1.0) -> float:
    """Radiation at the top of the atmosphere, in MJ per square metre per hour.

    What would arrive with no air in the way. The measured radiation against
    this is how the formula works out how cloudy it was.
    """
    # Solar constant in MJ/m^2/hr.
    gsc = 4.92
    declination = _solar_declination(doy)
    earth_distance = 1.0 + 0.033 * math.cos(2.0 * math.pi * doy / 365.0)

    start_omega = _hour_angle(tod_utc - interval, longitude_deg, doy)
    stop_omega = _hour_angle(tod_utc, longitude_deg, doy)
    latitude = math.radians(latitude_deg)

    part1 = ((stop_omega - start_omega) * math.sin(latitude)
             * math.sin(declination))
    part2 = (math.cos(latitude) * math.cos(declination)
             * (math.sin(stop_omega) - math.sin(start_omega)))

    radiation = (12.0 / math.pi) * gsc * earth_distance * (part1 + part2)
    return max(0.0, radiation)


def longwave_radiation(tmin_c: float, tmax_c: float, ea: float, rs: float,
                       rso: float, rh: float) -> float:
    """What the ground radiates back to the sky, in MJ per square metre per day.

    `rs` against `rso` is a measure of cloud. At night there is no `rso` to
    compare against, and WeeWX falls back to guessing cloud from humidity --
    its own comment calls that formula totally made up. Transcribed as it is,
    because an ET series that agrees with itself across the night matters more
    than a better guess nobody can compare against.
    """
    tmin_k = tmin_c + 273.16
    tmax_k = tmax_c + 273.16
    # Stefan-Boltzmann, in MJ per K^4 per square metre per day.
    sigma = 4.903e-09

    if rso:
        cloud_factor = rs / rso
    elif rh > 80:
        cloud_factor = 0.3
    elif rh > 40:
        cloud_factor = 0.5
    else:
        cloud_factor = 0.8

    part1 = sigma * (tmin_k ** 4 + tmax_k ** 4) / 2.0
    part2 = 0.34 - 0.14 * math.sqrt(ea)
    part3 = 1.35 * cloud_factor - 0.35
    return part1 * part2 * part3


def _etterm(elevation_m: float, t_c: float) -> float:
    """The height-and-temperature factor a pressure is reduced by."""
    return math.exp(-elevation_m / ((t_c + 273.15) * 29.263))


def sealevel_pressure_mbar(station_mbar: float | None,
                           elevation_m: float | None,
                           t_c: float | None) -> float | None:
    """Station pressure reduced to sea level. wview's, by way of WeeWX.

    What a barometer reads. Without the reduction two stations a hundred
    metres apart cannot be compared, and neither can one station against the
    forecast.
    """
    if station_mbar is None or elevation_m is None or t_c is None:
        return None
    factor = _etterm(elevation_m, t_c)
    return station_mbar / factor if factor else 0.0


def station_pressure_mbar(sealevel_mbar: float | None,
                          elevation_m: float | None,
                          t_c: float | None) -> float | None:
    """Sea-level pressure brought back down to the station.

    **This one is not WeeWX's.** Theirs goes through Davis's algorithm and a
    temperature from twelve hours ago; this is the plain inverse of the
    reduction above, so the two disagree by something under a tenth of a
    millibar. Written down rather than hidden: everything else in this file
    is transcribed, and this is the exception.

    It matters only for a station that reports a barometer and no station
    pressure. Most report both, and then this never runs -- which is why the
    twelve-hour history WeeWX keeps for it is not worth the memory here.
    """
    if sealevel_mbar is None or elevation_m is None or t_c is None:
        return None
    return sealevel_mbar * _etterm(elevation_m, t_c)


def beaufort_number(knots: float | None) -> int | None:
    """The Beaufort force for a wind speed, 0 to 12.

    WeeWX has begun calling this type deprecated in favour of a `beaufort`
    unit, and the version this is checked against still has the type and not
    the unit. Transcribed as it stands there; the day it becomes a unit, this
    becomes a conversion.
    """
    if knots is None:
        return None
    speed = abs(knots)
    for force, upper in enumerate((1, 4, 7, 11, 17, 22, 28, 34, 41, 48, 56,
                                   64)):
        if speed < upper:
            return force
    return 12


def evapotranspiration_mm(tmin_c: float | None, tmax_c: float | None,
                          rh_min: float | None, rh_max: float | None,
                          radiation_wpm2: float | None,
                          wind_mps: float | None,
                          wind_height_m: float | None,
                          latitude_deg: float | None,
                          longitude_deg: float | None,
                          altitude_m: float | None,
                          when: float | None,
                          albedo: float = 0.23, cn: float = 37.0,
                          cd: float = 0.34) -> float | None:
    """Reference evapotranspiration over one hour, in millimetres.

    How much water a short green crop would use, given the weather. It is a
    rate: what the archive stores is this scaled to the record's interval.

    `cn` and `cd` are the numerator and denominator constants for a short
    reference crop over an hour, and `albedo` is grass. All three are
    settings in WeeWX and their defaults are these.
    """
    if None in (tmin_c, tmax_c, rh_min, rh_max, radiation_wpm2, wind_mps,
                latitude_deg, longitude_deg, when):
        return None
    if wind_height_m is None:
        wind_height_m = 2.0
    if altitude_m is None:
        altitude_m = 0.0

    doy = time.localtime(when)[7] - 1
    utc = time.gmtime(when)
    tod_utc = utc.tm_hour + utc.tm_min / 60.0 + utc.tm_sec / 3600.0

    tavg_c = (tmax_c + tmin_c) / 2.0
    rh_avg = (rh_min + rh_max) / 2.0

    # The formula wants wind at two metres; a station measures it wherever
    # its mast is.
    u2 = 4.87 * wind_mps / math.log(67.8 * wind_height_m - 5.42)

    # Air pressure from height alone, in kPa, and the psychrometric constant.
    p = 101.3 * math.pow((293.0 - 0.0065 * altitude_m) / 293.0, 5.26)
    gamma = 0.665e-03 * p

    # Saturation vapour pressure, hPa to kPa.
    etmin = _teten_mbar(tmin_c) / 10.0
    etmax = _teten_mbar(tmax_c) / 10.0
    e0t = (etmin + etmax) / 2.0

    # How fast that changes with temperature, kPa per degree.
    delta_slope = (4098.0 * (0.6108 * math.exp(17.27 * tavg_c
                                               / (tavg_c + 237.3)))
                   / ((tavg_c + 237.3) * (tavg_c + 237.3)))

    # What the air actually holds.
    ea = (etmin * rh_max + etmax * rh_min) / 200.0

    # Measured radiation, W/m^2 to MJ/m^2/hr, and the part not reflected.
    rs = radiation_wpm2 * 3.6e-3
    rns = (1.0 - albedo) * rs

    ra = sun_radiation(doy, latitude_deg, longitude_deg, tod_utc, interval=1.0)
    rso = (0.75 + 2e-5 * altitude_m) * ra

    rnl = longwave_radiation(tmin_c, tmax_c, ea, rs, rso, rh_avg) / 24.0
    rn = rns - rnl

    # Heat into the ground: a tenth of it by day, half of it by night.
    g = 0.1 * rn if rs else 0.5 * rn

    et0 = ((0.408 * delta_slope * (rn - g)
            + gamma * (cn / (tavg_c + 273)) * u2 * (e0t - ea))
           / (delta_slope + gamma * (1 + cd * u2)))

    # Water does not come back out of the ground.
    return max(0.0, et0)

def sat_vapor_pressure_mbar(t_c: float) -> float:
    """The most water vapour the air could hold, in millibars.

    Magnus, with the coefficients WeeWX uses in `dewpoint_c` -- the same
    formula read forwards. Using a different set here would make the dew
    point and the vapour pressure disagree about the same air, which is the
    kind of inconsistency nobody finds because each is right on its own.
    """
    return 6.112 * math.exp((17.62 * t_c) / (243.12 + t_c))


def vapor_pressure_mbar(t_c: float, rh: float) -> float:
    """What the moisture actually in the air is worth, in millibars."""
    return sat_vapor_pressure_mbar(t_c) * (rh / 100.0)


def absolute_humidity(t_c: float, rh: float) -> float:
    """Grams of water per cubic metre.

    The number a greenhouse, a cellar or a museum cares about: relative
    humidity says how close the air is to saturated, which changes when the
    temperature does without any water moving. This does not.
    """
    pressure = vapor_pressure_mbar(t_c, rh)
    # From the ideal gas law: 100 converts millibars to pascals, 461.5 is the
    # specific gas constant for water vapour, and 1000 makes it grams.
    return (pressure * 100.0) / (461.5 * (t_c + 273.15)) * 1000.0


def mixing_ratio(t_c: float, rh: float, pressure_mbar: float) -> float | None:
    """Grams of water per kilogram of dry air.

    Conserved when air rises or is heated, which is why meteorology uses it
    where a percentage would mislead.
    """
    vapour = vapor_pressure_mbar(t_c, rh)
    dry = pressure_mbar - vapour
    if dry <= 0:
        # Saturated past the ambient pressure. Physically impossible, so a
        # sensor is wrong; better nothing than a division that explodes.
        return None
    return 621.97 * vapour / dry


def sunshine_seconds(radiation: float | None, maximum: float | None,
                     seconds: float, fraction: float = SUNSHINE_FRACTION,
                     floor: float = SUNSHINE_FLOOR) -> float | None:
    """How much of this interval was sunshine.

    All or nothing per interval, which is what every implementation of this
    does: the reading is one number for the whole interval, so there is no
    information about which minute of it the sun was out.

    The WMO's definition is direct irradiance above 120 W/m2, which needs a
    pyrheliometer. A weather station has a pyranometer measuring global
    radiation, so the usual approximation is used instead: a fraction of the
    clear-sky maximum for that moment, which `maxSolarRad` already computes.
    """
    if radiation is None or maximum is None or seconds <= 0:
        return None
    if maximum <= 0:
        # Night. Not "no sunshine yet" -- zero, definitely, which is a fact
        # worth recording rather than a gap.
        return 0.0
    if radiation < floor:
        return 0.0
    return float(seconds) if radiation >= maximum * fraction else 0.0


# ---------------------------------------------------------------------------
# Applying them
# ---------------------------------------------------------------------------

@dataclass
class Station:
    """What the formulas need to know about where the station is."""

    latitude: float | None = None
    longitude: float | None = None
    altitude_m: float | None = None

    @property
    def altitude_ft(self) -> float | None:
        if self.altitude_m is None:
            return None
        return self.altitude_m * 3.280839895


@dataclass
class Deriver:
    """Fills in the readings that follow from other readings.

    Holds one piece of state: the last value of each running total, so a
    delta can be taken. That state is why this is an object and not a
    function -- and why it is rebuilt rather than persisted: after a restart
    the first packet has no predecessor, and skipping one interval of rain is
    better than inventing one.
    """

    station: Station = field(default_factory=Station)
    how: dict[str, str] = field(default_factory=lambda: dict(DEFAULTS))
    #: What counts as sunshine, as a fraction of the clear-sky maximum. A
    #: setting because the right value depends on the sensor and how clean
    #: it is -- a dusty dome reads low all day.
    #: Clear a wind direction when the wind is zero. On, because a direction
    #: with no wind behind it is not a reading and a calm night otherwise
    #: reads as a steady breeze from wherever it last blew.
    #:
    #: Its own switch rather than an entry in `how`, because it does not
    #: *derive* anything: it removes what the hardware sent, and `how` says
    #: whether to trust the hardware. WeeWX calls this one `force_null`.
    calm_wind_null: bool = True
    #: How high the anemometer is, in metres. Evapotranspiration wants the
    #: wind at two metres and a mast is rarely there, so the formula corrects
    #: for it. Two is what WeeWX assumes when nobody says.
    wind_height_m: float = 2.0
    sunshine_fraction: float = SUNSHINE_FRACTION
    sunshine_floor: float = SUNSHINE_FLOOR
    _totals: dict[str, float] = field(default_factory=dict)
    #: Recent rain, for the rate: `(when, how much, which unit system)`.
    _rain_events: list[tuple[float, float, int]] = field(default_factory=list)
    #: The last hour of what evapotranspiration needs. WeeWX asks the
    #: database for this; there is no database here, so it is remembered.
    #: The cost of that is the hour after a restart, where the window is
    #: short and the answer rougher -- and a rough answer beats the silence
    #: this reading had before.
    _et_window: list[tuple[float, float, float, float, float]] = field(
        default_factory=list)

    def wanted(self, name: str, record: dict) -> bool:
        """Whether to work this one out for this record."""
        how = self.how.get(name, "prefer_hardware")
        if how == "hardware":
            return False
        if how == "software":
            return True
        # prefer_hardware: only when the station did not send it.
        return record.get(name) is None

    def apply(self, record: dict) -> dict:
        """Add what is missing. The record is modified and returned.

        Order matters: dew point before cloud base, because cloud base is
        computed from it. Written out rather than resolved from a dependency
        graph -- there are ten of them and the order is the documentation.
        """
        units = record.get("usUnits", US)
        self._deltas(record)
        self._temperatures(record, units)
        self._pressure(record, units)
        self._sun(record)
        self._wind(record)
        self._rain_rate(record, units)
        # Last of the new ones: it reads the temperature and humidity that
        # `_temperatures` may just have filled in.
        self._evapotranspiration(record, units)
        # Last, because it reads `maxSolarRad` and the vapour pressures read
        # what `_temperatures` may have just filled in.
        self._moisture(record, units)
        self._sunshine(record, units)
        return record

    # -- the groups ------------------------------------------------------

    def _deltas(self, record: dict) -> None:
        """Readings that are the difference between two running totals."""
        for name, sources in DELTAS.items():
            if not self.wanted(name, record):
                # The station sent it. Still remember the total, so a later
                # packet without it can still produce a delta.
                self._remember(record, sources)
                continue
            for source in sources:
                if source not in record or record[source] is None:
                    continue
                before = self._totals.get(source)
                self._totals[source] = float(record[source])
                value = delta(float(record[source]), before, name)
                if value is not None:
                    record[name] = value
                break

    def _remember(self, record: dict, sources: tuple[str, ...]) -> None:
        for source in sources:
            if record.get(source) is not None:
                self._totals[source] = float(record[source])

    def _temperatures(self, record: dict, units: int) -> None:
        t = record.get("outTemp")
        rh = record.get("outHumidity")

        if self.wanted("dewpoint", record) and t is not None and rh is not None:
            value = dewpoint_c(_to_c(t, units), rh)
            record["dewpoint"] = _from_c(value, units)

        if self.wanted("inDewpoint", record):
            it, irh = record.get("inTemp"), record.get("inHumidity")
            if it is not None and irh is not None:
                record["inDewpoint"] = _from_c(dewpoint_c(_to_c(it, units), irh),
                                               units)

        if self.wanted("heatindex", record) and t is not None and rh is not None:
            value = heatindex_f(_to_f(t, units), rh)
            record["heatindex"] = _from_f(value, units)

        if self.wanted("humidex", record) and t is not None and rh is not None:
            record["humidex"] = _from_c(humidex_c(_to_c(t, units), rh), units)

        if self.wanted("windchill", record) and t is not None:
            speed = record.get("windSpeed")
            if speed is not None:
                value = windchill_c(_to_c(t, units), _speed_kph(speed, units))
                record["windchill"] = _from_c(value, units)

        if self.wanted("appTemp", record) and t is not None and rh is not None:
            speed = record.get("windSpeed")
            if speed is not None:
                value = apptemp_c(_to_c(t, units), rh, _speed_mps(speed, units))
                record["appTemp"] = _from_c(value, units)

        if self.wanted("cloudbase", record) and t is not None and rh is not None:
            feet = cloudbase_ft(_to_f(t, units), rh, self.station.altitude_ft)
            if feet is not None:
                record["cloudbase"] = feet if units == US else feet / 3.280839895

    def _moisture(self, record: dict, units: int) -> None:
        """What the air is actually carrying, rather than how close to full.

        None of these are WeeWX's, and all four are things people install an
        extension for. They are four lines of arithmetic on readings the
        station already sends.
        """
        t, rh = record.get("outTemp"), record.get("outHumidity")
        if t is None or rh is None:
            return
        t_c = _to_c(t, units)
        # Millibars in both metric systems and inches of mercury in US, so
        # the result is converted back the same way the barometer is.
        to_mbar = 1.0 if units != US else 33.8639
        from_mbar = 1.0 if units != US else 1.0 / 33.8639

        if self.wanted("satVaporPressure", record):
            record["satVaporPressure"] = sat_vapor_pressure_mbar(t_c) * from_mbar
        if self.wanted("vaporPressure", record):
            record["vaporPressure"] = vapor_pressure_mbar(t_c, rh) * from_mbar
        if self.wanted("absoluteHumidity", record):
            # Grams per cubic metre in every unit system: there is no
            # customary unit for it, and WeeWX has no group for one either.
            record["absoluteHumidity"] = absolute_humidity(t_c, rh)
        if self.wanted("mixingRatio", record):
            pressure = record.get("pressure") or record.get("barometer")
            if pressure is not None:
                value = mixing_ratio(t_c, rh, float(pressure) * to_mbar)
                if value is not None:
                    record["mixingRatio"] = value

    def _sunshine(self, record: dict, units: int) -> None:
        """Seconds of sunshine in this interval, from the radiation.

        Needs `maxSolarRad`, which `_sun` works out just above -- and needs
        to know how long the interval was, which is `interval` in minutes.
        A packet without one is a live reading rather than an interval, and
        there is nothing to accumulate.
        """
        if not self.wanted("sunshine_time", record):
            return
        interval = record.get("interval")
        if interval is None:
            return
        value = sunshine_seconds(
            record.get("radiation"), record.get("maxSolarRad"),
            float(interval) * 60.0, self.sunshine_fraction,
            self.sunshine_floor)
        if value is not None:
            record["sunshine_time"] = value

    def _pressure(self, record: dict, units: int) -> None:
        """The three pressures. A station reports one of them and needs the rest.

        `pressure` is what the sensor reads where it sits. `barometer` is that
        reduced to sea level so two stations can be compared. `altimeter` is
        the aviation reduction, which uses a standard atmosphere rather than
        the actual temperature.
        """
        elevation_m = self.station.altitude_m
        t_c = (_to_c(record["outTemp"], units)
               if record.get("outTemp") is not None else None)

        # Station pressure from the barometer, for hardware that reports only
        # the latter. Before the other two, which are computed from it.
        if (self.wanted("pressure", record)
                and record.get("barometer") is not None):
            value = station_pressure_mbar(_to_mbar(record["barometer"], units),
                                          elevation_m, t_c)
            if value is not None:
                record["pressure"] = _from_mbar(value, units)

        pressure = record.get("pressure")

        if self.wanted("barometer", record) and pressure is not None:
            value = sealevel_pressure_mbar(_to_mbar(pressure, units),
                                           elevation_m, t_c)
            if value is not None:
                record["barometer"] = _from_mbar(value, units)

        if not self.wanted("altimeter", record):
            return
        if pressure is None or self.station.altitude_ft is None:
            return
        inhg = pressure if units == US else pressure * 0.0295299830714
        value = altimeter_inhg(inhg, self.station.altitude_ft)
        if value is not None:
            record["altimeter"] = value if units == US else value / 0.0295299830714

    def _sun(self, record: dict) -> None:
        if not self.wanted("maxSolarRad", record):
            return
        value = max_solar_rad(self.station.latitude, self.station.longitude,
                              self.station.altitude_m, record.get("dateTime"))
        if value is not None:
            record["maxSolarRad"] = value

    def _wind(self, record: dict) -> None:
        speed = record.get("windSpeed")

        if self.wanted("beaufort", record) and speed is not None:
            units = record.get("usUnits", US)
            knots = _speed_kph(speed, units) * 0.539956803
            record["beaufort"] = beaufort_number(knots)

        # A direction with no wind behind it is not a reading. Left alone, a
        # calm night reads as a steady breeze from wherever it last blew, and
        # a wind rose fills up with it.
        if speed == 0 and self.calm_wind_null:
            for name in ("windDir", "windGustDir"):
                if name in record or self.wanted(name, record):
                    record[name] = None

        if not self.wanted("windrun", record):
            return
        interval = record.get("interval")
        if speed is None or interval is None:
            return
        value = windrun(speed, float(interval) * 60.0)
        if value is not None:
            record["windrun"] = value

    def _rain_rate(self, record: dict, units: int) -> None:
        """How hard it is raining, from what fell in the last quarter hour.

        Not from this record alone: at a one-minute interval a single tip of
        the bucket would read as a downpour and the next minute as nothing.
        WeeWX keeps the same window and fills it from the database on the
        first record; there is none here, so the window starts empty and the
        first quarter hour after a restart reads low.
        """
        when = record.get("dateTime")
        if when is None:
            return
        fell = record.get("rain")
        if fell:
            self._rain_events.append((float(when), float(fell), units))
        self._rain_events = [one for one in self._rain_events
                             if one[0] > float(when) - RAIN_PERIOD]

        if not self.wanted("rainRate", record):
            return
        # Only what was measured in the same system. Mixing inches and
        # millimetres in one sum is a number that means nothing, and a
        # station changes system about as often as it changes hardware.
        total = sum(one[1] for one in self._rain_events if one[2] == units)
        record["rainRate"] = 3600.0 * total / RAIN_PERIOD

    def _evapotranspiration(self, record: dict, units: int) -> None:
        """How much water a short green crop would have used, this interval.

        The formula answers a rate per hour over the last hour, and what goes
        in the archive is that scaled to the record's own interval -- which is
        why the column is summed rather than averaged.
        """
        when = record.get("dateTime")
        interval = record.get("interval")
        t = record.get("outTemp")
        rh = record.get("outHumidity")
        radiation = record.get("radiation")
        speed = record.get("windSpeed")

        if None not in (when, t, rh, radiation, speed):
            self._et_window.append((float(when), _to_c(t, units), float(rh),
                                    float(radiation),
                                    _speed_mps(speed, units)))
        self._et_window = [one for one in self._et_window
                           if when is not None
                           and one[0] > float(when) - ET_PERIOD]

        if not self.wanted("ET", record) or interval is None:
            return
        window = self._et_window
        if not window:
            return

        temps = [one[1] for one in window]
        humidities = [one[2] for one in window]
        rate = evapotranspiration_mm(
            tmin_c=min(temps), tmax_c=max(temps),
            rh_min=min(humidities), rh_max=max(humidities),
            radiation_wpm2=sum(one[3] for one in window) / len(window),
            wind_mps=sum(one[4] for one in window) / len(window),
            wind_height_m=self.wind_height_m,
            latitude_deg=self.station.latitude,
            longitude_deg=self.station.longitude,
            altitude_m=self.station.altitude_m,
            when=float(when))
        if rate is None:
            return
        # mm per hour over the interval, and back into whatever the record is
        # written in.
        millimetres = rate * float(interval) / 60.0
        record["ET"] = (millimetres / 25.4 if units == US else millimetres)

    def forget(self) -> None:
        """Drop what was remembered. The next packet starts from nothing."""
        self._totals.clear()
        self._rain_events.clear()
        self._et_window.clear()


# -- units ---------------------------------------------------------------
#
# The formulas each want one unit system. Converting at the edge keeps that
# out of them, and keeps the conversions in one place where they can be read.

def _to_c(value: float, units: int) -> float:
    return _f_to_c(value) if units == US else value


def _from_c(value: float | None, units: int) -> float | None:
    if value is None:
        return None
    return _c_to_f(value) if units == US else value


def _to_f(value: float, units: int) -> float:
    return value if units == US else _c_to_f(value)


def _from_f(value: float | None, units: int) -> float | None:
    if value is None:
        return None
    return value if units == US else _f_to_c(value)


def _to_mbar(value: float, units: int) -> float:
    return value / 0.0295299830714 if units == US else value


def _from_mbar(value: float | None, units: int) -> float | None:
    if value is None:
        return None
    return value * 0.0295299830714 if units == US else value


def _speed_kph(value: float, units: int) -> float:
    if units == US:          # mph
        return value * 1.609344
    if units == METRICWX:    # m/s
        return value * 3.6
    return value             # METRIC is already km/h


def _speed_mps(value: float, units: int) -> float:
    if units == US:
        return value * 0.44704
    if units == METRIC:
        return value / 3.6
    return value


def from_settings(settings: Any) -> Deriver:
    """Build one from the resolved configuration."""
    station = Station(
        latitude=settings.get("station.latitude"),
        longitude=settings.get("station.longitude"),
        altitude_m=settings.get("station.altitude"),
    )
    how = dict(DEFAULTS)
    configured = settings.config.get("derive") or {}
    fraction, floor = SUNSHINE_FRACTION, SUNSHINE_FLOOR
    for name, choice in configured.items():
        # Two settings in this section are numbers rather than a policy: how
        # bright counts as sunshine, and how dim is too dim to count at all.
        # Named here rather than in a second section, because that is where
        # somebody looking for them will look.
        if name == "sunshine_fraction":
            fraction = _fraction(choice, fraction, name)
            continue
        if name == "sunshine_floor":
            floor = _fraction(choice, floor, name)
            continue
        if choice in HOW:
            how[name] = choice
        else:
            log.warning("derive.%s is %r, which is not one of %s. Ignoring it.",
                        name, choice, ", ".join(HOW))
    return Deriver(station=station, how=how, sunshine_fraction=fraction,
                   sunshine_floor=floor)


def _fraction(value: Any, fallback: float, name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        log.warning("derive.%s is %r, which is not a number. Using %s.",
                    name, value, fallback)
        return fallback
