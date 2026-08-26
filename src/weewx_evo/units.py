"""Units: which one a reading is in, and what to call it.

The database holds one unit system per record and says which in `usUnits`.
Everything else -- what group a reading belongs to, what unit that group uses
in each system, how to convert between units, what to print after the number
-- is knowledge, not data, and this is where it lives.

A station in Germany measuring in Fahrenheit because that is what the console
sends, and publishing a site in Celsius, is the ordinary case rather than the
exotic one. So the archive is left exactly as the station wrote it and the
conversion happens on the way out, in a feed.

Three tables and a rule:

    GROUPS      outTemp -> group_temperature
    SYSTEMS     (group_temperature, US) -> degree_F
    CONVERT     degree_F -> degree_C

The numbers are transcribed from `weewx.units`, expression by expression, not
recalculated. A conversion factor rewritten "more cleanly" is a chart that
disagrees with the same chart drawn by WeeWX in the third decimal, and finding
out why costs an afternoon. `tools/unittest.py` checks every one of them
against WeeWX itself.

Drivers extend `GROUPS`: a driver knows what its own fields mean and the core
does not. See `unit_groups()` on the Ecowitt driver.
"""

from __future__ import annotations

import math
from typing import Any, Callable

#: Written into every archive record's `usUnits` column, stable since WeeWX 3.
#: Not ours to change.
US = 1
METRIC = 16
METRICWX = 17

NAMES = {US: "US", METRIC: "METRIC", METRICWX: "METRICWX"}

#: What the three of them mean, for anyone choosing in a form. METRICWX is the
#: one most people want and the name gives no hint of it.
DESCRIPTIONS = {
    US: "US -- Fahrenheit, inches, miles per hour",
    METRIC: "METRIC -- Celsius, centimetres, kilometres per hour",
    METRICWX: "METRICWX -- Celsius, millimetres, metres per second",
}


def name(unit_system: int) -> str:
    return NAMES.get(unit_system, f"unknown({unit_system})")


def system_from(value: Any, default: int = US) -> int:
    """A unit system from whatever a configuration file offered.

    Accepts the number or the name, because both appear in the wild:
    `usUnits = 1` in a record, `US` in a config file.
    """
    if isinstance(value, str):
        text = value.strip().upper()
        for number, label in NAMES.items():
            if text == label:
                return number
        if text.isdigit():
            value = int(text)
    if isinstance(value, int) and value in NAMES:
        return value
    return default


# -- the constants the conversions are written in terms of -----------------
# Transcribed from weewx.units. INHG_PER_MBAR is not 1/33.8639 to the last
# digit and METER_PER_FOOT comes from a mile being 1609.34 metres rather than
# 1609.344; both are WeeWX's, and a value converted twice has to come back.

INHG_PER_MBAR = 0.0295299875
MM_PER_INCH = 25.4
CM_PER_INCH = MM_PER_INCH / 10.0
METER_PER_MILE = 1609.34
METER_PER_FOOT = METER_PER_MILE / 5280.0
MILE_PER_KM = 1000.0 / METER_PER_MILE
SECS_PER_DAY = 86400


def CtoK(x: float) -> float:  # noqa: N802
    return x + 273.15


def KtoC(x: float) -> float:  # noqa: N802
    return x - 273.15


def CtoF(x: float) -> float:  # noqa: N802
    return x * 1.8 + 32.0


def FtoC(x: float) -> float:  # noqa: N802
    return (x - 32.0) / 1.8


def KtoF(x: float) -> float:  # noqa: N802
    return CtoF(KtoC(x))


def FtoK(x: float) -> float:  # noqa: N802
    return CtoK(FtoC(x))


# Felsius. A joke unit that WeeWX supports in earnest, so it is here too:
# somebody's skin uses it and their charts should not break.
def FtoE(x: float) -> float:  # noqa: N802
    return (7.0 * x - 80.0) / 9.0


def EtoF(x: float) -> float:  # noqa: N802
    return (9.0 * x + 80.0) / 7.0


def CtoE(x: float) -> float:  # noqa: N802
    return (7.0 / 5.0) * x + 16.0


def EtoC(x: float) -> float:  # noqa: N802
    return (x - 16.0) * 5.0 / 7.0


def mps_to_mph(x: float) -> float:
    return x * 3600.0 / METER_PER_MILE


def kph_to_mph(x: float) -> float:
    return x * 1000.0 / METER_PER_MILE


def mps_to_knot(x: float) -> float:
    return x * 1.94384449


def kph_to_knot(x: float) -> float:
    return x * 0.539956803


def mph_to_knot(x: float) -> float:
    # Rounded factors rather than "/ 1852.0", because that is what WeeWX has.
    # They make the table not quite self-inverse: mph -> knot -> mph comes back
    # two parts in a million out. Correcting it would put every wind figure a
    # hair away from the one WeeWX prints for the same reading, which is worse
    # than the drift. `tools/unitcheck.py` holds our round trip against theirs.
    return x * 0.868976242


def dublin_to_epoch(x: float) -> float:
    return (x - 25567.5) * SECS_PER_DAY


def epoch_to_dublin(x: float) -> float:
    return x / SECS_PER_DAY + 25567.5


