#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Test what happens to fields nobody has mapped yet."""

import pytest

from ecowitt import catalog, infer

CATALOG = {
    'tf_ch1': 'soilTemp1',
    'tf_ch2': 'soilTemp2',
    'tf_ch3': 'soilTemp3',
    'temp1f': 'extraTemp1',
    'temp2f': 'extraTemp2',
    'tempf': 'outTemp',
    'onlyone1': 'someField1',
}
GROUPS = {'soilTemp1': 'group_temperature', 'extraTemp1': 'group_temperature'}


@pytest.fixture
def inferrer():
    return infer.Inferrer(CATALOG, GROUPS)


def test_continues_a_series(inferrer):
    """tf_ch1 through tf_ch3 are soilTemp1 through soilTemp3, so tf_ch4 is soilTemp4."""
    guess = inferrer.guess('tf_ch4')

    assert guess.field == 'soilTemp4'
    assert guess.group == 'group_temperature'
    assert guess.certain is True
    assert 'continues tf_ch' in guess.why


def test_a_series_with_a_tail(inferrer):
    guess = inferrer.guess('temp7f')

    assert guess.field == 'extraTemp7'
    assert guess.certain is True


def test_one_example_is_not_a_series(inferrer):
    """A single member says nothing about how the family is numbered."""
    guess = inferrer.guess('onlyone2')

    assert guess is None or guess.certain is False


def test_a_rule_when_no_series_fits(inferrer):
    guess = inferrer.guess('windgust2mph')

    assert guess.certain is False
    assert guess.group == 'group_speed'
    assert guess.unit == 'mile_per_hour'
    assert guess.field == 'ecowitt_windgust2mph'


def test_nothing_can_be_said(inferrer):
    assert inferrer.guess('wizzlefrob') is None


def test_a_series_will_not_collide(inferrer):
    """If the derived name is already taken, fall back rather than overwrite."""
    crowded = infer.Inferrer({'tf_ch1': 'soilTemp1', 'tf_ch2': 'soilTemp2',
                              'other': 'soilTemp3'})
    guess = crowded.guess('tf_ch3')

    assert guess.field != 'soilTemp3'
    assert guess.certain is False


def test_an_inconsistent_family_is_not_a_series():
    """Two members that disagree about the offset are not a pattern."""
    confused = infer.Inferrer({'x1': 'y1', 'x2': 'y5'})

    assert confused.guess('x3') is None


def test_a_channel_past_the_end_of_the_family_is_not_derived():
    """Ecowitt says a WH51 stops at 16. A seventeenth is real, but not routine."""
    inferrer = infer.Inferrer(catalog.FIELDS, catalog.GROUPS, catalog.CHANNELS)
    guess = inferrer.guess('soilmoisture17')

    assert guess.field == 'soilMoist17'
    assert guess.certain is False
    assert 'past the 16 a WH51' in guess.why


def test_a_channel_within_the_family_is_derived():
    """Without a published limit, the series is all there is to go on."""
    inferrer = infer.Inferrer({'zz_ch1': 'zzTemp1', 'zz_ch2': 'zzTemp2'},
                              {'zzTemp1': 'group_temperature'}, catalog.CHANNELS)
    guess = inferrer.guess('zz_ch3')

    assert guess.field == 'zzTemp3'
    assert guess.certain is True


def test_report_reads_like_something_a_person_can_act_on(inferrer):
    lines = infer.report([inferrer.guess('tf_ch4'), inferrer.guess('windgust2mph')])

    assert 'tf_ch4' in lines[0] and 'soilTemp4' in lines[0] and 'derived' in lines[0]
    assert 'guessed' in lines[1]
