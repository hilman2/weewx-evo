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
    "heatindex": "prefer_hardware",
    "humidex": "prefer_hardware",
    "inDewpoint": "prefer_hardware",
    "maxSolarRad": "prefer_hardware",
    "rainRate": "prefer_hardware",
    "windchill": "prefer_hardware",
    "windrun": "prefer_hardware",
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
    sunshine_fraction: float = SUNSHINE_FRACTION
    sunshine_floor: float = SUNSHINE_FLOOR
    _totals: dict[str, float] = field(default_factory=dict)

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
        if not self.wanted("altimeter", record):
            return
        pressure = record.get("pressure")
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
        if not self.wanted("windrun", record):
            return
        speed = record.get("windSpeed")
        interval = record.get("interval")
        if speed is None or interval is None:
            return
        value = windrun(speed, float(interval) * 60.0)
        if value is not None:
            record["windrun"] = value

    def forget(self) -> None:
        """Drop the running totals. The next packet takes no delta."""
        self._totals.clear()


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
