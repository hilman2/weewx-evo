#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Telling consoles apart, and giving each its own field map.

The driver used to decide which consoles were recorded: the first one heard
was adopted and everything else refused. That decision has moved to
`stations.toml`, where it covers every driver and where a console also gets a
name and an archive.

The refusal was wrong in a way that only showed with more than one archive.
`packets()` returned an empty list for a console it did not know, so no packet
reached the core, so the console did not appear as an unannounced stranger
either. Two consoles at two sites, and the second existed only in a log line.

What stays here is the part nothing else can do: two consoles both number
their channels from one, so `tf_ch1` is a different thermometer on each. That
is what a per-console field map is for.
"""

import pytest
from ecowitt.driver import EcowittDriver
from ecowitt.protocol import station_id

GARDEN = 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'
ROOF = 'BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB'


def upload(driver, body, client='192.168.1.42'):
    """One upload, as the core hands it over. Returns the packets it made."""
    return driver.packets(body.encode('utf-8'), {'source': client})


@pytest.fixture
def make_driver():
    made = []

    def _make(**options):
        options.setdefault('report_file', '')
        driver = EcowittDriver(**options)
        made.append(driver)
        return driver

    yield _make

    for driver in made:
        driver.close()


# ---------------------------------------------------------------- identification


def test_what_identifies_a_console():
    assert station_id('PASSKEY=ABC&tempf=1') == 'ABC'
    assert station_id('ID=KX123&PASSWORD=y&tempf=1') == 'KX123'   # Wunderground
    assert station_id('tempf=1') == ''
    assert station_id('') == ''


def test_the_passkey_is_the_source(make_driver):
    """The hardware's own identity, not a name.

    The core turns it into a station name, so renaming a station does not mean
    touching this driver or the field maps hanging off it.
    """
    driver = make_driver()
    packet = upload(driver, 'PASSKEY=%s&tempf=68.4' % GARDEN)[0]

    assert packet.source == GARDEN


def test_every_console_is_recorded(make_driver):
    """No console is refused here. That is the core's decision now.

    This is the test the old arrangement could not pass: the second console
    produced nothing at all, which made it invisible rather than merely
    unrecorded.
    """
    driver = make_driver()
    garden = upload(driver, 'PASSKEY=%s&tempf=68.4' % GARDEN)
    roof = upload(driver, 'PASSKEY=%s&tempf=51.1' % ROOF)

    assert len(garden) == 1
    assert len(roof) == 1
    assert garden[0].source == GARDEN
    assert roof[0].source == ROOF
    assert sorted(driver.consoles) == sorted([GARDEN, ROOF])


def test_hardware_that_identifies_itself_with_nothing_still_works(make_driver):
    """Not every device sends a PASSKEY. One that does not still reports."""
    driver = make_driver()

    assert upload(driver, 'tempf=59.7')[0].data['outTemp'] == 59.7


# ---------------------------------------------------------------- field maps


def test_named_consoles_each_keep_their_channels(make_driver):
    """The reason per-console maps exist at all.

    Both consoles number their channels from one, so `tf_ch1` is a different
    sensor on each. Without a map per console one would overwrite the other in
    a column nothing afterwards could separate.
    """
    driver = make_driver(stations={
        'garden': {'passkey': GARDEN,
                   'field_map_extensions': {'tf_ch1': 'soilTemp1'}},
        'roof': {'passkey': ROOF,
                 'field_map_extensions': {'tf_ch1': 'extraTemp12'}},
    })
    garden = upload(driver, 'PASSKEY=%s&tf_ch1=66.0' % GARDEN)[0]
    roof = upload(driver, 'PASSKEY=%s&tf_ch1=41.2' % ROOF)[0]

    assert garden.data['soilTemp1'] == 66.0
    assert roof.data['extraTemp12'] == 41.2
    assert 'extraTemp12' not in garden.data
    # Both still identify themselves by what the hardware sends.
    assert garden.source == GARDEN
    assert roof.source == ROOF


def test_a_console_with_no_map_gets_the_default_one(make_driver):
    """A third console is read, not dropped, when two are mapped."""
    driver = make_driver(stations={
        'garden': {'passkey': GARDEN,
                   'field_map_extensions': {'tf_ch1': 'soilTemp1'}},
    })
    other = upload(driver, 'PASSKEY=%s&tempf=51.1' % ROOF)[0]

    assert other.source == ROOF
    assert other.data['outTemp'] == 51.1


def test_a_station_without_a_passkey_is_refused(make_driver):
    """A field map with nothing to hang on is a configuration error."""
    with pytest.raises(ValueError):
        make_driver(stations={'garden': {'field_map_extensions': {}}})
