#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Test which columns a station turns out to need."""

import pytest

from ecowitt import columns
from ecowitt.mapping import Mapper

SCHEMA = {'dateTime', 'usUnits', 'interval', 'outTemp', 'soilTemp1', 'soilTemp2'}


def test_only_what_is_missing():
    packet = {'dateTime': 1, 'usUnits': 1, 'outTemp': 59.7,
              'soilTemp1': 66.2, 'soilTemp9': 61.5}

    assert columns.missing(packet, {}, known=SCHEMA) == [('soilTemp9', 'REAL')]


def test_counted_things_are_integers():
    packet = {'lightning_num': 0.0, 'lightning_time': 1787604643.0, 'vpd': 0.047}
    groups = {'lightning_num': 'group_count', 'lightning_time': 'group_time',
              'vpd': 'group_pressure'}

    assert columns.missing(packet, groups, known=SCHEMA) == [
        ('lightning_num', 'INTEGER'),
        ('lightning_time', 'INTEGER'),
        ('vpd', 'REAL'),
    ]


def test_a_real_station_needs_a_manageable_number(payload):
    """The point of doing this from a payload: a dozen columns, not four hundred."""
    mapper = Mapper()
    packet, _ = mapper.to_packet(payload('hp2561ae_pro'))
    wanted = columns.missing(packet, mapper.wanted_groups(), known=SCHEMA)

    assert len(wanted) < 40


def test_commands_are_ready_to_paste():
    lines = columns.commands([('soilTemp9', 'REAL')], config='/etc/weewx/weewx.conf')

    assert lines == ['weectl database add-column soilTemp9 --type REAL '
                     '--config=/etc/weewx/weewx.conf -y']


def test_the_standard_schema_is_what_we_compare_against():
    pytest.importorskip('weewx', reason="WeeWX is not installed")

    fields = columns.schema_fields()
    assert 'outTemp' in fields
    assert 'soilTemp4' in fields
    assert 'soilTemp9' not in fields


def test_occupied_needs_a_database():
    """Without one, the check says so rather than pretending everything is free."""
    pytest.importorskip('weewx', reason="WeeWX is not installed")

    with pytest.raises(Exception):
        columns.occupied('/nonexistent/weewx.conf')
