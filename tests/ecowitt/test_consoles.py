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

These came across from weewx-ecowitt, where the driver owns its own socket and
answers `genLoopPackets`. Here it does not: the core owns the socket and the
driver is handed a body. So they post nothing -- they call `packets()` -- and
what they check is the same either way.
"""

import logging
import os.path

import pytest
from ecowitt.driver import EcowittDriver
from ecowitt.protocol import station_id

from ecowitt import consoles

GARDEN = 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'
ROOF = 'BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB'


def upload(driver, body, client='192.168.1.42'):
    """One upload, as the core hands it over. Returns the packets it made."""
    return driver.packets(body.encode('utf-8'), {'source': client})


@pytest.fixture
def make_driver(tmp_path):
    """Drivers that keep their console list in a directory of their own."""
    made = []

    def _make(**options):
        options.setdefault('report_file', '')
        options.setdefault('console_file', str(tmp_path / 'consoles.txt'))
        driver = EcowittDriver(**options)
        made.append(driver)
        return driver

    yield _make

    for driver in made:
        driver.close()


class Memory:
    """The state a driver is given: get, set, delete on strings, and no more.

    Deliberately this small. The driver's job is producing packets, and a
    driver that can reach the archive is a driver that can write into it.
    """

    def __init__(self):
        self.values = {}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value

    def delete(self, key):
        self.values.pop(key, None)


# ---------------------------------------------------------------- identification


def test_what_identifies_a_console():
    assert station_id('PASSKEY=ABC&tempf=1') == 'ABC'
    assert station_id('ID=KX123&PASSWORD=y&tempf=1') == 'KX123'   # Wunderground
    assert station_id('tempf=1') == ''
    assert station_id('') == ''


# ---------------------------------------------------------------- learning one


def test_the_first_console_is_adopted(make_driver, caplog):
    driver = make_driver()
    with caplog.at_level(logging.INFO):
        packets = upload(driver, 'PASSKEY=%s&tempf=59.7' % GARDEN)

    assert packets[0].data['outTemp'] == 59.7
    assert GARDEN in driver.known
    assert GARDEN in driver.store.read()
    assert 'is now this driver' in caplog.text


def test_a_second_console_is_refused(make_driver, caplog):
    """The whole point: it cannot start writing into the first one's fields."""
    driver = make_driver(field_map_extensions={'tf_ch1': 'extraTemp9'})
    first = upload(driver, 'PASSKEY=%s&tf_ch1=66.0&tempf=59.7' % GARDEN)
    assert first[0].data['extraTemp9'] == 66.0

    with caplog.at_level(logging.WARNING):
        assert upload(driver, 'PASSKEY=%s&tf_ch1=41.2&tempf=71.0' % ROOF) == []
        again = upload(driver, 'PASSKEY=%s&tf_ch1=66.5&tempf=59.9' % GARDEN)

    assert again[0].data['extraTemp9'] == 66.5   # the known console, uninterrupted
    assert ROOF in caplog.text
    assert '[stations]' in caplog.text


def test_the_refusal_is_said_once(make_driver, caplog):
    driver = make_driver()
    upload(driver, 'PASSKEY=%s&tempf=59.7' % GARDEN)

    with caplog.at_level(logging.WARNING):
        upload(driver, 'PASSKEY=%s&tempf=71.0' % ROOF)
        upload(driver, 'PASSKEY=%s&tempf=60.0' % GARDEN)
        caplog.clear()
        upload(driver, 'PASSKEY=%s&tempf=71.1' % ROOF)
        upload(driver, 'PASSKEY=%s&tempf=60.1' % GARDEN)

    assert caplog.text == ''


def test_what_was_learned_survives_a_restart(make_driver):
    """A restart must not hand the station to whichever console speaks first."""
    first = make_driver()
    upload(first, 'PASSKEY=%s&tempf=59.7' % GARDEN)

    # A second driver on the same console file, as a restart would be. The other
    # console gets in first this time, and is still refused.
    second = make_driver(console_file=first.store.path)

    assert upload(second, 'PASSKEY=%s&tempf=71.0' % ROOF) == []
    assert upload(second, 'PASSKEY=%s&tempf=60.0' % GARDEN)[0].data['outTemp'] == 60.0
    assert second.known == {GARDEN}


def test_what_was_learned_survives_in_the_state(make_driver):
    """The same, through the core's state rather than a file of its own.

    This is the ordinary case in weewx-evo: the list lives in the archive's
    metadata, so it is in every backup of the readings it protects.
    """
    memory = Memory()
    first = make_driver(state=memory, console_file='/nowhere/at/all.txt')
    upload(first, 'PASSKEY=%s&tempf=59.7' % GARDEN)

    second = make_driver(state=memory, console_file='/nowhere/at/all.txt')

    assert second.known == {GARDEN}
    assert upload(second, 'PASSKEY=%s&tempf=71.0' % ROOF) == []


