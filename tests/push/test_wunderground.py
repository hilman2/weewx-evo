#
#    Copyright (c) 2026 Manuel Hilgert
#
#    See the file LICENSE for your full rights.
#
"""The Weather Underground protocol, from captured uploads.

Every payload here came off real hardware. Four of them are in the interceptor driver
by Matthew Wall, which is where they were captured; the specification they are checked
against is in fixtures/wunderground/spec.txt.

The point of these tests is the fields a driver quietly loses. `baromin`, `rainin`,
`indoortempf`, `indoorhumidity` and `UV` are not in the Ecowitt catalog, so a station
speaking this protocol would arrive with no pressure, no indoor readings and no UV,
and nothing anywhere would say so.
"""

import re

import pytest

from helpers import read
from ultimatepush import protocols, transport
from ultimatepush.catalogs import wunderground as catalog

WU = protocols.by_name('wunderground')


def packet_of(text, **kwargs):
    """The packet, the dialect and the guesses, as the driver would produce them."""
    return read('wunderground', text, **kwargs)


# ---------------------------------------------------------------- the spec


def spec_field_names(text):
    """Every parameter the specification names, read out of it rather than retyped.

    The list runs from 'list of fields:' to the worked example, one 'name - meaning'
    per line, with the sensors beyond the first of a family on continuation lines that
    begin with a star or a plus. Both shapes are taken.
    """
    body = text.split('list of fields:', 1)[1].split('Example URL', 1)[0]
    names = set()
    for line in body.splitlines():
        line = line.strip()
        match = re.match(r'^([A-Za-z][\w.\-]*)\s*-', line)
        if match:
            names.add(match.group(1))
        elif line.startswith(('*', '+')):
            # e.g. "* for sensors 2,3,4 use soiltemp2f, soiltemp3f, and soiltemp4f"
            names.update(re.findall(r'\b([a-z]+\d+[a-z]*)\b', line))
    return names


def test_every_field_the_specification_names_is_in_the_catalog(payload):
    """The catalog is derived from the specification, so this is what checks it.

    Not the other way round. The catalog is deliberately larger, because Fine Offset
    firmwares send more than the specification describes on the same endpoint.
    """
    named = spec_field_names(payload('wunderground/spec'))
    # The ones that identify the upload rather than measure anything, plus the two
    # free-text ones, which are not readings.
    named -= {'action', 'ID', 'PASSWORD', 'dateutc', 'weather', 'clouds',
              'softwaretype'}

    missing = named - set(catalog.FIELDS)
    assert not missing, "the specification names these and the catalog does not: %s" \
                        % ', '.join(sorted(missing))
    assert len(named) > 40, "the specification was not read properly"


def test_the_specification_is_the_one_this_was_written_from(payload):
    text = payload('wunderground/spec')

    assert 'updateweatherstation.php' in text
    assert 'RapidFire' in text
    assert '"success"' in text


# ---------------------------------------------------------------- imperial


def test_an_observer_upload_keeps_what_other_drivers_drop(payload):
    packet, dialect, _ = packet_of(payload('wunderground/observer_imperial'))

    assert dialect.units == protocols.US
    assert packet['barometer'] == 29.05      # baromin, absent from the Ecowitt catalog
    assert packet['inTemp'] == 76.5          # indoortempf, likewise
    assert packet['inHumidity'] == 49.0      # indoorhumidity, likewise
    assert packet['hourRain'] == 0.0         # rainin, the last 60 minutes
    assert packet['UV'] == 0.0               # capitalised, likewise
    assert packet['outTemp'] == 43.3
    assert packet['yearRain'] == 0.91


def test_the_device_computed_values_do_not_displace_weewx_own(payload):
    """WeeWX derives dewpoint and windchill in StdWXCalculate. What the console made
    of them is kept beside those, not over them."""
    packet, _, _ = packet_of(payload('wunderground/observer_imperial'))

    assert packet['fdewptf'] == 42.8
    assert packet['fwindchillf'] == 43.3
    assert 'dewpoint' not in packet
    assert 'windchill' not in packet


def test_an_ecowitt_console_in_wunderground_mode(payload):
    """An HP2550 set to protocol Wunderground. Same hardware, different vocabulary."""
    packet, _, _ = packet_of(payload('wunderground/easyweather_hp2550'))

    assert packet['outTemp'] == 55.2
    assert packet['soilMoist1'] == 52.0      # soilmoisture, no channel number
    assert packet['pm2_5'] == 309.0          # AqPM2.5, a name with a dot in it
    assert packet['barometer'] == 29.729
    assert packet['pressure'] == 29.729      # absbaromin, sent as well


# ---------------------------------------------------------------- missing values


def test_minus_9999_is_a_gap_and_not_a_reading(payload):
    """Fine Offset firmwares say this when a sensor has nothing to report.

    Read as a number it is nine thousand degrees below freezing, and it would go
    straight into the archive and into every average computed from it.
    """
    packet, _, _ = packet_of(payload('wunderground/missing_values'))

    assert packet['outTemp'] is None
    assert packet['outHumidity'] is None
    assert packet['windSpeed'] is None
    assert packet['radiation'] is None
    # The sensors that were working are unaffected.
    assert packet['inTemp'] == 66.2
    assert packet['barometer'] == 29.94


