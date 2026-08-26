#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Test the report the driver leaves behind."""

from ecowitt import report
from ecowitt.mapping import Mapper
from ecowitt.protocol import redact


def test_the_passkey_is_replaced(payload):
    text = redact(payload('hp2561ae_pro'))

    assert 'PASSKEY=X' in text
    assert '0000000000000000000000000000AAAA' not in text
    assert 'tempf=59.7' in text          # the weather survives


def test_a_wunderground_login_is_replaced():
    text = redact('ID=KX1234&PASSWORD=hunter2&tempf=61.0')

    assert text == 'ID=X&PASSWORD=X&tempf=61.0'


def test_the_report_carries_what_an_issue_needs(tmp_path, payload):
    raw = payload('hp2561ae_pro')
    mapper = Mapper()
    _, guesses = mapper.to_packet(raw)
    waiting = {r: f for r, f in mapper.undecided.items() if r in mapper.warned}

    path = report.write(raw, guesses, waiting, str(tmp_path / 'report.txt'))
    text = open(path, encoding='utf-8').read()

    assert 'weewx-ecowitt' in text
    assert 'PASSKEY=X' in text
    assert 'tempinf=75.4' in text                     # the upload itself
    assert 'issues/new' in text                       # where to send it
    assert 'yearlyrainin' in text                     # what could not be placed
    assert 'tf_ch1' in text                           # what is waiting


def test_nothing_to_report_writes_nothing(tmp_path):
    assert report.write('tempf=59.7', [], {}, str(tmp_path / 'report.txt')) is None


def test_an_unwritable_path_is_survivable(payload):
    mapper = Mapper()
    _, guesses = mapper.to_packet(payload('hp2561ae_pro'))

    assert report.write('tempf=59.7', guesses, {}, '/nope/nowhere/report.txt') is None