# ---------------------------------------------------------------- configured


def test_a_configured_passkey_needs_no_file(make_driver):
    driver = make_driver(passkey=GARDEN, console_file='/nowhere/at/all.txt')

    assert upload(driver, 'PASSKEY=%s&tempf=71.0' % ROOF) == []
    assert upload(driver, 'PASSKEY=%s&tempf=59.7' % GARDEN)[0].data['outTemp'] == 59.7
    assert driver.known == {GARDEN}


def test_named_consoles_each_keep_their_channels(make_driver):
    driver = make_driver(stations={
        'garden': {'passkey': GARDEN,
                   'field_map_extensions': {'tf_ch1': 'soilTemp1'}},
        'roof': {'passkey': ROOF,
                 'field_map_extensions': {'tf_ch1': 'extraTemp12'}},
    })
    garden = upload(driver, 'PASSKEY=%s&tf_ch1=66.0' % GARDEN)[0]
    roof = upload(driver, 'PASSKEY=%s&tf_ch1=41.2' % ROOF)[0]

    assert garden.source == 'garden'
    assert roof.source == 'roof'
    assert garden.data['soilTemp1'] == 66.0
    assert roof.data['extraTemp12'] == 41.2
    assert 'extraTemp12' not in garden.data


def test_a_station_without_a_passkey_is_refused(make_driver):
    with pytest.raises(ValueError):
        make_driver(stations={'garden': {'field_map_extensions': {}}})


def test_hardware_that_identifies_itself_with_nothing_still_works(make_driver):
    """Not every device sends a PASSKEY. One that does not is adopted as itself."""
    driver = make_driver()

    assert upload(driver, 'tempf=59.7')[0].data['outTemp'] == 59.7
    assert driver.known == {''}


# ---------------------------------------------------------------- the file


def test_the_file_explains_itself(tmp_path):
    path = str(tmp_path / 'consoles.txt')
    consoles._write_file(path, GARDEN, 'first console seen, from 192.168.1.42')
    text = open(path, encoding='utf-8').read()

    assert '[stations]' in text
    assert 'delete its line and restart' in text
    assert consoles.read(path) == [GARDEN]


def test_an_unwritable_file_does_not_stop_the_driver(make_driver, caplog):
    driver = make_driver(console_file='/nope/nowhere/consoles.txt')
    with caplog.at_level(logging.ERROR):
        packets = upload(driver, 'PASSKEY=%s&tempf=59.7' % GARDEN)

    assert packets[0].data['outTemp'] == 59.7      # readings still arrive
    assert 'Cannot record' in caplog.text


# ------------------------------------------------------------ kept in the state


def test_the_list_lives_in_the_state(tmp_path):
    """Where it belongs: with the readings it protects, in every backup of them."""
    path = str(tmp_path / 'consoles.txt')
    store = consoles.Store(path, state=Memory())

    assert store.add(GARDEN, 'first seen') == 'database'
    assert store.read() == [GARDEN]
    assert store.where == 'database'
    assert not os.path.exists(path)          # the file was never needed


def test_the_state_outlives_the_file(tmp_path):
    """The case that made this worth doing: the file is gone, the readings are not."""
    memory = Memory()
    path = str(tmp_path / 'consoles.txt')
    consoles.Store(path, state=memory).add(GARDEN)

    # A fresh driver, on a machine where only the archive was restored.
    later = consoles.Store(str(tmp_path / 'somewhere-else.txt'), state=memory)

    assert later.read() == [GARDEN]


def test_without_a_state_the_file_is_used(tmp_path):
    path = str(tmp_path / 'consoles.txt')
    store = consoles.Store(path, state=None, config_dict=None)

    assert store.add(GARDEN, 'first seen') == path
    assert store.read() == [GARDEN]
    assert store.where == 'file'


def test_a_second_console_is_added_to_what_is_there(tmp_path):
    store = consoles.Store(str(tmp_path / 'consoles.txt'), state=Memory())
    store.add(GARDEN)
    store.add(ROOF)

    assert sorted(store.read()) == sorted([GARDEN, ROOF])


def test_adding_the_same_console_twice_changes_nothing(tmp_path):
    store = consoles.Store(str(tmp_path / 'consoles.txt'), state=Memory())
    store.add(GARDEN)
    store.add(GARDEN)

    assert store.read() == [GARDEN]