#: How to get from one unit to another. Transcribed from weewx.units, one
#: expression at a time. Anything not in here cannot be converted, and asking
#: for it is an error rather than a silently unchanged number.
CONVERT: dict[str, dict[str, Callable[[float], float]]] = {
    "astronomical_unit": {"meter": lambda x: x * 149597870700,
                          "km": lambda x: x * 149597870.7,
                          "mile": lambda x: x * 92955807.23752087},
    "bit": {"byte": lambda x: x / 8},
    "byte": {"bit": lambda x: x * 8},
    "cm": {"inch": lambda x: x / CM_PER_INCH,
           "mm": lambda x: x * 10.0},
    "cm_per_hour": {"inch_per_hour": lambda x: x * 0.393700787,
                    "mm_per_hour": lambda x: x * 10.0},
    "cubic_foot": {"gallon": lambda x: x * 7.48052,
                   "litre": lambda x: x * 28.3168,
                   "liter": lambda x: x * 28.3168},
    "day": {"second": lambda x: x * SECS_PER_DAY,
            "minute": lambda x: x*1440.0,
            "hour": lambda x: x*24.0},
    "degree_angle": {"radian": math.radians},
                     "degree_C": {"degree_F": CtoF,
                     "degree_E": CtoE,
                     "degree_K": CtoK},
                     "degree_C_day": {"degree_F_day": lambda x: x * (9.0/5.0)},
                     "degree_E": {"degree_C": EtoC,
                     "degree_F": EtoF},
                     "degree_F": {"degree_C": FtoC,
                     "degree_E": FtoE,
                     "degree_K": FtoK},
                     "degree_F_day": {"degree_C_day": lambda x: x * (5.0/9.0)},
                     "degree_K": {"degree_C": KtoC,
                     "degree_F": KtoF},
    "dublin_jd": {"unix_epoch": dublin_to_epoch,
                  "unix_epoch_ms": lambda x: dublin_to_epoch(x) * 1000,
                  "unix_epoch_ns": lambda x: dublin_to_epoch(x) * 1e06},
    "foot": {"meter": lambda x: x * METER_PER_FOOT},
    "gallon": {"liter": lambda x: x * 3.78541,
               "litre": lambda x: x * 3.78541,
               "cubic_foot": lambda x: x * 0.133681},
    "hour": {"second": lambda x: x*3600.0,
             "minute": lambda x: x*60.0,
             "day": lambda x: x/24.0},
             "hPa": {"inHg": lambda x: x * INHG_PER_MBAR,
             "mmHg": lambda x: x * 0.75006168,
             "mbar": lambda x: x,
             "kPa": lambda x: x / 10.0},
             "hPa_per_hour": {"inHg_per_hour": lambda x: x * INHG_PER_MBAR,
             "mmHg_per_hour": lambda x: x * 0.75006168,
             "mbar_per_hour": lambda x: x,
             "kPa_per_hour": lambda x: x / 10.0},
    "inch": {"cm": lambda x: x * CM_PER_INCH,
             "mm": lambda x: x * MM_PER_INCH},
    "inch_per_hour": {"cm_per_hour": lambda x: x * 2.54,
                      "mm_per_hour": lambda x: x * 25.4},
                      "inHg": {"mbar": lambda x: x / INHG_PER_MBAR,
                      "hPa": lambda x: x / INHG_PER_MBAR,
                      "kPa": lambda x: x / INHG_PER_MBAR / 10.0,
                      "mmHg": lambda x: x * 25.4},
                      "inHg_per_hour": {"mbar_per_hour": lambda x: x / INHG_PER_MBAR,
                      "hPa_per_hour": lambda x: x / INHG_PER_MBAR,
                      "kPa_per_hour": lambda x: x / INHG_PER_MBAR / 10.0,
                      "mmHg_per_hour": lambda x: x * 25.4},
    "kilowatt": {"watt": lambda x: x * 1000.0},
    "kilowatt_hour": {"mega_joule": lambda x: x * 3.6,
                      "watt_second": lambda x: x * 3.6e6,
                      "watt_hour": lambda x: x * 1000.0},
    "km": {"meter": lambda x: x * 1000.0,
           "mile": lambda x: x * 0.621371192,
           "astronomical_unit": lambda x: x / 149597870.7 },
    "km_per_hour": {"mile_per_hour": kph_to_mph,
                    "knot": kph_to_knot,
                    "meter_per_second": lambda x: x * 0.277777778},
    "knot": {"mile_per_hour": lambda x: x * 1.15077945,
             "km_per_hour": lambda x: x * 1.85200,
             "meter_per_second": lambda x: x * 0.514444444},
    "knot2": {"mile_per_hour2": lambda x: x * 1.15077945,
              "km_per_hour2": lambda x: x * 1.85200,
              "meter_per_second2": lambda x: x * 0.514444444},
              "kPa": {"inHg": lambda x: x * INHG_PER_MBAR * 10.0,
              "mmHg": lambda x: x * 7.5006168,
              "mbar": lambda x: x * 10.0,
              "hPa": lambda x: x * 10.0},
              "kPa_per_hour": {"inHg_per_hour": lambda x: x * INHG_PER_MBAR * 10.0,
              "mmHg_per_hour": lambda x: x * 7.5006168,
              "mbar_per_hour": lambda x: x * 10.0,
              "hPa_per_hour": lambda x: x * 10.0},
    "liter": {"gallon": lambda x: x * 0.264172,
              "cubic_foot": lambda x: x * 0.0353147},
    "mbar": {"inHg": lambda x: x * INHG_PER_MBAR,
             "mmHg": lambda x: x * 0.75006168,
             "hPa": lambda x: x,
             "kPa": lambda x: x / 10.0},
    "mbar_per_hour": {"inHg_per_hour": lambda x: x * INHG_PER_MBAR,
                      "mmHg_per_hour": lambda x: x * 0.75006168,
                      "hPa_per_hour": lambda x: x,
                      "kPa_per_hour": lambda x: x / 10.0},
    "mega_joule": {"kilowatt_hour": lambda x: x / 3.6,
                   "watt_hour": lambda x: x * 1000000 / 3600,
                   "watt_second": lambda x: x * 1000000},
    "meter": {"foot": lambda x: x / METER_PER_FOOT,
              "km": lambda x: x / 1000.0,
              "astronomical_unit": lambda x: x / 149597870700},
    "meter_per_second": {"mile_per_hour": mps_to_mph,
                         "knot": mps_to_knot,
                         "km_per_hour": lambda x: x * 3.6},
    "meter_per_second2": {"mile_per_hour2": lambda x: x * 2.23693629,
                          "knot2": lambda x: x * 1.94384449,
                          "km_per_hour2": lambda x: x * 3.6},
    "mile": {"km": lambda x: x * 1.609344,
             "astronomical_unit": lambda x: x / 92955807.23752087},
    "mile_per_hour": {"km_per_hour": lambda x: x * 1.609344,
                      "knot": mph_to_knot,
                      "meter_per_second": lambda x: x * 0.44704},
    "mile_per_hour2": {"km_per_hour2": lambda x: x * 1.609344,
                       "knot2": lambda x: x * 0.868976242,
                       "meter_per_second2": lambda x: x * 0.44704},
    "minute": {"second": lambda x: x * 60.0,
               "hour": lambda x: x / 60.0,
               "day": lambda x: x / 1440.0},
    "mm": {"inch": lambda x: x / MM_PER_INCH,
           "cm": lambda x: x * 0.10},
    "mm_per_hour": {"inch_per_hour": lambda x: x * .0393700787,
                    "cm_per_hour": lambda x: x * 0.10},
                    "mmHg": {"inHg": lambda x: x / MM_PER_INCH,
                    "mbar": lambda x: x / 0.75006168,
                    "hPa": lambda x: x / 0.75006168,
                    "kPa": lambda x: x / 7.5006168},
                    "mmHg_per_hour": {"inHg_per_hour": lambda x: x / MM_PER_INCH,
                    "mbar_per_hour": lambda x: x / 0.75006168,
                    "hPa_per_hour": lambda x: x / 0.75006168,
                    "kPa_per_hour": lambda x: x / 7.5006168},
    "radian": {"degree_angle": math.degrees},
    "second": {"hour": lambda x: x/3600.0,
               "minute": lambda x: x/60.0,
               "day": lambda x: x / SECS_PER_DAY},
    "unix_epoch": {"dublin_jd": epoch_to_dublin,
                   "unix_epoch_ms": lambda x: x * 1000,
                   "unix_epoch_ns": lambda x: x * 1000000},
    "unix_epoch_ms": {"dublin_jd": lambda x: epoch_to_dublin(x / 1000.0),
                      "unix_epoch": lambda x: x / 1000,
                      "unix_epoch_ns": lambda x: x * 1000},
    "unix_epoch_ns": {"dublin_jd": lambda x: epoch_to_dublin(x / 1e6),
                      "unix_epoch": lambda x: x / 1e06,
                      "unix_epoch_ms": lambda x: x / 1000},
    "watt": {"kilowatt": lambda x: x / 1000.0},
    "watt_hour": {"kilowatt_hour": lambda x: x / 1000.0,
                  "mega_joule": lambda x: x * 0.0036,
                  "watt_second": lambda x: x * 3600.0},
    "watt_second": {"kilowatt_hour": lambda x: x / 3.6e6,
                    "mega_joule": lambda x: x / 1000000,
                    "watt_hour": lambda x: x / 3600.0}
}


