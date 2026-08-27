#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""What happens when something goes wrong.

A driver that raises inside the packet loop takes the process down with it. That
is not a theoretical concern: weewx-interceptor does exactly this on an HP2561AE,
where its rain mapping hits a KeyError on a field the station does not send, and
the engine restarts on every upload.

These pin down that one bad upload, one bad field or one bad parser costs one
packet, not the process.

**Where the line is.** In weewx-ecowitt the driver owns its socket, so its own
tests covered the size limit, the queue and the thread. Here the core owns all
of that -- see `ingest/listener.py` -- and the driver is handed a body and asked
for packets. So the half of these that tested a socket now tests the boundary
instead: the driver is given rubbish and must answer with no packets and no
exception, and when it does raise, the core must survive it. The socket half is
`tools/smoke.py` and `tools/netaccess_test.py`.
"""

import pytest
from ecowitt.driver import EcowittDriver

from ecowitt import mapping

FIXTURE_PASSKEY = '0000000000000000000000000000AAAA'


@pytest.fixture
def driver(tmp_path):
    made = EcowittDriver(passkey=FIXTURE_PASSKEY, report_file='',
                         console_file=str(tmp_path / 'consoles.txt'))
    yield made
    made.close()


def upload(driver, body):
    return driver.packets(body.encode('utf-8'), {'source': '192.168.1.42'})


def test_rubbish_costs_nothing(driver):
    """Every one of these has been seen on a real port. None is a reading."""
    for junk in ['', '%%%%', 'a' * 5000, 'tempf=abc', 'tempf=', '=', '&&&&',
                 'nosuchfield=1']:
        assert upload(driver, junk) == []

    assert upload(driver, 'PASSKEY=%s&tempf=62.0'
                  % FIXTURE_PASSKEY)[0].data['outTemp'] == 62.0


def test_an_upload_that_is_not_even_text(driver):
    """A port on a home network gets probed. None of it is UTF-8."""
    assert driver.packets(b'\xff\xfe\x00\x01\x80', {'source': 'x'}) == []
    assert driver.packets(b'', {'source': 'x'}) == []

    assert upload(driver, 'PASSKEY=%s&tempf=63.0'
                  % FIXTURE_PASSKEY)[0].data['outTemp'] == 63.0


def test_a_huge_upload_is_read_and_dropped(driver):
    """The core caps what it reads; whatever gets through must still be safe."""
    assert upload(driver, 'x' * 200000) == []

    assert upload(driver, 'PASSKEY=%s&tempf=64.0'
                  % FIXTURE_PASSKEY)[0].data['outTemp'] == 64.0


def test_a_parser_that_raises_costs_one_packet(driver, monkeypatch):
    """The interceptor's failure mode: KeyError on a field the station omits.

    The driver does not swallow it, on purpose -- a mapper that cannot map is
    a fault worth a line in the log, and the core writes that line. What must
    not happen is the next upload being lost too.
    """
    def explode(self, text, now=None):
        raise KeyError('totalrainin')

    monkeypatch.setattr(mapping.Mapper, 'to_packet', explode)
    with pytest.raises(KeyError):
        upload(driver, 'PASSKEY=%s&tempf=59.7' % FIXTURE_PASSKEY)

    monkeypatch.undo()
    assert upload(driver, 'PASSKEY=%s&tempf=61.0'
                  % FIXTURE_PASSKEY)[0].data['outTemp'] == 61.0


def test_the_core_survives_a_driver_that_raises(tmp_path, monkeypatch, caplog):
    """And the other half of it: the listener takes the fault, not the process.

    This is the whole reason the driver is allowed to raise at all. The core
    catches, counts, logs which driver it was, and still answers the console --
    a device that gets an error stops uploading, and the next measurement is
    worth more than the tidy status code.
    """
    import logging

    from weewx_evo.ingest import drivers, listener

    def explode(self, text, now=None):
        raise KeyError('totalrainin')

    made = EcowittDriver(passkey=FIXTURE_PASSKEY, report_file='',
                         console_file=str(tmp_path / 'consoles.txt'))
    registry = drivers.Registry()
    registry.register('ecowitt', made)
    ingest = listener.Ingest(_Nowhere(), token=None,
                             registry=registry)

    monkeypatch.setattr(mapping.Mapper, 'to_packet', explode)
    with caplog.at_level(logging.WARNING):
        stored, reason, response = ingest.submit(
            b'PASSKEY=%s&tempf=59.7' % FIXTURE_PASSKEY.encode(), '/', 'x')

    assert (stored, reason) == (0, 'unreadable')
    assert response[0], 'the console still gets what its protocol wants'
    assert 'could not read an upload' in caplog.text

    monkeypatch.undo()
    stored, reason, _ = ingest.submit(
        b'PASSKEY=%s&tempf=61.0' % FIXTURE_PASSKEY.encode(), '/', 'x')
    assert (stored, reason) == (1, 'ok')


class _Nowhere:
    """A store that accepts packets and keeps nothing.

    What is being checked is that the fault stops at the driver, so a real
    database here would only add a second thing that could fail.
    """

    keep_raw_seconds = 0

    def __init__(self):
        self.packets = []

    def add(self, packet, raw=None):
        self.packets.append(packet)
        return 1
