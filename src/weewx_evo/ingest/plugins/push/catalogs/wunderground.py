#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""What a Weather Underground upload calls things, and where they belong in WeeWX.

Unlike the Ecowitt and Ambient catalogs, this one is not generated. There is nothing
to generate it from and nothing to regenerate it for: the protocol was published once,
has not changed in a decade, and the page it was published on is gone. The copy it was
written from is in tests/fixtures/wunderground/spec.txt, and a test checks that every
field named there appears here, so the derivation stays checkable.

The comment on each line is the specification's own wording. A mapping can then be
checked against what a field is supposed to be, rather than against what its name
suggests.

Two catalogs, because the same endpoint carries two dialects. See FIELDS for the
imperial one the specification describes, and METRIC_FIELDS for the Celsius and
millimetres one that Fine Offset firmwares send instead.

Sources:
    the specification, wiki.wunderground.com/index.php/PWS_-_Upload_Protocol
    six captured uploads, from the interceptor driver by Matthew Wall
"""

# Raw field -> WeeWX field, imperial dialect.
#
# The comment on each line is the specification's own wording, so that a mapping can
# be checked against what the field is supposed to be rather than against what its
# name suggests.
FIELDS = {
    # --- wind ------------------------------------------------------------------
    'winddir': 'windDir',                     # 0-360 instantaneous wind direction
    'windspeedmph': 'windSpeed',              # mph instantaneous wind speed
    'windgustmph': 'windGust',                # mph current wind gust
    'windgustdir': 'windGustDir',             # 0-360, software specific period
    # The averaged wind. WeeWX has no column for any of these, so they keep the name
    # the hardware uses, which is also the name the Ecowitt catalog gives them. A
    # station that changes protocol keeps one series per sensor rather than starting a
    # second column for the same reading.
    'windspdmph_avg2m': 'windspdmph_avg2m',   # mph 2 minute average wind speed
    'winddir_avg2m': 'winddir_avg2m',         # 0-360 2 minute average direction
    'windspdmph_avg10m': 'windspdmph_avg10m', # beyond the specification, sent by
    'winddir_avg10m': 'winddir_avg10m',       # Ambient and Ecowitt hardware
    'windgustmph_10m': 'windgustmph_10m',     # mph past 10 minutes wind gust
    'windgustdir_10m': 'windgustdir_10m',     # 0-360 past 10 minutes gust direction

    # --- air -------------------------------------------------------------------
    'humidity': 'outHumidity',                # % outdoor humidity 0-100%
    'tempf': 'outTemp',                       # F outdoor temperature
    'dewptf': 'fdewptf',                      # F outdoor dewpoint, as the device
                                              # computed it. WeeWX computes its own
                                              # 'dewpoint', so this is kept beside it
                                              # rather than over it.
    'indoortempf': 'inTemp',                  # F indoor temperature
    'indoorhumidity': 'inHumidity',           # % indoor humidity 0-100
    'baromin': 'barometer',                   # barometric pressure inches. Two
                                              # firmwares mean station pressure by
                                              # it; see STATION_PRESSURE_FIRMWARE.

    # Extra outdoor sensors. The specification says "for extra outdoor sensors use
    # temp2f, temp3f, and so on", so temp2f is the second sensor, not the second
    # channel of an eight-channel array. Placed where Ecowitt hardware puts its
    # WH31 channels, since on that hardware they are the same sensors.
    'temp2f': 'extraTemp2',
    'temp3f': 'extraTemp3',
    'temp4f': 'extraTemp4',
    'temp5f': 'extraTemp5',
    'temp6f': 'extraTemp6',
    'temp7f': 'extraTemp7',
    'temp8f': 'extraTemp8',

    # --- rain ------------------------------------------------------------------
    'rainin': 'hourRain',                     # rain inches over the past hour, i.e.
                                              # accumulated rainfall in the past 60 min
    'dailyrainin': 'dayRain',                 # rain inches so far today, local time

    # --- sky -------------------------------------------------------------------
    'solarradiation': 'radiation',            # W/m^2
    'UV': 'UV',                               # index
    'visibility': 'visibility',               # nm visibility (nautical miles, scaled
                                              # to statute miles, see SCALE)
    # weather and clouds are text, METAR style. They are not readings and are left in
    # the report rather than the packet.

    # --- ground ----------------------------------------------------------------
    'soiltempf': 'soilTemp1',                 # F soil temperature
    'soiltemp2f': 'soilTemp2',
    'soiltemp3f': 'soilTemp3',
    'soiltemp4f': 'soilTemp4',
    'soilmoisture': 'soilMoist1',             # %
    'soilmoisture2': 'soilMoist2',
    'soilmoisture3': 'soilMoist3',
    'soilmoisture4': 'soilMoist4',
    'leafwetness': 'leafWet1',                # %
    'leafwetness2': 'leafWet2',

    # --- pollution -------------------------------------------------------------
    # The specification gives a unit for every one of these, and they are not all the
    # same unit. Where WeeWX has a column, the value is scaled to the unit WeeWX
    # keeps that column in. See SCALE.
    'AqNO': 'no',                             # NO (nitric oxide) ppb
    'AqNO2T': 'no2_true',                     # NO2, true measure, ppb
    'AqNO2': 'no2',                           # NO2 computed, NOx-NO, ppb
    'AqNO2Y': 'no2_noy',                      # NO2 computed, NOy-NO, ppb
    'AqNOX': 'nox',                           # NOx (nitrogen oxides) ppb
    'AqNOY': 'noy',                           # NOy (total reactive nitrogen) ppb
    'AqNO3': 'no3',                           # NO3 ion (nitrate) ug/m3
    'AqSO4': 'so4',                           # SO4 ion (sulfate) ug/m3
    'AqSO2': 'so2',                           # SO2 (sulfur dioxide) conventional ppb
    'AqSO2T': 'so2_trace',                    # SO2 trace levels ppb
    'AqCO': 'co',                             # CO (carbon monoxide) conventional ppm
    'AqCOT': 'co_trace',                      # CO trace levels ppb
    'AqEC': 'ec',                             # EC (elemental carbon) PM2.5 ug/m3
    'AqOC': 'oc',                             # OC (organic carbon) PM2.5 ug/m3
    'AqBC': 'bc',                             # BC (black carbon at 880 nm) ug/m3
    'AqUV-AETH': 'uv_aeth',                   # Aethalometer second channel, 370 nm
    'AqPM2.5': 'pm2_5',                       # PM2.5 mass ug/m3
    'AqPM10': 'pm10_0',                       # PM10 mass ug/m3
    'AqOZONE': 'o3',                          # Ozone ppb

    # --- beyond the specification ----------------------------------------------
    # Fine Offset firmwares send these on the same endpoint. Every one of them comes
    # out of a captured upload, not out of a manual.
    'windchillf': 'fwindchillf',              # F, as the device computed it
    'heatindexf': 'fheatindexf',
    'feelslikef': 'ffeelslikef',
    'rainratein': 'rainRate',                 # inch/hour
    'hourlyrainin': 'hourRain',
    'eventrainin': 'eventRain',
    'weeklyrainin': 'weekRain',
    'monthlyrainin': 'monthRain',
    'yearlyrainin': 'yearRain',
    'totalrainin': 'totalRain',
    'maxdailygust': 'maxdailygust',
    'absbaromin': 'pressure',                 # WS-1002 V2.4.3 station pressure
    'baromabsin': 'pressure',                 # newer firmwares, same reading
    'baromrelin': 'barometer',                # newer firmwares, unambiguous
    'uv': 'UV',                               # lowercase on some firmwares
    'lowbatt': 'outTempBatteryStatus',        # the outdoor array, 0 or 1
    'soilmoisture1': 'soilMoist1',            # EasyWeather sends the digit
    'soilmoisture5': 'soilMoist5',
    'soilmoisture6': 'soilMoist6',
    'soilmoisture7': 'soilMoist7',
    'soilmoisture8': 'soilMoist8',
}


# The metric dialect: 'Weather logger V2.x', 'HP1001 V2.2.2' and their relatives.
#
# Same endpoint, same ID and PASSWORD, different names and different units. Celsius,
# hPa, millimetres, lux. It is a dialect rather than a protocol of its own because
# nothing else about the exchange differs.
METRIC_FIELDS = {
    'intemp': 'inTemp',                       # C
    'outtemp': 'outTemp',                     # C
    'inhumi': 'inHumidity',                   # %
    'outhumi': 'outHumidity',                 # %
    'dewpoint': 'fdewptf',                    # C, as the device computed it
    'windchill': 'fwindchillf',               # C
    'windspeed': 'windSpeed',
    'windgust': 'windGust',
    'winddir': 'windDir',                     # degrees, the same either way
    'absbaro': 'pressure',                    # hPa
    'relbaro': 'barometer',                   # hPa
    'rainrate': 'rainRate',
    'dailyrain': 'dayRain',
    'weeklyrain': 'weekRain',
    'monthlyrain': 'monthRain',
    'yearlyrain': 'yearRain',
    'light': 'luminosity',                    # lux
    # Not the UV index. In this dialect UV is the raw irradiance in uW/cm2, which is
    # why captured uploads carry values like 919. Calling it 'UV' would put a number
    # forty times too large into a column reports render as an index, so it gets a
    # column of its own and keeps its unit.
    'UV': 'uvradiation',                      # uW/cm2
    'lowbatt': 'outTempBatteryStatus',
}


# WeeWX field -> unit group, for every field above that WeeWX does not already know.
GROUPS = {
    'windspdmph_avg2m': 'group_speed2',
    'winddir_avg2m': 'group_direction',
    'windspdmph_avg10m': 'group_speed2',
    'winddir_avg10m': 'group_direction',
    'windgustmph_10m': 'group_speed2',
    'windgustdir_10m': 'group_direction',
    'fdewptf': 'group_temperature',
    'fwindchillf': 'group_temperature',
    'fheatindexf': 'group_temperature',
    'ffeelslikef': 'group_temperature',
    'hourRain': 'group_rain',
    'dayRain': 'group_rain',
    'weekRain': 'group_rain',
    'monthRain': 'group_rain',
    'yearRain': 'group_rain',
    'totalRain': 'group_rain',
    'eventRain': 'group_rain',
    'maxdailygust': 'group_speed2',
    'visibility': 'group_distance',
    'luminosity': 'group_illuminance',
    'uvradiation': 'group_radiation',
    'no2_true': 'group_concentration',
    'no2_noy': 'group_concentration',
    'nox': 'group_concentration',
    'noy': 'group_concentration',
    'no3': 'group_concentration',
    'so4': 'group_concentration',
    'so2_trace': 'group_fraction',
    'co_trace': 'group_fraction',
    'ec': 'group_concentration',
    'oc': 'group_concentration',
    'bc': 'group_concentration',
    'uv_aeth': 'group_concentration',
}


# Values that arrive in a unit other than the one WeeWX keeps the column in.
#
# Nothing else in this driver touches a value on its way through, and that is on
# purpose: a scaled number is a number nobody can check against the payload. These
# five are unavoidable. The alternative is a column labelled ppm holding ppb, which
# is wrong by a thousand and looks right.
SCALE = {
    # The specification gives these in ppb. WeeWX keeps group_fraction in ppm.
    'AqNO': 0.001,
    'AqNO2T': 0.001,
    'AqNO2Y': 0.001,
    'AqSO2': 0.001,
    'AqSO2T': 0.001,
    'AqCOT': 0.001,
    'AqOZONE': 0.001,
    # Nautical miles to the statute miles WeeWX keeps group_distance in.
    'visibility': 1.15078,
}


# The metric dialect sends millimetres where weewx.METRIC keeps centimetres, and
# microwatts per square centimetre where group_radiation keeps watts per square
# metre. Both are fixed conversions and neither is in doubt.
METRIC_SCALE = {
    'rainrate': 0.1,
    'dailyrain': 0.1,
    'weeklyrain': 0.1,
    'monthlyrain': 0.1,
    'yearlyrain': 0.1,
    'UV': 0.01,
}

METRIC_GROUPS = {
    'fdewptf': 'group_temperature',
    'fwindchillf': 'group_temperature',
    'dayRain': 'group_rain',
    'weekRain': 'group_rain',
    'monthRain': 'group_rain',
    'yearRain': 'group_rain',
    'luminosity': 'group_illuminance',
    'uvradiation': 'group_radiation',
}

# One thing about the metric dialect cannot be read off a payload: whether the wind
# arrives in kilometres per hour or in metres per second. The two differ by 3.6, both
# are plausible for the numbers these consoles send, and the firmware does not say.
#
# The default follows the interceptor driver, which has been pointed at this hardware
# for a decade: kilometres per hour, i.e. weewx.METRIC, no conversion. Set
# 'metric_wind = mps' in the driver section if your console disagrees, and the packet
# becomes weewx.METRICWX instead, where rain is in millimetres and no rain conversion
# is needed either.
#
# It is said out loud in the log the first time a metric upload arrives, because a
# wind speed that is wrong by 3.6 is not obvious in a report and is very hard to
# correct afterwards.
METRIC_WIND_CHOICES = ('kph', 'mps')


# Sensor families, for deciding what a channel this catalog does not list would be.
# The counts are what the protocol allows, which for the ground sensors is what the
# specification names and no more.
CHANNELS = {
    'soiltemp': ('WU soil temperature', 4),
    'soilmoisture': ('WU soil moisture', 4),
    'leafwetness': ('WU leaf wetness', 2),
    'temp': ('WU extra sensor', 8),
}


# Nothing here is contested.
#
# 'baromin' looks like it should be. Most firmwares send sea-level pressure, which
# belongs in 'barometer'; WH2600GEN_V2.2.5 and WH2650A_V1.2.1 send station pressure,
# which belongs in 'pressure'. But those two say so in softwaretype, so the question
# has an answer in every upload that carries one, and holding the field back would
# leave every ordinary station with no pressure at all rather than with a possibly
# misplaced one. It goes to 'barometer', and STATION_PRESSURE_FIRMWARE moves it.
CONTESTED = {}

CONTESTED_WITH = ''


# Firmwares that mean station pressure by 'baromin'. From the interceptor driver,
# which found them the way such things are found: somebody's readings were wrong.
STATION_PRESSURE_FIRMWARE = ('WH2600GEN_V2.2.5', 'WH2650A_V1.2.1')


METADATA = frozenset([
    'ID', 'PASSWORD', 'action', 'dateutc', 'softwaretype', 'realtime', 'rtfreq',
    'weather', 'clouds',
])

# Names that appear in one dialect and never in the other. One of them in a payload
# settles which catalog to read it with, without any reading having to be plausible
# for the answer to be right.
METRIC_MARKERS = ('intemp', 'outtemp', 'absbaro', 'relbaro', 'inhumi', 'outhumi')