#: What a reading is called, in words, when nothing else says. WeeWX's
#: `[Labels] [[Generic]]` defaults, transcribed.
#:
#: A skin brings its own and they win -- these are for everything that has
#: no skin behind it, which is every chart drawn on its own. Without them a
#: chart has no heading at all, and a page of thirty unlabelled charts is a
#: page nobody can read.
OBS_LABELS: dict[str, str] = {
    "barometer": "Barometer",
    "barometerRate": "Barometer Change Rate",
    "pressure": "Pressure",
    "altimeter": "Altimeter",
    "dewpoint": "Dew Point",
    "ET": "ET",
    "heatindex": "Heat Index",
    "appTemp": "Apparent Temperature",
    "humidex": "Humidex",
    "inHumidity": "Inside Humidity",
    "inTemp": "Inside Temperature",
    "inDewpoint": "Inside Dew Point",
    "outHumidity": "Outside Humidity",
    "outTemp": "Outside Temperature",
    "radiation": "Radiation",
    "maxSolarRad": "Clear Sky Radiation",
    "rain": "Rain",
    "rainRate": "Rain Rate",
    "hail": "Hail",
    "hailRate": "Hail Rate",
    "snow": "Snow",
    "snowRate": "Snow Rate",
    "snowDepth": "Snow Depth",
    "UV": "UV Index",
    "wind": "Wind",
    "windDir": "Wind Direction",
    "windGust": "Gust Speed",
    "windGustDir": "Gust Direction",
    "windSpeed": "Wind Speed",
    "windchill": "Wind Chill",
    "windgustvec": "Gust Vector",
    "windvec": "Wind Vector",
    "windrun": "Wind Run",
    "cloudbase": "Cloud Base",
    "heatdeg": "Heating Degree Days",
    "cooldeg": "Cooling Degree Days",
    "growdeg": "Growing Degree Days",
    "lightning_distance": "Lightning Distance",
    "lightning_strike_count": "Lightning Strikes",
    "rxCheckPercent": "Signal Quality",
    "txBatteryStatus": "Transmitter Battery",
    "windBatteryStatus": "Wind Battery",
    "rainBatteryStatus": "Rain Battery",
    "outTempBatteryStatus": "Outside Temperature Battery",
    "inTempBatteryStatus": "Inside Temperature Battery",
    "consBatteryVoltage": "Console Battery",
    "heatingVoltage": "Heating Battery",
    "supplyVoltage": "Supply Voltage",
    "referenceVoltage": "Reference Voltage",
    "pm1_0": "PM1.0", "pm2_5": "PM2.5", "pm10_0": "PM10",
    "co": "CO", "co2": "CO2", "nh3": "NH3", "no2": "NO2",
    "o3": "O3", "so2": "SO2",
}

