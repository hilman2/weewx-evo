#
#    Copyright (c) 2016-2020 Matthew Wall
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""What an Acurite bridge forwards, and where it belongs in WeeWX.

The bridge sends one request per sensor, not one per station. A frame says which
sensor it came from in `sensor`, and what kind of sensor that is in `mt`, and then
carries three or four readings. So a station with a 5-in-1 and three towers produces
four requests every eighteen seconds, each of them with `tempf` in it meaning
something different.

That is why the readings are qualified before they reach this catalog. The 5-in-1 is
the station and keeps the plain names; everything else is prefixed with what it is and
which sensor it was, and waits for the user to say where it goes. Nothing else can:
which tower is on the north wall and which is in the greenhouse is not in the payload.

Field names and their meanings come from the interceptor driver by Matthew Wall, which
captured them from real bridges. GPLv3, like this.
"""

# The message types a 5-in-1 sends. It splits its readings over two frames, and both
# are the station, so both keep the plain names.
STATION_TYPES = ('5N1x31', '5N1x38')

# Everything else is a sensor whose placement only the user knows.
SENSOR_TYPES = ('tower', 'ProIn', 'ProOut', 'rain899')

# Readings that belong to the bridge rather than to whichever sensor a frame came
# from. The bridge puts its own barometer in every frame it forwards, so qualifying
# this one by sensor would produce a pressure per sensor and place none of them.
BRIDGE_READINGS = ('baromin',)


FIELDS = {
    # --- the 5-in-1 ------------------------------------------------------------
    'tempf': 'outTemp',
    'humidity': 'outHumidity',
    'windspeedmph': 'windSpeed',
    'winddir': 'windDir',
    'rainin': 'hourRain',
    'dailyrainin': 'dayRain',
    # The bridge puts its own barometer in every frame. It is station pressure, not
    # reduced to sea level, whatever the name suggests. WeeWX derives 'barometer' from
    # it and the altitude in weewx.conf, which the bridge does not know.
    'baromin': 'pressure',
    'dewptf': 'fdewptf',

    # --- the bridge ------------------------------------------------------------
    # 'normal' or 'low', turned into 0 or 1 by the protocol.
    'battery': 'txBatteryStatus',
    # 0 to 4 bars, turned into a percentage by the protocol.
    'rssi': 'rxCheckPercent',
}


GROUPS = {
    'hourRain': 'group_rain',
    'dayRain': 'group_rain',
    'fdewptf': 'group_temperature',
    'txBatteryStatus': 'group_count',
    'rxCheckPercent': 'group_percent',
}


# Prefixes for the readings that arrive qualified, so that a new tower is recognised
# as a tower rather than as an unknown name.
CHANNELS = {
    'tower': ('Acurite tower sensor', 16),
    'ProIn': ('Acurite Pro indoor sensor', 16),
    'ProOut': ('Acurite Pro outdoor sensor', 16),
    'rain899': ('Acurite 899 rain gauge', 16),
}


PLACEMENT_UNKNOWN = {
    'tower': "An Acurite tower sensor. The bridge says which sensor sent a reading "
             "and nothing else: whether it is on a north wall or in a greenhouse is "
             "yours to say.",
    'ProIn': "An Acurite Pro indoor sensor, with an optional water probe.",
    'ProOut': "An Acurite Pro outdoor sensor.",
}


CONTESTED = {}
CONTESTED_WITH = ''
