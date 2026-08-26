#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Which consoles the driver answers to.

Anyone who can reach the port can point a console at it, and two consoles number
their channels from one. So the driver answers to the consoles it knows and refuses
the rest, rather than working out from the readings who is who. That cannot be made
to work: a station uploading every eight seconds owns every field for a minute
before anyone knows a sixty-second one exists.
"""

import http.client
import os.path

import pytest

weewx = pytest.importorskip('weewx', reason="WeeWX is not installed")

from ecowitt import consoles                        # noqa: E402
from ecowitt.driver import EcowittDriver            # noqa: E402
from ecowitt.protocol import station_id             # noqa: E402

GARDEN = 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'
ROOF = 'BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB'


def post(driver, body):
    connection = http.client.HTTPConnection('127.0.0.1', driver.listener.port, timeout=5)
    try:
        connection.request('POST', '/', body)
        connection.getresponse().read()
    finally:
        connection.close()


@pytest.fixture
def make_driver(tmp_path):
    """Drivers that keep their console list in a directory of their own."""
    made = []

    def _make(**options):
        options.setdefault('port', 0)
        options.setdefault('address', '127.0.0.1')
        options.setdefault('report_file', '')
        options.setdefault('console_file', str(tmp_path / 'consoles.txt'))
        driver = EcowittDriver(**options)
        made.append(driver)
        return driver

    yield _make

    for driver in made:
        driver.closePort()


# ---------------------------------------------------------------- identification


def test_what_identifies_a_console():
    assert station_id('PASSKEY=ABC&tempf=1') == 'ABC'
    assert station_id('ID=KX123&PASSWORD=y&tempf=1') == 'KX123'   # Wunderground
    assert station_id('tempf=1') == ''
    assert station_id('') == ''


# ---------------------------------------------------------------- learning one


def test_the_first_console_is_adopted(make_driver, caplog):
    import logging

    driver = make_driver()
    with caplog.at_level(logging.INFO):
        post(driver, 'PASSKEY=%s&tempf=59.7' % GARDEN)
        packet = next(driver.genLoopPackets())

    assert packet['outTemp'] == 59.7
    assert GARDEN in driver.known
    assert GARDEN in driver.store.read()
    assert 'is now this driver' in caplog.text


def test_a_second_console_is_refused(make_driver, caplog):
    """The whole point: it cannot start writing into the first one's fields."""
    import logging

    driver = make_driver(field_map_extensions={'tf_ch1': 'extraTemp9'})
    packets = driver.genLoopPackets()
    post(driver, 'PASSKEY=%s&tf_ch1=66.0&tempf=59.7' % GARDEN)
    assert next(packets)['extraTemp9'] == 66.0

    with caplog.at_level(logging.WARNING):
        post(driver, 'PASSKEY=%s&tf_ch1=41.2&tempf=71.0' % ROOF)
        post(driver, 'PASSKEY=%s&tf_ch1=66.5&tempf=59.9' % GARDEN)
        arrived = next(packets)

    assert arrived['extraTemp9'] == 66.5      # the known console, uninterrupted
    assert ROOF in caplog.text
    assert '[[stations]]' in caplog.text


def test_the_refusal_is_said_once(make_driver, caplog):
    import logging

    driver = make_driver()
    packets = driver.genLoopPackets()
    post(driver, 'PASSKEY=%s&tempf=59.7' % GARDEN)
    next(packets)

    with caplog.at_level(logging.WARNING):
        post(driver, 'PASSKEY=%s&tempf=71.0' % ROOF)
        post(driver, 'PASSKEY=%s&tempf=60.0' % GARDEN)
        next(packets)
        caplog.clear()
        post(driver, 'PASSKEY=%s&tempf=71.1' % ROOF)
        post(driver, 'PASSKEY=%s&tempf=60.1' % GARDEN)
        next(packets)

    assert caplog.text == ''


def test_what_was_learned_survives_a_restart(make_driver):
    """A restart must not hand the station to whichever console speaks first."""
    first = make_driver()
    post(first, 'PASSKEY=%s&tempf=59.7' % GARDEN)
    next(first.genLoopPackets())

    # A second driver on the same console file, as a restart would be. The other
    # console gets in first this time, and is still refused.
    second = make_driver(console_file=first.console_file)
    packets = second.genLoopPackets()
    post(second, 'PASSKEY=%s&tempf=71.0' % ROOF)
    post(second, 'PASSKEY=%s&tempf=60.0' % GARDEN)

    assert next(packets)['outTemp'] == 60.0
    assert second.known == {GARDEN}


# ---------------------------------------------------------------- configured


def test_a_configured_passkey_needs_no_file(make_driver):
    driver = make_driver(passkey=GARDEN, console_file='/nowhere/at/all.txt')
    packets = driver.genLoopPackets()
    post(driver, 'PASSKEY=%s&tempf=71.0' % ROOF)
    post(driver, 'PASSKEY=%s&tempf=59.7' % GARDEN)

    assert next(packets)['outTemp'] == 59.7
    assert driver.known == {GARDEN}


