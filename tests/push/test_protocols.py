#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Telling one protocol from another.

Everything downstream depends on getting this right. A Weather Underground upload read
with the Ecowitt catalog does not fail: it silently drops the pressure, the indoor
sensors and the hourly rain, and records the rest. That is the failure mode this whole
driver exists to prevent, so it is tested from captured payloads rather than from
made-up ones.
"""

import pytest

from helpers import FakeRequest
from ultimatepush import protocols, transport

WU_PATH = '/weatherstation/updateweatherstation.php'


def sender(text, path='/data/report/'):
    """Which protocol the driver would say sent this."""
    raw = transport.parse(text)
    protocol = protocols.detect(FakeRequest(text, path=path), raw, protocols.registry())
    return protocol.name if protocol else None


# ---------------------------------------------------------------- real payloads


@pytest.mark.parametrize('fixture, path, expected', [
    ('hp2561ae_pro', '/data/report/', 'ecowitt'),
    ('ambient/ambweather_v4', '/data/report/', 'ambient'),
    ('wunderground/observer_imperial', WU_PATH, 'wunderground'),
    ('wunderground/observer_metric', WU_PATH, 'wunderground'),
    ('wunderground/easyweather_hp2550', WU_PATH, 'wunderground'),
    ('wunderground/missing_values', WU_PATH, 'wunderground'),
    ('acurite/5n1x31', WU_PATH, 'acurite'),
    ('acurite/tower', WU_PATH, 'acurite'),
    ('lacrosse/base', '/', 'lacrosse'),
    ('lacrosse/thermo', '/', 'lacrosse'),
    ('weatherflow/obs_st', '', 'weatherflow'),
    ('weatherflow/rapid_wind', '', 'weatherflow'),
])
def test_a_captured_upload_is_recognised(payload, fixture, path, expected):
    assert sender(payload(fixture), path) == expected


# ---------------------------------------------------------------- the hard cases


def test_ambient_is_not_mistaken_for_ecowitt():
    """Both descend from Fine Offset and both send a PASSKEY.

    The station type is what separates them, and Ambient consoles always send theirs.
    Reading an Ambient upload as Ecowitt would drop soilhum, battout and the relays.
    """
    assert sender('PASSKEY=A&stationtype=AMBWeatherV4.0.2&tempf=1') == 'ambient'
    assert sender('PASSKEY=A&stationtype=GW2000A_V3.1.5&tempf=1') == 'ecowitt'


def test_ambient_without_a_station_type_is_still_ambient():
    """A name no Ecowitt console sends is enough on its own."""
    assert sender('PASSKEY=A&tempf=1&soilhum1=42') == 'ambient'
    assert sender('PASSKEY=A&tempf=1&battout=1') == 'ambient'


def test_the_endpoint_settles_wunderground():
    """Its hardware cannot be told to use another path, so the path is the strongest
    signal there is. It is also the only signal when a proxy strips the credentials."""
    assert sender('tempf=1', WU_PATH) == 'wunderground'
    assert sender('tempf=1', '/weatherstation/updateweatherstation.asp') == 'wunderground'
    assert sender('tempf=1', '/data/report/') is None


def test_credentials_settle_it_when_the_path_does_not():
    """A reverse proxy that rewrites the path must not cost the station its readings."""
    assert sender('ID=KX1&PASSWORD=s&tempf=1', '/somewhere/else') == 'wunderground'


def test_an_acurite_bridge_outranks_wunderground_on_its_own_endpoint():
    """The bridge posts there too, with dateutc, action and realtime in the query.

    Read as Weather Underground, its 5-in-1 would arrive and every tower would be
    dropped. 'mt' is the only thing that separates them, and it wins.
    """
    frame = ('dateutc=now&action=updateraw&realtime=1&id=24C86E&mt=tower'
             '&sensor=00002719&humidity=15&tempf=83.8&baromin=29.92')

    assert sender(frame, WU_PATH) == 'acurite'


def test_nothing_claims_a_payload_that_says_nothing():
    assert sender('tempf=59.7') is None
    assert sender('') is None


# ---------------------------------------------------------------- what they answer


def test_each_protocol_answers_the_way_its_hardware_expects():
    """A device that does not read the answer it wants counts the upload as failed."""
    answers = {p.name: (p.answer, p.content_type) for p in protocols.registry()}

    assert answers['ecowitt'] == ('{"errcode":"0","errmsg":"ok"}', 'application/json')
    assert answers['wunderground'] == ('success', 'text/plain')
    assert answers['ambient'] == ('success', 'text/plain')
    assert answers['acurite'] == ('{ "success": 1, "checkversion": "224" }',
                                  'application/json')
    # A broadcast is not answered. There is nobody to answer to.
    assert answers['weatherflow'] == ('', 'text/plain')


def test_every_protocol_says_what_it_is_for():
    """These strings go in the log at startup and in the documentation table."""
    for protocol in protocols.registry():
        assert protocol.name and protocol.label and protocol.hardware
        assert protocol.identity, "%s names no station" % protocol.name


def test_only_the_posting_protocols_are_switched_on_by_auto():
    """A protocol that broadcasts needs a socket of its own on a port of its own.
    Opening one for hardware nobody has is not a thing to do quietly."""
    auto = protocols.posting()

    assert all(not p.datagram for p in auto)
    assert any(p.datagram for p in protocols.registry())
    assert protocols.by_name('weatherflow') not in auto


def test_every_protocol_can_be_asked_for_by_name():
    for name in protocols.names():
        assert protocols.by_name(name) is not None
    assert protocols.by_name('nonesuch') is None


# ---------------------------------------------------------------- units


def test_the_unit_systems_are_the_numbers_weewx_uses():
    """protocols/ repeats them rather than importing weewx, so that a catalog can be
    exercised without WeeWX. This is what keeps the two from drifting apart."""
    weewx = pytest.importorskip('weewx', reason="WeeWX is not installed")

    assert protocols.US == weewx.US
    assert protocols.METRIC == weewx.METRIC
    assert protocols.METRICWX == weewx.METRICWX