#: Readings that come in numbered families. Spelling out forty of each in
#: the table above would be forty chances to mistype one.
NUMBERED = {
    "extraTemp": "Temperature", "extraHumid": "Humidity",
    "leafTemp": "Leaf Temperature", "leafWet": "Leaf Wetness",
    "soilTemp": "Soil Temperature", "soilMoist": "Soil Moisture",
    "batteryStatus": "Battery", "signal": "Signal",
}


def obs_label(obs_type: str) -> str:
    """What to call a reading on a chart, when nothing else says.

    A skin's own name wins wherever there is one. This is the fallback, and
    it is better than the column name: "Outside Temperature" over "outTemp",
    and "Soil Moisture 3" over "soilMoist3".
    """
    name = str(obs_type or "")
    if name in OBS_LABELS:
        return OBS_LABELS[name]
    stem = name.rstrip("0123456789")
    number = name[len(stem):]
    if number and stem in NUMBERED:
        return f"{NUMBERED[stem]} {number}"
    if not name:
        return ""
    # Something nobody has named. Split the camel case and the
    # underscores, which turns `soilTempSensor` into something readable
    # rather than leaving it raw.
    said = ""
    for i, char in enumerate(name):
        if char == "_":
            said += " "
        elif char.isupper() and i and name[i - 1].islower():
            said += " " + char
        else:
            said += char
    said = " ".join(said.split())
    return said[:1].upper() + said[1:] if said else name