def test_named_consoles_each_keep_their_channels(make_driver):
    driver = make_driver(stations={
        'garden': {'passkey': GARDEN,
                   'field_map_extensions': {'tf_ch1': 'soilTemp1'}},
        'roof': {'passkey': ROOF,
                 'field_map_extensions': {'tf_ch1': 'extraTemp12'}},
    })
    post(driver, 'PASSKEY=%s&tf_ch1=66.0' % GARDEN)
    post(driver, 'PASSKEY=%s&tf_ch1=41.2' % ROOF)

    packets = driver.genLoopPackets()
    readings = {p['station']: p for p in (next(packets), next(packets))}

    assert readings['garden']['soilTemp1'] == 66.0
    assert readings['roof']['extraTemp12'] == 41.2
    assert 'extraTemp12' not in readings['garden']


def test_a_station_without_a_passkey_is_refused(make_driver):
    with pytest.raises(ValueError):
        make_driver(stations={'garden': {'field_map_extensions': {}}})


def test_hardware_that_identifies_itself_with_nothing_still_works(make_driver):
    """Not every device sends a PASSKEY. One that does not is adopted as itself."""
    driver = make_driver()
    post(driver, 'tempf=59.7')

    assert next(driver.genLoopPackets())['outTemp'] == 59.7
    assert driver.known == {''}


# ---------------------------------------------------------------- the file


def test_the_file_explains_itself(tmp_path):
    path = str(tmp_path / 'consoles.txt')
    consoles._write_file(path, GARDEN, 'first console seen, from 192.168.1.42')
    text = open(path, encoding='utf-8').read()

    assert '[[stations]]' in text
    assert 'delete its line and restart' in text
    assert consoles.read(path) == [GARDEN]


def test_an_unwritable_file_does_not_stop_the_driver(make_driver, caplog):
    import logging

    driver = make_driver(console_file='/nope/nowhere/consoles.txt')
    with caplog.at_level(logging.ERROR):
        post(driver, 'PASSKEY=%s&tempf=59.7' % GARDEN)
        packet = next(driver.genLoopPackets())

    assert packet['outTemp'] == 59.7      # readings still arrive
    assert 'Cannot record' in caplog.text


# ------------------------------------------------------- kept in the database


@pytest.fixture
def database(tmp_path):
    """A real WeeWX database, so the metadata path is exercised, not mocked."""
    import weewx.manager

    config = {
        'WEEWX_ROOT': str(tmp_path),
        'DatabaseTypes': {
            'SQLite': {'driver': 'weedb.sqlite', 'SQLITE_ROOT': str(tmp_path)}},
        'Databases': {
            'archive_sqlite': {'database_name': 'test.sdb',
                               'database_type': 'SQLite'}},
        'DataBindings': {
            'wx_binding': {'database': 'archive_sqlite',
                           'table_name': 'archive',
                           'manager': 'weewx.manager.DaySummaryManager',
                           'schema': 'schemas.wview_extended.schema'}},
    }
    with weewx.manager.open_manager_with_config(config, 'wx_binding',
                                                initialize=True):
        pass
    return config


def test_the_list_lives_in_the_database(tmp_path, database):
    """Where it belongs: with the readings it protects, in every backup of them."""
    path = str(tmp_path / 'consoles.txt')
    store = consoles.Store(path, database)

    assert store.add(GARDEN, 'first seen') == 'database'
    assert store.read() == [GARDEN]
    assert store.where == 'database'
    assert not os.path.exists(path)          # the file was never needed


def test_the_database_outlives_the_file(tmp_path, database):
    """The case that made this worth doing: the file is gone, the readings are not."""
    path = str(tmp_path / 'consoles.txt')
    consoles.Store(path, database).add(GARDEN)

    # A fresh driver, on a machine where only the database was restored.
    later = consoles.Store(str(tmp_path / 'somewhere-else.txt'), database)

    assert later.read() == [GARDEN]


def test_without_a_database_the_file_is_used(tmp_path):
    path = str(tmp_path / 'consoles.txt')
    store = consoles.Store(path, config_dict=None)

    assert store.add(GARDEN, 'first seen') == path
    assert store.read() == [GARDEN]
    assert store.where == 'file'


def test_a_second_console_is_added_to_what_is_there(tmp_path, database):
    store = consoles.Store(str(tmp_path / 'consoles.txt'), database)
    store.add(GARDEN)
    store.add(ROOF)

    assert sorted(store.read()) == sorted([GARDEN, ROOF])


def test_adding_the_same_console_twice_changes_nothing(tmp_path, database):
    store = consoles.Store(str(tmp_path / 'consoles.txt'), database)
    store.add(GARDEN)
    store.add(GARDEN)

    assert store.read() == [GARDEN]
