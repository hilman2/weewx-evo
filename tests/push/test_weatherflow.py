#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""WeatherFlow, from the datagrams in the official reference.

Every fixture here is an example out of WeatherFlow's own UDP reference, unchanged.
That matters more than usual: the readings are positional, so a mapping that is off by
one puts the humidity in the pressure column and looks entirely plausible.
"""

import pytest

from helpers import read
from ultimatepush import protocols, transport
from ultimatepush.catalogs import weatherflow as catalog

WF = protocols.by_name('weatherflow')


def packet_of(text, **kwargs):
    return read('weatherflow', text, **kwargs)


# ---------------------------------------------------------------- the layouts


def test_the_layouts_are_as_long_as_the_reference_says():
    """An array with more values than names is a firmware that added a reading. One
    with fewer names than values means somebody trimmed the wrong end."""
    assert len(catalog.LAYOUTS['obs_st']) == 18
    assert len(catalog.LAYOUTS['obs_air']) == 8
    assert len(catalog.LAYOUTS['obs_sky']) == 14
    assert len(catalog.LAYOUTS['rapid_wind']) == 3
    assert len(catalog.LAYOUTS['evt_strike']) == 3


def test_no_two_devices_share_a_battery_column():
    """An AIR and a SKY on one hub each have one. A single 'battery' would put two
    devices in one column, and the last one to report would win."""
    batteries = [name for layout in catalog.LAYOUTS.values() for name in layout
                 if name.endswith('battery')]

    assert len(set(batteries)) == len(batteries)


# ---------------------------------------------------------------- observations


def test_a_tempest_observation(payload):
    packet, dialect, guesses = packet_of(payload('weatherflow/obs_st'))

    assert dialect.units == protocols.METRICWX
    assert packet['outTemp'] == 22.37          # index 7
    assert packet['outHumidity'] == 50.26      # index 8
    assert packet['pressure'] == 1017.57       # index 6, station pressure
    assert packet['windSpeed'] == 0.22         # index 2, m/s
    assert packet['windGust'] == 0.27
    assert packet['windLull'] == 0.18
    assert packet['windDir'] == 144.0
    assert packet['illuminance'] == 328.0
    assert packet['UV'] == 0.03
    assert packet['radiation'] == 3.0
    assert packet['rain'] == 0.0
    assert packet['lightning_strike_count'] == 0.0
    assert packet['st_batt'] == 2.410
    assert guesses == []


def test_an_air_observation(payload):
    packet, _, _ = packet_of(payload('weatherflow/obs_air'))

    assert packet['pressure'] == 835.0
    assert packet['outTemp'] == 10.0
    assert packet['outHumidity'] == 45.0
    assert packet['air_batt'] == 3.46
    assert 'st_batt' not in packet


def test_a_sky_observation(payload):
    """Its layout puts the solar radiation after the battery, which is the kind of
    thing that only a captured message settles."""
    packet, _, _ = packet_of(payload('weatherflow/obs_sky'))

    assert packet['illuminance'] == 9000.0
    assert packet['UV'] == 10.0
    assert packet['windSpeed'] == 4.6
    assert packet['windDir'] == 187.0
    assert packet['sky_batt'] == 3.12
    assert packet['radiation'] == 130.0
    assert packet['dayRain'] is None           # the reference sends null here


def test_the_report_interval_arrives_in_seconds(payload):
    """The hub sends minutes. group_deltatime is seconds, and the Ecowitt catalog
    already puts its own upload interval in that column in seconds."""
    packet, _, _ = packet_of(payload('weatherflow/obs_st'))

    assert packet['ws_interval'] == 60.0


def test_the_time_comes_from_the_hub(payload):
    """It sends an epoch, not the text every other protocol sends. Written into the
    same field so that the clock window applies to it too."""
    raw = transport.parse(payload('weatherflow/obs_st'))
    named = WF.readings(None, raw)

    assert named['dateutc'] == '2020-05-08 14:36:54'
    assert 'time_epoch' not in named


# ---------------------------------------------------------------- events


def test_rapid_wind_is_wind_and_nothing_else(payload):
    packet, _, _ = packet_of(payload('weatherflow/rapid_wind'))

    assert packet['windSpeed'] == 2.3
    assert packet['windDir'] == 128.0
    assert set(packet) == {'windSpeed', 'windDir', 'dateTime'}


def test_a_strike_counts_as_one(payload):
    """The event and the observation fill the same field, so a station that sees both
    does not have to be read two ways."""
    packet, _, _ = packet_of(payload('weatherflow/evt_strike'))

    assert packet['lightning_distance'] == 27.0
    assert packet['lightning_energy'] == 3848.0
    assert packet['lightning_strike_count'] == 1.0


def test_rain_starting_measures_nothing(payload):
    """It is a notification, not a reading. A packet with only a timestamp in it is
    dropped by the driver."""
    packet, _, _ = packet_of(payload('weatherflow/evt_precip'))

    assert set(packet) == {'dateTime'}


def test_status_messages_carry_the_health_of_the_hardware(payload):
    packet, _, _ = packet_of(payload('weatherflow/device_status'))

    assert packet['wf_voltage'] == 3.50
    assert packet['wf_rssi'] == -17.0
    assert packet['wf_hub_rssi'] == -87.0
    assert packet['wf_uptime'] == 2189.0


def test_a_hub_status_does_not_look_like_readings(payload):
    """Its arrays and its firmware string must not end up as numbers in columns."""
    packet, _, _ = packet_of(payload('weatherflow/hub_status'))

    assert 'wf_uptime' in packet
    for field in packet:
        assert not field.startswith(('fs', 'radio_stats', 'mqtt_stats'))


# ---------------------------------------------------------------- the awkward parts


def test_the_rain_is_already_a_difference():
    """Every other protocol here sends counters. This one sends the millimetres since
    its last report, so StdDelta must not difference it again."""
    assert WF.rain_counter is None
    assert catalog.FIELDS['rain_amount'] == 'rain'


def test_a_station_is_its_hub_and_not_its_sensors(payload):
    """An AIR and a SKY on one hub are one station with two sensors."""
    for name in ('obs_air', 'obs_sky'):
        raw = transport.parse(payload('weatherflow/' + name))
        assert WF.station_of(raw) == 'HB-00000001'


def test_a_longer_array_than_the_layout_is_not_guessed_at():
    """WeatherFlow has appended readings before. A position nobody has named is a
    number, not a reading."""
    text = ('{"serial_number":"ST-1","type":"obs_st","hub_sn":"HB-1",'
            '"obs":[[1588948614,0.18,0.22,0.27,144,6,1017.57,22.37,50.26,328,0.03,'
            '3,0.0,0,0,0,2.410,1,99999]]}')
    packet, _, guesses = packet_of(text)

    assert packet['outTemp'] == 22.37
    assert 99999 not in packet.values()
    assert guesses == []


def test_the_most_recent_observation_in_a_batch_wins():
    """A device that has been out of touch sends several at once. Handing WeeWX an
    older one as though it had just been measured would be worse than dropping it."""
    text = ('{"serial_number":"ST-1","type":"obs_st","hub_sn":"HB-1","obs":['
            '[1588948614,0,0,0,0,6,1000.0,10.0,50,0,0,0,0,0,0,0,2.4,1],'
            '[1588948674,0,0,0,0,6,1017.57,22.37,50.26,0,0,0,0,0,0,0,2.4,1]]}')
    packet, _, _ = packet_of(text)

    assert packet['outTemp'] == 22.37


def test_a_message_type_this_driver_has_not_met_is_claimed_not_dropped():
    """Claimed, so that it is reported. Dropped afterwards for having nothing in it,
    rather than logged as an unrecognised protocol every time it arrives."""
    text = '{"serial_number":"ST-1","type":"obs_future","hub_sn":"HB-1","obs":[[1,2]]}'
    raw = transport.parse(text)

    assert WF.claims(None, raw) > 0
