#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""What happens when something goes wrong.

A driver that raises inside genLoopPackets takes WeeWX down with it. That is not a
theoretical concern: weewx-interceptor does exactly this on an HP2561AE, where its
rain mapping hits a KeyError on a field the station does not send, and the engine
restarts on every upload.

These tests pin down that one bad upload, one bad field or one bad parser costs one
packet, not the process.
"""

import http.client

import pytest

FIXTURE_PASSKEY = '0000000000000000000000000000AAAA'

weewx = pytest.importorskip('weewx', reason="WeeWX is not installed")

from ecowitt import mapping                                  # noqa: E402
from ecowitt.driver import EcowittDriver                     # noqa: E402


@pytest.fixture
def driver():
    made = EcowittDriver(port=0, address='127.0.0.1', passkey=FIXTURE_PASSKEY, report_file='')
    yield made
    made.closePort()


def post(driver, body, path='/'):
    connection = http.client.HTTPConnection('127.0.0.1', driver.listener.port,
                                            timeout=5)
    try:
        connection.request('POST', path, body)
        response = connection.getresponse()
        response.read()
        return response.status
    finally:
        connection.close()


def test_a_parser_that_raises_costs_one_packet(driver, monkeypatch):
    """The interceptor's failure mode: KeyError on a field the station omits."""

    def explode(self, text, now=None):
        raise KeyError('totalrainin')

    monkeypatch.setattr(mapping.Mapper, 'to_packet', explode)
    post(driver, 'PASSKEY=%s&tempf=59.7' % FIXTURE_PASSKEY)

    packets = driver.genLoopPackets()
    # The bad one is consumed and logged while the parser is still broken. Repairing
    # it and sending another shows the driver is still there.
    import threading
    def repair_and_send():
        monkeypatch.undo()
        post(driver, 'PASSKEY=%s&tempf=61.0' % FIXTURE_PASSKEY)
    threading.Timer(0.5, repair_and_send).start()

    assert next(packets)['outTemp'] == 61.0


def test_rubbish_costs_nothing(driver):
    for junk in ['', '%%%%', 'a' * 5000, 'tempf=abc', 'tempf=', '=', '&&&&',
                 'nosuchfield=1']:
        assert post(driver, junk) == 200

    post(driver, 'PASSKEY=%s&tempf=62.0' % FIXTURE_PASSKEY)
    assert next(driver.genLoopPackets())['outTemp'] == 62.0


def test_an_oversized_upload_is_refused_not_read(driver):
    assert post(driver, 'x' * 200000) == 413

    post(driver, 'PASSKEY=%s&tempf=63.0' % FIXTURE_PASSKEY)
    assert next(driver.genLoopPackets())['outTemp'] == 63.0


def test_a_response_that_raises_still_stores_the_reading():
    """The device gets an empty 200 rather than nothing at all."""
    made = EcowittDriver(port=0, address='127.0.0.1', passkey=FIXTURE_PASSKEY, report_file='',
                         response=lambda request: 1 / 0)
    try:
        assert post(made, 'PASSKEY=%s&tempf=64.0' % FIXTURE_PASSKEY) == 200
        assert next(made.genLoopPackets())['outTemp'] == 64.0
    finally:
        made.closePort()


def test_a_flood_drops_readings_rather_than_growing(driver):
    """An upload every eight seconds against a slow consumer must not eat memory."""
    for i in range(40):
        post(driver, 'tempf=%d' % (60 + i % 10))

    assert driver.listener.queue.qsize() <= driver.listener.queue_size
    assert driver.listener.dropped > 0


def test_the_listener_notices_when_its_thread_dies(driver):
    """A dead server thread must not look like a station that went quiet."""
    driver.listener.server.shutdown()
    while driver.listener.thread.is_alive():
        pass
    while not driver.listener.queue.empty():
        driver.listener.queue.get_nowait()

    with pytest.raises(weewx.WeeWxIOError):
        driver.listener.get(timeout=2)