#: Which group each reading belongs to. WeeWX's `obs_group_dict`. A driver
#: adds its own on top; this is what the core knows without one.
GROUPS: dict[str, str] = {
    "ET": "group_rain",
    "THSW": "group_temperature",
    "UV": "group_uv",
    "altimeter": "group_pressure",
    "altimeterRate": "group_pressurerate",
    "altitude": "group_altitude",
    "appTemp": "group_temperature",
    "appTemp1": "group_temperature",
    "barometer": "group_pressure",
    "barometerRate": "group_pressurerate",
    "beaufort": "group_count",
    "cloudbase": "group_altitude",
    "cloudcover": "group_percent",
    "co": "group_fraction",
    "co2": "group_fraction",
    "consBatteryVoltage": "group_volt",
    "cooldeg": "group_degree_day",
    "dateTime": "group_time",
    "dayRain": "group_rain",
    "daySunshineDur": "group_deltatime",
    "dewpoint": "group_temperature",
    "dewpoint1": "group_temperature",
    "extraHumid1": "group_percent",
    "extraHumid2": "group_percent",
    "extraHumid3": "group_percent",
    "extraHumid4": "group_percent",
    "extraHumid5": "group_percent",
    "extraHumid6": "group_percent",
    "extraHumid7": "group_percent",
    "extraHumid8": "group_percent",
    "extraTemp1": "group_temperature",
    "extraTemp2": "group_temperature",
    "extraTemp3": "group_temperature",
    "extraTemp4": "group_temperature",
    "extraTemp5": "group_temperature",
    "extraTemp6": "group_temperature",
    "extraTemp7": "group_temperature",
    "extraTemp8": "group_temperature",
    "growdeg": "group_degree_day",
    "gustdir": "group_direction",
    "hail": "group_rain",
    "hailRate": "group_rainrate",
    "heatdeg": "group_degree_day",
    "heatindex": "group_temperature",
    "heatindex1": "group_temperature",
    "heatingTemp": "group_temperature",
    "heatingVoltage": "group_volt",
    "highOutTemp": "group_temperature",
    "hourRain": "group_rain",
    "humidex": "group_temperature",
    "humidex1": "group_temperature",
    "illuminance": "group_illuminance",
    "inDewpoint": "group_temperature",
    "inHumidity": "group_percent",
    "inTemp": "group_temperature",
    "interval": "group_interval",
    "leafTemp1": "group_temperature",
    "leafTemp2": "group_temperature",
    "leafTemp3": "group_temperature",
    "leafTemp4": "group_temperature",
    "leafWet1": "group_count",
    "leafWet2": "group_count",
    "lightning_distance": "group_distance",
    "lightning_disturber_count": "group_count",
    "lightning_noise_count": "group_count",
    "lightning_strike_count": "group_count",
    "lowOutTemp": "group_temperature",
    "maxSolarRad": "group_radiation",
    "monthRain": "group_rain",
    "nh3": "group_fraction",
    "no2": "group_concentration",
    "noise": "group_db",
    "o3": "group_fraction",
    "outHumidity": "group_percent",
    "outTemp": "group_temperature",
    "outWetbulb": "group_temperature",
    "pb": "group_fraction",
    "pm10_0": "group_concentration",
    "pm1_0": "group_concentration",
    "pm2_5": "group_concentration",
    "pop": "group_percent",
    "pressure": "group_pressure",
    "pressureRate": "group_pressurerate",
    "radiation": "group_radiation",
    "rain": "group_rain",
    "rain24": "group_rain",
    "rainDur": "group_deltatime",
    "rainRate": "group_rainrate",
    "referenceVoltage": "group_volt",
    "rms": "group_speed2",
    "rxCheckPercent": "group_percent",
    "snow": "group_rain",
    "snowDepth": "group_rain",
    "snowMoisture": "group_percent",
    "snowRate": "group_rainrate",
    "so2": "group_fraction",
    "soilMoist1": "group_moisture",
    "soilMoist2": "group_moisture",
    "soilMoist3": "group_moisture",
    "soilMoist4": "group_moisture",
    "soilTemp1": "group_temperature",
    "soilTemp2": "group_temperature",
    "soilTemp3": "group_temperature",
    "soilTemp4": "group_temperature",
    "stormRain": "group_rain",
    "stormStart": "group_time",
    "sunshineDur": "group_deltatime",
    "supplyVoltage": "group_volt",
    "totalRain": "group_rain",
    "vecavg": "group_speed2",
    "vecdir": "group_direction",
    "wind": "group_speed",
    "windDir": "group_direction",
    "windDir10": "group_direction",
    "windGust": "group_speed",
    "windGustDir": "group_direction",
    "windSpeed": "group_speed",
    "windSpeed10": "group_speed",
    "windchill": "group_temperature",
    "windgustvec": "group_speed",
    "windrun": "group_distance",
    "windvec": "group_speed",
    "yearRain": "group_rain",
}

_US: dict[str, str] = {
    "group_altitude": "foot",
    "group_amp": "amp",
    "group_angle": "degree_angle",
    "group_boolean": "boolean",
    "group_concentration": "microgram_per_meter_cubed",
    "group_count": "count",
    "group_data": "byte",
    "group_db": "dB",
    "group_degree_day": "degree_F_day",
    "group_deltatime": "second",
    "group_direction": "degree_compass",
    "group_distance": "mile",
    "group_elapsed": "second",
    "group_energy": "watt_hour",
    "group_energy2": "watt_second",
    "group_fraction": "ppm",
    "group_frequency": "hertz",
    "group_illuminance": "lux",
    "group_interval": "minute",
    "group_length": "inch",
    "group_localtime": "local_djd",
    "group_moisture": "centibar",
    "group_percent": "percent",
    "group_power": "watt",
    "group_pressure": "inHg",
    "group_pressurerate": "inHg_per_hour",
    "group_radiation": "watt_per_meter_squared",
    "group_rain": "inch",
    "group_rainrate": "inch_per_hour",
    "group_speed": "mile_per_hour",
    "group_speed2": "mile_per_hour2",
    "group_temperature": "degree_F",
    "group_time": "unix_epoch",
    "group_uv": "uv_index",
    "group_volt": "volt",
    "group_volume": "gallon",
}

