#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""Test the whole way from a captured payload to a WeeWX packet."""

import pytest

from ecowitt.mapping import Mapper


def test_a_real_payload_becomes_a_packet(payload):
    packet, _ = Mapper().to_packet(payload('hp2561ae_pro'))

    assert packet['outTemp'] == 59.7
    assert packet['inTemp'] == 75.4
    assert packet['outHumidity'] == 91.0
    assert packet['barometer'] == 29.920
    assert packet['windSpeed'] == 1.34
    assert packet['radiation'] == 207.36
    assert 'dateTime' in packet


def test_the_sensors_that_the_interceptor_drops(payload):
    """These are the fields an HP2561AE sends that weewx-interceptor throws away.

    The two WN34 channels and the WH52 temperature need a placement first, because
    that is the user's to give. Everything else arrives on its own.
    """
    placed = {'tf_ch1': 'extraTemp9', 'tf_ch2': 'extraTemp10',
              'soil_ec_temp1': 'soilTemp1'}
    packet, _ = Mapper(extensions=placed).to_packet(payload('hp2561ae_pro'))

    assert packet['extraTemp9'] == 66.2         # WN34, first channel
    assert packet['extraTemp10'] == 61.5        # WN34, second channel
    assert packet['soilMoist1'] == 30.0         # WH52, moisture, no decision needed
    assert packet['soilTemp1'] == 65.7          # WH52, temperature
    assert packet['lightning_distance'] == 1.0  # WH57
    assert packet['lightning_num'] == 0.0
    assert packet['vpd'] == 0.047


def test_batteries_land_on_the_fields_that_skins_read(payload):
    """A battery on outTempBatteryStatus shows up in a report. On wh65_batt it does not."""
    packet, _ = Mapper().to_packet(payload('hp2561ae_pro'))

    assert packet['outTempBatteryStatus'] == 0.0
    assert packet['lightning_Batt'] == 5.0


def test_identifiers_do_not_reach_the_packet(payload):
    packet, _ = Mapper().to_packet(payload('hp2561ae_pro'))

    for field in ('PASSKEY', 'model', 'stationtype', 'freq', 'heap', 'runtime'):
        assert field not in packet


def test_unknown_fields_are_reported(payload):
    _, guesses = Mapper().to_packet(payload('hp2561ae_pro'))

    assert {g.raw for g in guesses} == {'last24hrainin', 'yearlyrainin'}
    assert all(g.group == 'group_rain' for g in guesses)
    assert not any(g.certain for g in guesses)


def test_a_guess_is_reported_but_not_used(payload):
    """The default keeps a guess out of the database. A wrong unit is worse than a gap."""
    packet, guesses = Mapper().to_packet(payload('hp2561ae_pro'))

    assert guesses
    assert 'ecowitt_yearlyrainin' not in packet


def test_infer_all_takes_the_guess_too(payload):
    packet, _ = Mapper(infer_unknown='all').to_packet(payload('hp2561ae_pro'))

    assert packet['ecowitt_yearlyrainin'] == 0.020


def test_infer_off_reports_nothing_and_takes_nothing(payload):
    packet, guesses = Mapper(infer_unknown='off').to_packet(payload('hp2561ae_pro'))

    assert guesses          # still reported, so the log says what was left out
    assert 'ecowitt_yearlyrainin' not in packet


def test_a_derived_field_is_taken_by_default():
    """A series continued from the catalog is not a guess, so it goes in."""
    mapper = Mapper(fields={'zz_ch1': 'zzTemp1', 'zz_ch2': 'zzTemp2'},
                    groups={'zzTemp1': 'group_temperature'}, channels={})
    packet, guesses = mapper.to_packet('zz_ch3=66.2')

    assert packet['zzTemp3'] == 66.2
    assert guesses[0].certain is True


def test_a_channel_past_the_published_limit_is_not_taken():
    """Ecowitt says a WH51 stops at 16. A seventeenth is real, but worth a look."""
    packet, guesses = Mapper().to_packet('soilmoisture17=30')

    assert 'soilMoist17' not in packet
    assert guesses[0].certain is False
    assert 'past the 16' in guesses[0].why


def test_extensions_win_over_the_catalog(payload):
    mapper = Mapper(extensions={'yearlyrainin': 'rain_year', 'tempf': 'extraTemp8'})
    packet, guesses = mapper.to_packet(payload('hp2561ae_pro'))

    assert packet['rain_year'] == 0.020
    assert packet['extraTemp8'] == 59.7
    assert 'outTemp' not in packet
    assert {g.raw for g in guesses} == {'last24hrainin'}


def test_a_field_is_only_reported_once(payload):
    mapper = Mapper()
    first = mapper.to_packet(payload('hp2561ae_pro'))[1]
    second = mapper.to_packet(payload('hp2561ae_pro'))[1]

    assert first
    assert second == []


def test_unit_groups_grow_with_what_arrives():
    mapper = Mapper(fields={'zz_ch1': 'zzTemp1', 'zz_ch2': 'zzTemp2'},
                    groups={'zzTemp1': 'group_temperature'}, channels={})
    assert 'zzTemp3' not in mapper.wanted_groups()

    mapper.to_packet('zz_ch3=66.2')

    assert mapper.wanted_groups()['zzTemp3'] == 'group_temperature'


def test_bad_mode_is_refused():
    with pytest.raises(ValueError):
        Mapper(infer_unknown='sometimes')


def test_an_empty_payload_yields_only_a_timestamp():
    packet, guesses = Mapper().to_packet('')

    assert list(packet) == ['dateTime']
    assert guesses == []


