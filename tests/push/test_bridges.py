#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""The two bridges: Acurite and LaCrosse.

Both are the same shape of problem. One request per sensor, all of them carrying the
same field names, and nothing in any of them saying where that sensor hangs. So both
qualify their readings before mapping, and both leave the placement to the user.

Every fixture is a frame captured off real hardware, by way of the interceptor driver.
"""

import pytest

from helpers import FakeRequest, read
from ultimatepush import protocols, transport
from ultimatepush.catalogs import acurite as acurite_catalog
from ultimatepush.catalogs import lacrosse as lacrosse_catalog

ACURITE = protocols.by_name('acurite')
LACROSSE = protocols.by_name('lacrosse')


def sender(text):
    raw = transport.parse(text)
    protocol = protocols.detect(FakeRequest(text), raw, protocols.registry())
    return protocol.name if protocol else None


# ---------------------------------------------------------------- acurite


def test_the_five_in_one_is_the_station(payload):
    """It splits its readings over two frames and both are the station."""
    wind, _, _ = read('acurite', payload('acurite/5n1x31'))
    air, _, _ = read('acurite', payload('acurite/5n1x38'))

    assert wind['windSpeed'] == 9.0
    assert wind['windDir'] == 180.0
    assert wind['dayRain'] == 0.03
    assert wind['hourRain'] == 0.0
    assert air['outTemp'] == 84.0
    assert air['outHumidity'] == 76.0


def test_a_tower_waits_to_be_placed(payload):
    """Its tempf is not the station's, and which wall it is on is not in the payload.

    So it arrives named after the sensor that sent it, which is what the user pastes
    into field_map_extensions, and which stays the same across restarts.
    """
    packet, _, guesses = read('acurite', payload('acurite/tower'))

    assert 'outTemp' not in packet
    assert {g.raw for g in guesses} >= {'tower00002719_tempf',
                                        'tower00002719_humidity'}


def test_the_bridge_barometer_rides_along_in_every_frame(payload):
    """It belongs to the bridge, not to whatever sensor the frame came from. Qualified
    by sensor it would become a pressure per sensor and none of them would be placed.
    """
    tower, _, _ = read('acurite', payload('acurite/tower'))
    wind, _, _ = read('acurite', payload('acurite/5n1x31'))

    assert tower['pressure'] == 29.92
    assert wind['pressure'] == 29.92


def test_baromin_is_station_pressure_here():
    """Whatever the name suggests. The bridge does not know its own altitude, so WeeWX
    derives the barometer from this and the altitude in weewx.conf."""
    assert acurite_catalog.FIELDS['baromin'] == 'pressure'


def test_the_words_the_bridge_sends_instead_of_numbers(payload):
    """battery is 'normal' or 'low'. rssi is nought to four bars."""
    packet, _, _ = read('acurite', payload('acurite/5n1x31'))

    assert packet['txBatteryStatus'] == 0.0    # 'normal'
    assert packet['rxCheckPercent'] == 25.0    # one bar of four

    low, _, _ = read('acurite', payload('acurite/5n1x31').replace('normal', 'low'))
    assert low['txBatteryStatus'] == 1.0


def test_a_bridge_is_one_station_however_many_sensors_it_has(payload):
    for fixture in ('5n1x31', '5n1x38', 'tower'):
        raw = transport.parse(payload('acurite/' + fixture))
        assert ACURITE.station_of(raw) == '24C86Exxxxxx'


def test_an_acurite_frame_is_not_read_as_wunderground(payload):
    """It posts to the same endpoint with dateutc, action and realtime in it. Only
    'mt' separates the two, and reading it as WU would drop every tower."""
    for fixture in ('5n1x31', '5n1x38', 'tower'):
        assert sender(payload('acurite/' + fixture)) == 'acurite'


# ---------------------------------------------------------------- lacrosse


def test_the_base_station(payload):
    packet, dialect, _ = read('lacrosse', payload('lacrosse/base'))

    assert dialect.units == protocols.METRICWX
    assert packet['pressure'] == 806.0         # mbar
    assert packet['forecast'] == 3.0           # rainy


@pytest.mark.parametrize('fixture, field, value', [
    ('lacrosse/wind', 'windSpeed', 1.1),       # m/s
    ('lacrosse/wind', 'windGust', 1.9),
    ('lacrosse/wind', 'windDir', 315.0),
    ('lacrosse/thermo', 'outTemp', 18.9),      # C
    ('lacrosse/thermo', 'outHumidity', 90.0),
    ('lacrosse/uv', 'UV', 0.0),                # uvh, the index
])
def test_each_lacrosse_sensor(payload, fixture, field, value):
    packet, _, _ = read('lacrosse', payload(fixture))

    assert packet[field] == value


def test_the_rain_gauge_sends_inches_where_everything_else_is_metric(payload):
    """One gateway, two unit systems. 5.114 inches is 129.9 mm."""
    packet, _, _ = read('lacrosse', payload('lacrosse/rain'))

    assert packet['totalRain'] == pytest.approx(129.8956)
    assert packet['rainRate'] == 0.0


def test_the_lifetime_total_is_what_gets_differenced():
    """An LW30x has no daily counter, so the installer's default is wrong for it and
    the driver says so at startup."""
    assert LACROSSE.rain_counter == 'totalRain'
    assert 'rfa_ch1' in lacrosse_catalog.FIELDS


def test_a_channel_keeps_its_readings_apart(payload):
    """Two temperature sensors both send 'ot'. Without the channel the second would
    overwrite the first every eighteen seconds, with nothing in the log to say so."""
    first = payload('lacrosse/thermo')
    second = first.replace('ch=1', 'ch=2').replace('rid=20', 'rid=21')

    one, _, _ = read('lacrosse', first)
    two, _, _ = read('lacrosse', second)

    assert one['outTemp'] == 18.9
    assert two.get('extraTemp2') == 18.9
    assert 'outTemp' not in two


def test_what_nobody_has_worked_out_stays_out_of_the_database(payload):
    """An LW30x sends nine parameters whose meaning has never been established. A
    column of numbers nobody can label is worse than no column."""
    packet, _, guesses = read('lacrosse', payload('lacrosse/uv'))

    for name in ('uv', 'or', 'p'):
        assert name in lacrosse_catalog.UNDOCUMENTED
    assert not [g for g in guesses if g.raw in lacrosse_catalog.UNDOCUMENTED]
    assert 'UV' in packet                      # uvh, which is documented, is kept


def test_a_lacrosse_frame_is_recognised(payload):
    for fixture in ('base', 'wind', 'thermo', 'rain', 'uv'):
        assert sender(payload('lacrosse/' + fixture)) == 'lacrosse'