_METRIC: dict[str, str] = {
    "group_altitude": "meter",
    "group_amp": "amp",
    "group_angle": "degree_angle",
    "group_boolean": "boolean",
    "group_concentration": "microgram_per_meter_cubed",
    "group_count": "count",
    "group_data": "byte",
    "group_db": "dB",
    "group_degree_day": "degree_C_day",
    "group_deltatime": "second",
    "group_direction": "degree_compass",
    "group_distance": "km",
    "group_elapsed": "second",
    "group_energy": "watt_hour",
    "group_energy2": "watt_second",
    "group_fraction": "ppm",
    "group_frequency": "hertz",
    "group_illuminance": "lux",
    "group_interval": "minute",
    "group_length": "cm",
    "group_localtime": "local_djd",
    "group_moisture": "centibar",
    "group_percent": "percent",
    "group_power": "watt",
    "group_pressure": "mbar",
    "group_pressurerate": "mbar_per_hour",
    "group_radiation": "watt_per_meter_squared",
    "group_rain": "cm",
    "group_rainrate": "cm_per_hour",
    "group_speed": "km_per_hour",
    "group_speed2": "km_per_hour2",
    "group_temperature": "degree_C",
    "group_time": "unix_epoch",
    "group_uv": "uv_index",
    "group_volt": "volt",
    "group_volume": "liter",
}

_METRICWX: dict[str, str] = {
    "group_altitude": "meter",
    "group_amp": "amp",
    "group_angle": "degree_angle",
    "group_boolean": "boolean",
    "group_concentration": "microgram_per_meter_cubed",
    "group_count": "count",
    "group_data": "byte",
    "group_db": "dB",
    "group_degree_day": "degree_C_day",
    "group_deltatime": "second",
    "group_direction": "degree_compass",
    "group_distance": "km",
    "group_elapsed": "second",
    "group_energy": "watt_hour",
    "group_energy2": "watt_second",
    "group_fraction": "ppm",
    "group_frequency": "hertz",
    "group_illuminance": "lux",
    "group_interval": "minute",
    "group_length": "cm",
    "group_localtime": "local_djd",
    "group_moisture": "centibar",
    "group_percent": "percent",
    "group_power": "watt",
    "group_pressure": "mbar",
    "group_pressurerate": "mbar_per_hour",
    "group_radiation": "watt_per_meter_squared",
    "group_rain": "mm",
    "group_rainrate": "mm_per_hour",
    "group_speed": "meter_per_second",
    "group_speed2": "meter_per_second2",
    "group_temperature": "degree_C",
    "group_time": "unix_epoch",
    "group_uv": "uv_index",
    "group_volt": "volt",
    "group_volume": "liter",
}


#: The unit each group uses, per system.
SYSTEMS: dict[int, dict[str, str]] = {
    US: _US,
    METRIC: _METRIC,
    METRICWX: _METRICWX,
}

#: Some aggregates change what a value *is*. The time of today's maximum is a
#: time, not a temperature, and counting how many readings there were gives a
#: count. WeeWX's `agg_group`.
AGGREGATE_GROUPS: dict[str, str] = {
    "avg_ge": "group_count",
    "avg_le": "group_count",
    "count": "group_count",
    "firsttime": "group_time",
    "gustdir": "group_direction",
    "lasttime": "group_time",
    "max_ge": "group_count",
    "max_le": "group_count",
    "maxmintime": "group_time",
    "maxsumtime": "group_time",
    "maxtime": "group_time",
    "min_ge": "group_count",
    "min_le": "group_count",
    "minmaxtime": "group_time",
    "minsumtime": "group_time",
    "mintime": "group_time",
    "not_null": "group_boolean",
    "sum_ge": "group_count",
    "sum_le": "group_count",
    "vecdir": "group_direction",}


#: What to print after the number. WeeWX keeps these in each skin so they can
#: be translated; here they are the default and a feed may override them.
LABELS: dict[str, Any] = {
    "NONE": "",
    "amp": " A",
    "astronomical_unit": " AU",
    "bit": " b",
    "boolean": "",
    "byte": " B",
    "centibar": " cb",
    "cm": " cm",
    "cm_per_hour": " cm/h",
    "count": "",
    "cubic_foot": " ft³",
    "dB": " dB",
    "day": [" day", " days"],
    "degree_C": "°C",
    "degree_C_day": "°C-day",
    "degree_E": "°E",
    "degree_F": "°F",
    "degree_F_day": "°F-day",
    "degree_K": "°K",
    "degree_angle": "°",
    "degree_compass": "°",
    "foot": " feet",
    "gallon": " gal",
    "hPa": " hPa",
    "hPa_per_hour": " hPa/h",
    "hertz": " Hz",
    "hour": [" hour", " hours"],
    "inHg": " inHg",
    "inHg_per_hour": " inHg/h",
    "inch": " in",
    "inch_per_hour": " in/h",
    "kPa": [" kPa"],
    "kPa_per_hour": [" kPa/h"],
    "kilowatt": " kW",
    "kilowatt_hour": " kWh",
    "km": " km",
    "km_per_hour": " km/h",
    "km_per_hour2": " km/h",
    "knot": " knots",
    "knot2": " knots",
    "liter": [" l"],
    "litre": [" l"],
    "lux": [" lx"],
    "mbar": " mbar",
    "mbar_per_hour": " mbar/h",
    "mega_joule": " MJ",
    "meter": [" meter", " meters"],
    "meter_per_second": " m/s",
    "meter_per_second2": " m/s",
    "microgram_per_meter_cubed": [" µg/m³"],
    "mile": [" mile", " miles"],
    "mile_per_hour": " mph",
    "mile_per_hour2": " mph",
    "minute": [" minute", " minutes"],
    "mm": " mm",
    "mmHg": " mmHg",
    "mmHg_per_hour": " mmHg/h",
    "mm_per_hour": " mm/h",
    "percent": "%",
    "ppm": " ppm",
    "radian": " rad",
    "second": [" second", " seconds"],
    "uv_index": "",
    "volt": " V",
    "watt": " W",
    "watt_hour": " Wh",
    "watt_per_meter_squared": " W/m²",
    "watt_second": " Ws",}