# ---------------------------------------------------------------- metric dialect


def test_the_metric_dialect_is_recognised_by_its_names(payload):
    """Same endpoint, same credentials, different catalog and different units."""
    packet, dialect, _ = packet_of(payload('wunderground/observer_metric'))

    assert dialect.name == 'wunderground/metric'
    assert dialect.units == protocols.METRIC
    assert packet['inTemp'] == 22.8          # intemp, Celsius
    assert packet['outTemp'] == 1.4
    assert packet['pressure'] == 1009.5      # absbaro, hPa
    assert packet['barometer'] == 1033.4     # relbaro


def test_the_metric_dialect_converts_rain_to_what_weewx_metric_keeps(payload):
    """The console sends millimetres. weewx.METRIC keeps centimetres."""
    packet, _, _ = packet_of(payload('wunderground/observer_metric'))

    assert packet['weekRain'] == pytest.approx(1.05)     # 10.5 mm
    assert packet['monthRain'] == pytest.approx(1.05)


def test_uv_is_not_an_index_in_the_metric_dialect(payload):
    """The same name means two different things.

    Imperial UV is the index, 0 to about 12. Metric UV is the raw irradiance in
    microwatts per square centimetre, which is why captured uploads carry 919. Put
    into a column reports render as an index it would be forty times too large, so it
    gets a column of its own and its own unit.
    """
    packet, _, _ = packet_of(payload('wunderground/observer_metric'))

    assert 'UV' not in packet
    assert packet['uvradiation'] == pytest.approx(0.38)  # 38 uW/cm2 -> W/m2
    assert packet['luminosity'] == 1724.9                # light, lux


def test_the_two_dialects_never_look_like_each_other(payload):
    """Decided on names, not on values, so no reading has to be plausible."""
    assert not set(catalog.METRIC_MARKERS) & set(catalog.FIELDS)
    imperial = transport.parse(payload('wunderground/observer_imperial'))
    metric = transport.parse(payload('wunderground/observer_metric'))

    assert not WU.dialect(imperial).name.endswith('metric')
    assert WU.dialect(metric).name.endswith('metric')


def test_the_wind_unit_of_the_metric_dialect_can_be_said(payload):
    """It cannot be read off a payload, and being wrong about it is wrong by 3.6."""
    raw = transport.parse(payload('wunderground/observer_metric'))
    try:
        WU.metric_wind = 'mps'
        assert WU.dialect(raw).units == protocols.METRICWX
        # METRICWX already keeps rain in millimetres, so nothing is converted.
        assert 'dailyrain' not in WU.dialect(raw).scale
    finally:
        WU.metric_wind = 'kph'
    assert WU.dialect(raw).units == protocols.METRIC


# ---------------------------------------------------------------- baromin


def test_baromin_is_sea_level_pressure_for_almost_everything(payload):
    packet, _, _ = packet_of(payload('wunderground/observer_imperial'))

    assert packet['barometer'] == 29.05
    assert 'pressure' not in packet


def test_the_two_firmwares_that_mean_station_pressure_say_so(payload):
    """Nothing else in the payload distinguishes them, but they name themselves.

    Getting this wrong is a station's whole pressure series recorded as the wrong
    quantity, and it looks entirely plausible until somebody compares it with a
    neighbour's.
    """
    text = payload('wunderground/observer_imperial').replace(
        'Weather%20logger%20V2.1.9', 'WH2650A_V1.2.1')
    packet, _, _ = packet_of(text)

    assert packet['pressure'] == 29.05
    assert 'barometer' not in packet


def test_a_users_own_mapping_outranks_the_firmware(payload):
    """Naming a field yourself is a decision. A default is not."""
    text = payload('wunderground/observer_imperial').replace(
        'Weather%20logger%20V2.1.9', 'WH2650A_V1.2.1')
    packet, _, _ = packet_of(text, extensions={'baromin': 'barometer'})

    assert packet['barometer'] == 29.05


# ---------------------------------------------------------------- pollution


def test_pollution_arrives_in_the_unit_weewx_keeps_the_column_in():
    """The specification gives some of these in ppb. group_fraction is ppm."""
    packet, _, _ = packet_of('ID=K1&PASSWORD=x&AqSO2=1200&AqCO=1.5&AqPM10=42'
                             '&AqOZONE=35&AqNO2=800')

    assert packet['so2'] == pytest.approx(1.2)    # 1200 ppb
    assert packet['co'] == 1.5                    # already ppm
    assert packet['o3'] == pytest.approx(0.035)   # 35 ppb
    assert packet['pm10_0'] == 42.0               # ug/m3, no conversion
    assert packet['no2'] == 800.0                 # ug/m3 in WeeWX, no conversion
