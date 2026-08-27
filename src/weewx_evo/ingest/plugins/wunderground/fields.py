"""What a Weather Underground upload can carry, and what we call it.

Merged from three sources, because no one of them is complete:

  * **`weewx-interceptor`'s `WUClient.Parser.LABEL_MAP`** -- what hardware
    actually sends. Fifty-nine names, thirty of which WeeWX itself never
    sends: the eight extra thermometers, the air quality block, the per-sensor
    battery flag. That list is years of people reporting what turned up in
    their logs and is the reason this table is not written from the spec.
  * **`weewx.restx.AmbientThread._FORMATS`** -- what WeeWX sends. Anything in
    there has to be readable here, or two weewx-evo instances cannot talk to
    each other through a protocol both of them speak.
  * **`uploads/ambient.py`** -- our own half of the same protocol, already
    transcribed. It is the sending direction of this file.

Comparing the first two found three fields that hardware and WeeWX both send
and the interceptor drops on the floor: `rainin`, `soilmoisture` and
`leafwetness2`. The last two are the plain first sensor -- WeeWX writes
`soilMoist1` as `soilmoisture=` with no digit, and the interceptor maps only
`soilmoisture1` through `4`. A station with one soil probe therefore delivered
nothing at all. They are in here.

**Everything is US units and there is no parameter to say otherwise.** The
protocol is defined in Fahrenheit, inches and miles per hour, so a packet is
tagged `usUnits = US` and `units.py` does the rest on the way out. That is why
this table is names only: there is nothing to convert here, and converting
twice is how a page ends up in the wrong unit.
"""

from __future__ import annotations

#: Their name -> ours. WeeWX's names, because the archive is WeeWX's.
FIELDS: dict[str, str] = {
    # -- the basics ---------------------------------------------------
    "tempf": "outTemp",
    "humidity": "outHumidity",
    "dewptf": "dewpoint",
    "windchillf": "windchill",
    "heatindexf": "heatindex",
    "baromin": "barometer",
    # Station pressure, as Ambient and Ecowitt consoles send it. Not in the
    # WU spec and not what `baromin` means: one is reduced to sea level and
    # the other is not, and at 440 m they are 50 mbar apart.
    "absbaromin": "pressure",
    "baromabsin": "pressure",

    # -- wind ---------------------------------------------------------
    "winddir": "windDir",
    "windspeedmph": "windSpeed",
    "windgustmph": "windGust",
    "windgustdir": "windGustDir",
    # WeeWX sends these three and the interceptor throws them away as
    # uninteresting. They are readings, and they have columns.
    "windspdmph_avg2m": "windSpeed2",
    "windgustmph_10m": "windGust10",
    "windgustdir_10m": "windGustDir10",

    # -- rain ---------------------------------------------------------
    # Mapped, not differenced. The interceptor works `rain` out here by
    # subtracting one running total from the one before it; `derive.py` does
    # that for every driver at once (`DELTAS`), so doing it again in here
    # would be a second place that has to agree about midnight rollovers.
    "rainin": "hourRain",
    "dailyrainin": "dayRain",
    "weeklyrainin": "weekRain",
    "monthlyrainin": "monthRain",
    "yearlyrainin": "yearRain",
    "totalrainin": "totalRain",
    # Some firmware drops the "in" even though the value is still inches.
    "dailyrain": "dayRain",
    "yearlyrain": "yearRain",

    # -- sun ----------------------------------------------------------
    "solarradiation": "radiation",
    "UV": "UV",

    # -- indoors ------------------------------------------------------
    "indoortempf": "inTemp",
    "indoorhumidity": "inHumidity",

    # -- extra sensors ------------------------------------------------
    "temp1f": "extraTemp1", "temp2f": "extraTemp2", "temp3f": "extraTemp3",
    "temp4f": "extraTemp4", "temp5f": "extraTemp5", "temp6f": "extraTemp6",
    "temp7f": "extraTemp7", "temp8f": "extraTemp8",
    "humidity1": "extraHumid1", "humidity2": "extraHumid2",
    "humidity3": "extraHumid3", "humidity4": "extraHumid4",
    "humidity5": "extraHumid5", "humidity6": "extraHumid6",
    "humidity7": "extraHumid7", "humidity8": "extraHumid8",

    # -- soil and leaf ------------------------------------------------
    "soiltempf": "soilTemp1", "soiltemp2f": "soilTemp2",
    "soiltemp3f": "soilTemp3", "soiltemp4f": "soilTemp4",
    # The bare name is the first sensor. This is one of the three the
    # interceptor misses, and it is the one that matters most: a station with
    # a single soil probe sends exactly this and nothing else.
    "soilmoisture": "soilMoist1",
    "soilmoisture1": "soilMoist1", "soilmoisture2": "soilMoist2",
    "soilmoisture3": "soilMoist3", "soilmoisture4": "soilMoist4",
    "leafwetness": "leafWet1",
    "leafwetness2": "leafWet2",

    # -- air quality --------------------------------------------------
    # WeeWX has columns for a few of these and not the rest; the ones with
    # nowhere to go are reported by `weewx-evo columns` like any other
    # unplaceable reading rather than dropped in silence.
    "AqPM2.5": "pm2_5",
    "AqPM10": "pm10_0",
    "AqOZONE": "o3",
    "AqCO": "co",
    "AqCOT": "coT",
    "AqNO": "no",
    "AqNO2": "no2",
    "AqNO2T": "no2T",
    "AqNO2Y": "no2Y",
    "AqNOX": "noX",
    "AqNOY": "noY",
    "AqNO3": "no3",
    "AqSO2": "so2",
    "AqSO2T": "so2T",
    "AqSO4": "so4",
    "AqEC": "ec",
    "AqOC": "oc",
    "AqBC": "bc",
    "AqUV-AETH": "uv_aeth",

    # -- housekeeping the hardware sends anyway ------------------------
    "lowbatt": "batteryStatus1",
}

#: Sent by every station, carrying no measurement. Named so they can be passed
#: over without being reported as unknown -- an "unrecognised field" line for
#: `action=updateraw` on every upload is noise that teaches people to ignore
#: the log that also names the field they actually lost.
IGNORED: frozenset[str] = frozenset({
    # Identity and authentication.
    "ID", "PASSWORD", "stationtype", "model", "PASSKEY", "mac",
    # The request itself.
    "action", "realtime", "rtfreq", "softwaretype", "dateutc",
    # Averaged wind that WeeWX has no column for. `windspdmph_avg2m` and the
    # two ten-minute gust fields are readings and are mapped above; this one
    # is not.
    "winddir_avg2m",
    # Human-entered, not measured.
    "weather", "clouds", "visibility",
})

#: Which unit group each of our names belongs to, for the ones `units.py`
#: does not already know. Everything standard is in the core table; these are
#: the air quality fields, which no WeeWX schema has columns for either.
GROUPS: dict[str, str] = {
    "co": "group_fraction", "coT": "group_fraction",
    "no": "group_fraction", "no2": "group_fraction",
    "no2T": "group_fraction", "no2Y": "group_fraction",
    "noX": "group_fraction", "noY": "group_fraction",
    "no3": "group_fraction", "so2": "group_fraction",
    "so2T": "group_fraction", "so4": "group_fraction",
    "ec": "group_concentration", "oc": "group_concentration",
    "bc": "group_concentration", "uv_aeth": "group_concentration",
}

#: What these stations send for "the sensor did not report". A real -9999 °F
#: is not a temperature anybody has measured.
MISSING = (-9999.0, -9999)