#: How many decimals are worth showing. Not used for the JSON -- a machine
#: reading it wants the number -- but a feed rendering a page needs it, and it
#: belongs beside the labels rather than in the feed.
FORMATS: dict[str, str] = {
    "NONE": "   N/A",
    "amp": "%.1f",
    "astronomical_unit": "%.2f",
    "bit": "%.0f",
    "boolean": "%d",
    "byte": "%.0f",
    "centibar": "%.0f",
    "cm": "%.2f",
    "cm_per_hour": "%.2f",
    "count": "%d",
    "cubic_foot": "%.1f",
    "dB": "%.0f",
    "day": "%.1f",
    "degree_C": "%.1f",
    "degree_C_day": "%.1f",
    "degree_E": "%.1f",
    "degree_F": "%.1f",
    "degree_F_day": "%.1f",
    "degree_K": "%.1f",
    "degree_angle": "%02.0f",
    "degree_compass": "%03.0f",
    "foot": "%.0f",
    "gallon": "%.1f",
    "hPa": "%.1f",
    "hPa_per_hour": "%.3f",
    "hertz": "%.1f",
    "hour": "%.1f",
    "inHg": "%.3f",
    "inHg_per_hour": "%.5f",
    "inch": "%.2f",
    "inch_per_hour": "%.2f",
    "kPa": "%.2f",
    "kPa_per_hour": "%.4f",
    "kilowatt": "%.1f",
    "kilowatt_hour": "%.1f",
    "km": "%.1f",
    "km_per_hour": "%.0f",
    "km_per_hour2": "%.1f",
    "knot": "%.0f",
    "knot2": "%.1f",
    "liter": "%.1f",
    "litre": "%.1f",
    "lux": "%.0f",
    "mbar": "%.1f",
    "mbar_per_hour": "%.4f",
    "mega_joule": "%.0f",
    "meter": "%.0f",
    "meter_per_second": "%.1f",
    "meter_per_second2": "%.1f",
    "microgram_per_meter_cubed": "%.0f",
    "mile": "%.1f",
    "mile_per_hour": "%.0f",
    "mile_per_hour2": "%.1f",
    "minute": "%.1f",
    "mm": "%.1f",
    "mmHg": "%.1f",
    "mmHg_per_hour": "%.4f",
    "mm_per_hour": "%.1f",
    "percent": "%.0f",
    "ppm": "%.0f",
    "radian": "%.3f",
    "second": "%.0f",
    "uv_index": "%.1f",
    "volt": "%.1f",
    "watt": "%.1f",
    "watt_hour": "%.1f",
    "watt_per_meter_squared": "%.0f",
    "watt_second": "%.0f",
}


# -- asking questions of the tables ----------------------------------------


def group_of(obs_type: str, aggregate: str | None = None,
             extra: dict[str, str] | None = None) -> str | None:
    """Which group a reading belongs to, or None if nothing knows.

    `extra` is what a driver contributed. It wins over the built-in table: a
    driver knows its own fields, and the core's list is only the standard
    schema.

    Some aggregates change the answer. The *time* of today's maximum is a
    time, not a temperature, and a count of readings is a count.
    """
    if aggregate and aggregate in AGGREGATE_GROUPS:
        return AGGREGATE_GROUPS[aggregate]
    if extra and obs_type in extra:
        return extra[obs_type]
    return GROUPS.get(obs_type)


def unit_of(obs_type: str, unit_system: int, aggregate: str | None = None,
            extra: dict[str, str] | None = None) -> tuple[str | None, str | None]:
    """The unit a reading is stored in, and its group.

    This is the unit as it sits in the database -- what the record's `usUnits`
    says it is. What to *show* it in is a separate question; see `Target`.
    """
    group = group_of(obs_type, aggregate, extra)
    if group is None:
        return None, None
    return SYSTEMS.get(unit_system, _US).get(group), group


def convert(value: Any, from_unit: str | None, to_unit: str | None) -> Any:
    """One value from one unit to another.

    None stays None: a gap in the readings is not zero degrees. An unknown
    conversion raises rather than returning the number unchanged -- a
    temperature quietly labelled Celsius while holding Fahrenheit is the worst
    of the three possible outcomes.
    """
    if value is None or not from_unit or not to_unit or from_unit == to_unit:
        return value
    try:
        return CONVERT[from_unit][to_unit](value)
    except KeyError:
        raise ValueError(
            f"there is no conversion from {from_unit} to {to_unit}") from None


