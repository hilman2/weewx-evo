#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""What a WeatherFlow station broadcasts, and where it belongs in WeeWX.

Unlike the others, this hardware does not send name/value pairs. It broadcasts JSON
on the local network, and the readings are positional: an array where index 7 is the
air temperature because index 7 is the air temperature.

So there are two tables here rather than one. LAYOUTS says what each position is,
which is the protocol's own business and comes from WeatherFlow's UDP reference.
FIELDS says where each of those readings belongs in WeeWX, which is this driver's
decision, and looks like every other catalog.

Keeping them apart is what makes a firmware that appends a reading harmless: the new
position is simply not named yet, and everything before it still lines up.

Source: WeatherFlow Tempest UDP reference v171,
        https://weatherflow.github.io/Tempest/api/udp/v171/
"""

# What each position in an observation array is, in order.
#
# The names are WeatherFlow's own, snake-cased. Only the battery is renamed, per
# message type: an AIR and a SKY on one hub each have one, and a single 'battery'
# would put two devices in one column.
LAYOUTS = {
    # Tempest, the all-in-one. 18 values.
    'obs_st': (
        'time_epoch',              # seconds
        'wind_lull',               # m/s, the minimum over the sample interval
        'wind_avg',                # m/s
        'wind_gust',               # m/s
        'wind_direction',          # degrees
        'wind_sample_interval',    # seconds
        'station_pressure',        # mb
        'air_temperature',         # C
        'relative_humidity',       # %
        'illuminance',             # lux
        'uv',                      # index
        'solar_radiation',         # W/m2
        'rain_amount',             # mm, over the report interval
        'precipitation_type',      # 0 none, 1 rain, 2 hail, 3 rain and hail
        'lightning_avg_distance',  # km
        'lightning_count',         # strikes over the report interval
        'st_battery',              # volts
        'report_interval',         # minutes
    ),
    # AIR: temperature, humidity, pressure, lightning. 8 values.
    'obs_air': (
        'time_epoch',
        'station_pressure',
        'air_temperature',
        'relative_humidity',
        'lightning_count',
        'lightning_avg_distance',
        'air_battery',
        'report_interval',
    ),
    # SKY: wind, rain, light. 14 values.
    'obs_sky': (
        'time_epoch',
        'illuminance',
        'uv',
        'rain_amount',
        'wind_lull',
        'wind_avg',
        'wind_gust',
        'wind_direction',
        'sky_battery',
        'report_interval',
        'solar_radiation',
        'local_day_rain',          # mm since local midnight
        'precipitation_type',
        'wind_sample_interval',
    ),
    # Every three seconds, while the wind is being sampled.
    'rapid_wind': (
        'time_epoch',
        'wind_avg',
        'wind_direction',
    ),
    # One strike, as it happens.
    'evt_strike': (
        'time_epoch',
        'lightning_avg_distance',  # this strike's distance, km
        'lightning_energy',        # unitless, WeatherFlow gives no scale
    ),
    # Rain has started. Nothing is measured, so nothing is mapped.
    'evt_precip': (
        'time_epoch',
    ),
}

# The status messages are objects rather than arrays, so they need no layout. These
# are the keys worth keeping out of them.
STATUS_KEYS = ('timestamp', 'uptime', 'voltage', 'rssi', 'hub_rssi', 'sensor_status')


# Reading -> the WeeWX field it belongs in.
FIELDS = {
    'air_temperature': 'outTemp',
    'relative_humidity': 'outHumidity',
    # The station's own pressure, not reduced to sea level. WeeWX derives 'barometer'
    # from it and the altitude, which is the right way round: the altitude is in
    # weewx.conf and the station does not know it.
    'station_pressure': 'pressure',

    'wind_avg': 'windSpeed',
    'wind_gust': 'windGust',
    'wind_direction': 'windDir',
    'wind_lull': 'windLull',
    'wind_sample_interval': 'windSampleInterval',

    # Already the amount since the last report, which is what WeeWX means by 'rain'.
    # Every other protocol here sends running counters that StdDelta has to difference;
    # this one does not, and must not be differenced again.
    'rain_amount': 'rain',
    'local_day_rain': 'dayRain',
    'precipitation_type': 'precipType',

    'illuminance': 'illuminance',
    'uv': 'UV',
    'solar_radiation': 'radiation',

    # Strikes since the last report, which is exactly what this WeeWX field is.
    'lightning_count': 'lightning_strike_count',
    'lightning_avg_distance': 'lightning_distance',
    'lightning_energy': 'lightning_energy',

    'st_battery': 'st_batt',
    'air_battery': 'air_batt',
    'sky_battery': 'sky_batt',
    'report_interval': 'ws_interval',

    'uptime': 'wf_uptime',
    'voltage': 'wf_voltage',
    'rssi': 'wf_rssi',
    'hub_rssi': 'wf_hub_rssi',
    'sensor_status': 'wf_sensor_status',
}


# WeeWX field -> unit group, for the fields WeeWX does not already know.
GROUPS = {
    'windLull': 'group_speed',
    'windSampleInterval': 'group_deltatime',
    'dayRain': 'group_rain',
    'precipType': 'group_count',
    'st_batt': 'group_volt',
    'air_batt': 'group_volt',
    'sky_batt': 'group_volt',
    'ws_interval': 'group_deltatime',
    'wf_uptime': 'group_deltatime',
    'wf_voltage': 'group_volt',
    'wf_rssi': 'group_db',
    'wf_hub_rssi': 'group_db',
    'wf_sensor_status': 'group_count',
}


# Readings that arrive in a unit other than the one WeeWX keeps the column in.
SCALE = {
    # Minutes. group_deltatime is seconds, and the Ecowitt catalog already puts its
    # own upload interval in this column in seconds.
    'report_interval': 60,
}
