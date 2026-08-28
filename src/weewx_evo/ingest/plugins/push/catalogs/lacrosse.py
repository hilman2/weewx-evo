#
#    Copyright (c) 2016-2020 Matthew Wall
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""What a LaCrosse LW30x gateway forwards, and where it belongs in WeeWX.

Two-letter names, one request per sensor, and a `ch` that says which channel the
sensor is on. Channel 1 is the station; anything above it is a sensor whose placement
only the user knows, so the readings are qualified with their channel before they get
here.

Half the parameters have no documented meaning. They are listed in UNDOCUMENTED rather
than left out, so that the report says a gateway sent them and somebody who has one
can work out what they are.

Field names, meanings and units come from the interceptor driver by Matthew Wall,
which captured them from an LW301. GPLv3, like this.
"""

# Sensor type -> what it is, by the `id` in every frame.
SENSORS = {
    '82': 'rain gauge',
    '84': 'temperature and humidity',
    '8e': 'UV',
    '90': 'wind',
    'c2': 'base station',
}


FIELDS = {
    # --- base station (id=c2) --------------------------------------------------
    # Station pressure in mbar. The base station has no channel.
    'baro': 'pressure',
    # 0 partly cloudy, 1 sunny, 2 cloudy, 3 rainy, 4 snowy.
    'wfor': 'forecast',

    # --- channel 1, i.e. the station -------------------------------------------
    'ot_ch1': 'outTemp',            # C
    'oh_ch1': 'outHumidity',        # %
    'ws_ch1': 'windSpeed',          # m/s
    'wg_ch1': 'windGust',           # m/s
    'wd_ch1': 'windDir',            # degrees
    'uvh_ch1': 'UV',                # index
    'rr_ch1': 'rainRate',           # inch/hour, converted, see SCALE
    'rfa_ch1': 'totalRain',         # inch since the gauge was last reset
    'pwr_ch1': 'txBatteryStatus',
}

# Channels two and up. Where they sit is the user's to say, so they are placed on the
# extra fields rather than over the station's, and PLACEMENT_UNKNOWN says why.
for _channel in range(2, 9):
    FIELDS['ot_ch%d' % _channel] = 'extraTemp%d' % _channel
    FIELDS['oh_ch%d' % _channel] = 'extraHumid%d' % _channel
    FIELDS['pwr_ch%d' % _channel] = 'batteryStatus%d' % _channel


GROUPS = {
    'forecast': 'group_count',
    'totalRain': 'group_rain',
    'txBatteryStatus': 'group_count',
}
for _channel in range(2, 9):
    GROUPS['batteryStatus%d' % _channel] = 'group_count'


CHANNELS = {
    'ot_ch': ('LaCrosse temperature sensor', 8),
    'oh_ch': ('LaCrosse humidity sensor', 8),
    'pwr_ch': ('LaCrosse sensor battery', 8),
}


PLACEMENT_UNKNOWN = {
    'ot_ch': "A LaCrosse sensor on a channel of its own. The gateway says which "
             "channel and nothing else, so where it hangs is yours to say.",
    'oh_ch': "A LaCrosse sensor on a channel of its own.",
}


# Readings that arrive in a unit other than the one weewx.METRICWX keeps them in.
SCALE = {
    # The gateway sends rain in inches even where everything else is metric.
    'rr_ch1': 25.4,
    'rfa_ch1': 25.4,
}


# Parameters an LW30x sends whose meaning nobody has established. Kept out of the
# packet rather than guessed at, and named here so that the report can say a gateway
# sent them.
UNDOCUMENTED = ('p', 'or', 'gw', 'av', 'htr', 'cz', 'ttr', 'rro', 'pv', 'lb', 'ac',
                'ptr', 'uv')


CONTESTED = {}
CONTESTED_WITH = ''