def convert_all(values: list, from_unit: str | None,
                to_unit: str | None) -> list:
    """A whole series, converted. The gaps stay gaps."""
    if not from_unit or not to_unit or from_unit == to_unit:
        return list(values)
    try:
        fn = CONVERT[from_unit][to_unit]
    except KeyError:
        raise ValueError(
            f"there is no conversion from {from_unit} to {to_unit}") from None
    return [None if v is None else fn(v) for v in values]


def can_convert(from_unit: str | None, to_unit: str | None) -> bool:
    """Whether that conversion exists, without doing it."""
    if not from_unit or not to_unit:
        return False
    return from_unit == to_unit or to_unit in CONVERT.get(from_unit, {})


def label(unit: str | None, plural: bool = True) -> str:
    """What to print after the number, including its leading space.

    A few units have a singular and a plural ('1 day', '2 days'). Most do not
    and the same string is returned either way.
    """
    if not unit:
        return ""
    text = LABELS.get(unit, "")
    if isinstance(text, (list, tuple)):
        return text[1 if plural and len(text) > 1 else 0]
    return text


def formatted(value: Any, unit: str | None, with_label: bool = False) -> str:
    """A value as a person would read it.

    Not used by the JSON feed -- a machine reading it wants the number -- but
    a feed writing a page needs it, and the decimals belong beside the labels
    rather than scattered through templates.
    """
    if value is None:
        return FORMATS.get("NONE", "   N/A")
    try:
        text = FORMATS.get(unit or "", "%s") % value
    except (TypeError, ValueError):
        text = str(value)
    return text + label(unit) if with_label else text


class Target:
    """What to show readings in, whatever the database holds them in.

    A console in Germany reporting Fahrenheit and a site published in Celsius
    is the ordinary case. The archive keeps what the station wrote; this is
    the other end.

        Target(METRICWX)                       everything in that system
        Target(METRICWX, {"group_pressure": "mbar"})   except pressure

    An override naming a unit the group cannot reach is refused when the
    Target is built rather than halfway through a report.
    """

    __slots__ = ("system", "overrides", "formats", "labels",
                 "time_formats", "deltatime_formats", "ordinals")

    def __init__(self, system: int | str = US,
                 overrides: dict[str, str] | None = None,
                 formats: dict[str, str] | None = None,
                 labels: dict[str, Any] | None = None,
                 time_formats: dict[str, str] | None = None,
                 deltatime_formats: dict[str, str] | None = None,
                 ordinals: tuple[str, ...] | None = None) -> None:
        self.system = system_from(system)
        self.overrides = dict(overrides or {})
        #: How many decimals, what to call a unit, and how to print a time.
        #: Empty here means the defaults below; a skin brings its own, and
        #: a page that has said "%.1f" for eight years keeps saying it.
        self.formats = dict(formats or {})
        self.labels = dict(labels or {})
        self.time_formats = dict(time_formats or {})
        self.deltatime_formats = dict(deltatime_formats or {})
        #: The sixteen points of the compass and a word for "no wind at
        #: all". A translation names its own -- N, NNO, NO in German -- and
        #: they go straight into a sentence, so they are the skin's to
        #: decide rather than ours.
        self.ordinals: tuple[str, ...] = tuple(ordinals or ())
        for group, unit in self.overrides.items():
            if group not in SYSTEMS[US]:
                raise ValueError(f"{group!r} is not a unit group")
            if not can_convert(SYSTEMS[US][group], unit) \
                    and unit != SYSTEMS[US][group]:
                raise ValueError(
                    f"{unit!r} is not a unit {group} can be shown in")

    def format_for(self, unit: str | None) -> str | None:
        """The printf format for a unit, the skin's if it named one."""
        if unit and unit in self.formats:
            return self.formats[unit]
        return FORMATS.get(unit or "")

    def label_for(self, unit: str | None, plural: bool = True) -> str:
        """What to print after the number, the skin's word if it has one."""
        if not unit:
            return ""
        if unit in self.labels:
            text = self.labels[unit]
            if isinstance(text, (list, tuple)):
                return str(text[1 if plural and len(text) > 1 else 0])
            return str(text)
        return label(unit, plural)

    def unit(self, group: str | None) -> str | None:
        """The unit this group is shown in."""
        if group is None:
            return None
        if group in self.overrides:
            return self.overrides[group]
        return SYSTEMS.get(self.system, _US).get(group)

    def for_obs(self, obs_type: str, aggregate: str | None = None,
                extra: dict[str, str] | None = None) -> tuple[str | None, str | None]:
        """The unit and group a reading should be shown in."""
        group = group_of(obs_type, aggregate, extra)
        return self.unit(group), group

    def convert(self, values: list, obs_type: str, source_system: int,
                aggregate: str | None = None,
                extra: dict[str, str] | None = None) -> tuple[list, str | None, str | None]:
        """A series out of the database and into what it should be shown in.

        Returns the values, the unit they are now in, and its group.
        """
        stored, group = unit_of(obs_type, source_system, aggregate, extra)
        wanted = self.unit(group)
        if stored is None or wanted is None:
            return list(values), stored or wanted, group
        return convert_all(values, stored, wanted), wanted, group

    def __repr__(self) -> str:
        extra = f", {self.overrides}" if self.overrides else ""
        return f"Target({name(self.system)}{extra})"
