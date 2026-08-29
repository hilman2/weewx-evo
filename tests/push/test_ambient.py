#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""The Ambient Weather protocol.

Ambient hardware descends from the same Fine Offset design as Ecowitt's and looks
almost identical on the wire. Almost is the problem: it says `soilhum1` where Ecowitt
says `soilmoisture1`, `battout` where Ecowitt says `wh65batt`, and `lightning_day`
where Ecowitt says `lightning_num`.

Read with the Ecowitt catalog, an Ambient upload does not fail. The temperature and
the wind arrive, and the soil probes, the batteries and the lightning sensor are
dropped without a word. These tests are what stops that.
"""

from helpers import read
from ultimatepush import protocols
from ultimatepush.catalogs import ambient as catalog
from ultimatepush.catalogs import ecowitt as ecowitt_catalog


def packet_of(text, **kwargs):
    return read('ambient', text, **kwargs)


def test_a_captured_upload_becomes_a_packet(payload):
    """An AMBWeatherV4.0.2 console, as captured by the interceptor driver."""
    packet, dialect, guesses = packet_of(payload('ambient/ambweather_v4'))

    assert dialect.units == protocols.US
    assert packet['outTemp'] == 69.1
    assert packet['inTemp'] == 73.4
    assert packet['barometer'] == 29.89      # baromrelin
    assert packet['pressure'] == 29.48       # baromabsin
    assert packet['radiation'] == 299.23
    assert packet['UV'] == 3.0
    assert packet['maxdailygust'] == 3.4
    assert packet['totalRain'] == 0.87       # no Ecowitt console sends this
    assert guesses == []


def test_the_names_ecowitt_does_not_have():
    """Every one of these is dropped by a driver that only knows the Ecowitt names."""
    packet, _, _ = packet_of(
        'PASSKEY=A&stationtype=AMBWeatherV4.3.4&tempf=60'
        '&soilhum1=42&soilhum10=17&soiltemp1f=55.4'
        '&battout=1&battin=0&battsm1=1'
        '&lightning_day=7&lightning_distance=12&lightning_hour=2'
        '&relay1=1&relay10=0&aqi_pm25=51&pm25=12.5&24hourrainin=0.31')

    assert packet['soilMoist1'] == 42.0
    assert packet['soilMoist10'] == 17.0     # Ambient goes to ten, Ecowitt to sixteen
    assert packet['soilTemp1'] == 55.4
    assert packet['outTempBatteryStatus'] == 1.0
    assert packet['inTempBatteryStatus'] == 0.0
    assert packet['soilMoistBatt1'] == 1.0
    assert packet['lightning_num'] == 7.0
    assert packet['lightning_distance'] == 12.0
    assert packet['relay1'] == 1.0
    assert packet['pm2_5'] == 12.5
    assert packet['pm2_5_aqi'] == 51.0
    assert packet['rain24'] == 0.31


def test_the_aqin_module_arrives():
    """Ambient's indoor air quality sensor. Ecowitt has no equivalent at all."""
    packet, _, _ = packet_of(
        'PASSKEY=A&stationtype=AMBWeatherV4.3.4&tempf=60'
        '&pm25_in_aqin=8.1&aqi_pm25_aqin=34&co2_in_aqin=612'
        '&pm_in_temp_aqin=70.2&pm_in_humidity_aqin=44')

    assert packet['pm2_5_in_aqin'] == 8.1
    assert packet['pm2_5_aqi_aqin'] == 34.0
    assert packet['co2_in_aqin'] == 612.0
    assert packet['aqin_Temp'] == 70.2
    assert packet['aqin_Hum'] == 44.0


def test_a_reading_both_protocols_send_lands_in_the_same_column():
    """Two consoles reporting the same thing into two different columns would be a
    decision nobody made on purpose."""
    shared = set(catalog.FIELDS) & set(ecowitt_catalog.FIELDS)
    disagreements = {raw: (catalog.FIELDS[raw], ecowitt_catalog.FIELDS[raw])
                     for raw in shared
                     if catalog.FIELDS[raw] != ecowitt_catalog.FIELDS[raw]}

    assert not disagreements, \
        "the same name goes to two places: %s" % sorted(disagreements.items())


def test_the_catalog_covers_every_channel_the_hardware_has():
    """Home Assistant lists the channels somebody happened to own. The catalog has to
    cover the ones nobody has reported yet, or the first person to buy a tenth probe
    finds it silently dropped."""
    for channel in range(1, 11):
        assert 'soilhum%d' % channel in catalog.FIELDS
        assert 'temp%df' % channel in catalog.FIELDS
        assert 'humidity%d' % channel in catalog.FIELDS
        assert 'batt%d' % channel in catalog.FIELDS
    for channel in range(1, 5):
        assert 'leak%d' % channel in catalog.FIELDS


def test_the_fields_ambient_computes_on_its_servers_are_not_in_the_catalog():
    """dewPoint, feelsLike and lastRain come back from Ambient's cloud API and never
    from a console. WeeWX derives the first two itself."""
    for name in ('dewPoint', 'feelsLike', 'lastRain'):
        assert name not in catalog.FIELDS