def test_placement_is_flagged_for_multi_channel_sensors():
    """A WN34 is the same part whether it sits in a bed or a pool."""
    from ecowitt.mapping import placement_note

    assert placement_note('tf_ch1')
    assert placement_note('temp1f')
    assert placement_note('leafwetness_ch3')
    # The single outdoor sensor is not a channel, and not in question.
    assert placement_note('tempf') is None
    assert placement_note('humidity') is None


def test_a_channel_can_be_put_where_it_actually_is():
    """Channel 1 is a spike in the bed, channel 2 a lead in the pool."""
    mapper = Mapper(extensions={'tf_ch1': 'soilTemp3', 'tf_ch2': 'extraTemp5'})
    packet, _ = mapper.to_packet('tf_ch1=66.2&tf_ch2=78.4')

    assert packet['soilTemp3'] == 66.2
    assert packet['extraTemp5'] == 78.4
    assert 'extraTemp9' not in packet


def test_a_derived_channel_can_be_redirected_too():
    """What holds for the catalog holds for a channel the driver worked out."""
    mapper = Mapper(extensions={'zz_ch3': 'extraTemp6'},
                    fields={'zz_ch1': 'zzTemp1', 'zz_ch2': 'zzTemp2'},
                    groups={}, channels={})
    packet, guesses = mapper.to_packet('zz_ch3=78.4')

    assert packet['extraTemp6'] == 78.4
    assert guesses == []


def test_two_sensors_on_one_channel_are_flagged(caplog):
    """A WH51 and a WH52 should never send the same channel. If they do, say so."""
    import logging

    with caplog.at_level(logging.WARNING):
        packet, _ = Mapper().to_packet('soilmoisture3=30&soil_ec_hum3=45')

    assert 'One will overwrite the other' in caplog.text
    assert packet['soilMoist3'] in (30.0, 45.0)


def test_the_warning_is_said_once(caplog):
    import logging

    mapper = Mapper()
    with caplog.at_level(logging.WARNING):
        mapper.to_packet('soilmoisture3=30&soil_ec_hum3=45')
        caplog.clear()
        mapper.to_packet('soilmoisture3=31&soil_ec_hum3=46')

    assert caplog.text == ''


# A family whose placement is a convention, here with room left to grow. The shipped
# catalog has no such gap today, which is the point: this is what happens the day
# Ecowitt adds a channel to one.
AMBIGUOUS = {'temp1f': 'myTemp1', 'temp2f': 'myTemp2'}


def test_a_new_channel_of_an_ambiguous_family_waits_for_a_decision(caplog):
    """myTemp3 may already hold another sensor's history. Two series in one column
    cannot be told apart later, so this one waits to be confirmed."""
    import logging

    mapper = Mapper(fields=AMBIGUOUS, groups={'myTemp1': 'group_temperature'},
                    channels={})
    with caplog.at_level(logging.INFO):
        packet, guesses = mapper.to_packet('temp3f=66.2')

    assert 'myTemp3' not in packet
    assert guesses[0].certain is True       # derived, and still not taken
    assert 'field_map_extensions' in caplog.text


def test_an_unambiguous_new_channel_is_taken():
    """Nobody puts a laser rangefinder anywhere but where it measures."""
    mapper = Mapper(fields={'zz_ch1': 'zzDepth1', 'zz_ch2': 'zzDepth2'},
                    groups={'zzDepth1': 'group_distance'}, channels={})
    packet, guesses = mapper.to_packet('zz_ch3=1200')

    assert packet['zzDepth3'] == 1200.0
    assert guesses[0].certain is True


def test_the_suggested_line_is_ready_to_paste(caplog):
    import logging

    mapper = Mapper(fields=AMBIGUOUS, groups={}, channels={})
    with caplog.at_level(logging.INFO):
        mapper.to_packet('temp3f=66.2')

    assert "'temp3f = myTemp3'" in caplog.text


def test_a_contested_field_waits_for_the_user(caplog):
    """Where a WN34 sits is not something the hardware says, so nobody guesses."""
    import logging

    with caplog.at_level(logging.WARNING):
        packet, _ = Mapper().to_packet('tf_ch1=66.2&tempf=59.7')

    assert packet['outTemp'] == 59.7        # nothing to decide about that one
    assert 'extraTemp9' not in packet
    assert "'tf_ch1 = extraTemp9'" in caplog.text
    assert "'tf_ch1 = soilTemp1'" in caplog.text


def test_naming_it_settles_it():
    packet, _ = Mapper(extensions={'tf_ch1': 'soilTemp5'}).to_packet('tf_ch1=66.2')

    assert packet['soilTemp5'] == 66.2


def test_a_contested_field_is_said_once(caplog):
    import logging

    mapper = Mapper()
    with caplog.at_level(logging.WARNING):
        mapper.to_packet('tf_ch1=66.2')
        caplog.clear()
        mapper.to_packet('tf_ch1=66.3')

    assert caplog.text == ''


def test_the_hardware_settles_most_of_it(payload):
    """Only a handful of fields are ever in question. The rest just arrive.

    On a station with two WN34 probes, a WH52 and a lightning sensor: 29 readings
    arrive, 6 wait. Blocking is only bearable while it stays rare, which is why it
    is limited to what the hardware genuinely does not say.
    """
    mapper = Mapper()
    packet, _ = mapper.to_packet(payload('hp2561ae_pro'))

    assert len(packet) - 1 == 29        # less the timestamp
    assert len(mapper.warned) == 6
    assert packet['soilMoist1'] == 30.0
    assert packet['lightning_distance'] == 1.0
    assert packet['vpd'] == 0.047
