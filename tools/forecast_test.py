#!/usr/bin/env python3
"""The forecast sources and the store, without touching the network.

Every fixture here is a cut-down copy of a real response -- the field names,
the namespaces and the encodings are exactly what the services send, because
those are what the parsing gets wrong.

What this is actually checking is the arithmetic and the two failure modes
that matter:

  * **Kelvin.** MOSMIX publishes `287.35`, not `14.2`. Reading one as Celsius
    gives a forecast of 287 degrees; getting the conversion backwards gives
    one of -259.
  * **The daily timestamp.** Open-Meteo stamps a day as local midnight
    expressed in UTC. Subtracting the offset is what makes "Thursday" mean
    Thursday in Berlin instead of starting at two in the morning.
  * **A failed fetch keeps the old forecast.** A network hiccup must not turn
    into a blank page.
  * **An empty warning feed clears the warnings.** Calm weather is an answer,
    and leaving an expired storm warning up is the one failure here that
    would actually hurt somebody.

    python tools/forecast_test.py
"""

from __future__ import annotations

import sys
import tempfile
import time
import zipfile
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from weewx_evo import units
from weewx_evo.forecast import (
    Day,
    ForecastError,
    Moment,
    Place,
    Reading,
    Warning,
    codes,
    dwd,
    meteoalarm,
    nws,
    openmeteo,
)
from weewx_evo.forecast.runner import Scheduled
from weewx_evo.forecast.store import ForecastStore

FAILURES: list[str] = []
CHECKS = 0


def check(what: str, got: object, want: object) -> None:
    global CHECKS
    CHECKS += 1
    if got != want:
        FAILURES.append(f"{what}\n    got  {got!r}\n    want {want!r}")


def ok(what: str, condition: bool) -> None:
    check(what, bool(condition), True)


def close(what: str, got: float | None, want: float, tolerance: float = 0.05) -> None:
    global CHECKS
    CHECKS += 1
    if got is None or abs(got - want) > tolerance:
        FAILURES.append(f"{what}\n    got  {got!r}\n    want {want} +/- {tolerance}")


# ---------------------------------------------------------------------------
# Open-Meteo.
# ---------------------------------------------------------------------------

OPEN_METEO = {
    "latitude": 48.4, "longitude": 11.7, "utc_offset_seconds": 7200,
    "timezone": "Europe/Berlin", "generationtime_ms": 0.5,
    "hourly": {
        "time": [1787781600, 1787785200, 1787788800],
        "temperature_2m": [20.1, 19.6, None],
        "dew_point_2m": [14.2, 14.0, 13.8],
        "relative_humidity_2m": [68, 71, 74],
        "pressure_msl": [1015.8, 1015.6, 1015.2],
        "wind_speed_10m": [3.2, 2.8, 2.1],
        "wind_direction_10m": [245, 250, 255],
        "wind_gusts_10m": [7.1, 6.4, 5.2],
        "precipitation": [0.0, 0.2, 1.4],
        "precipitation_probability": [5, 20, 60],
        "weather_code": [2, 61, 63],
        "visibility": [24140.0, 18000.0, 9000.0],
        "cloud_cover": [40, 75, 95],
    },
    "daily": {
        # Local midnight expressed as UTC: 1787788800 is 2026-08-27T00:00Z,
        # and the day in Berlin starts two hours earlier in absolute terms.
        "time": [1787788800, 1787875200],
        "temperature_2m_max": [31.5, 28.4],
        "temperature_2m_min": [16.6, 17.2],
        "precipitation_sum": [0.0, 4.2],
        "sunrise": [1787806920, 1787893380],
        "sunset": [1787857260, 1787943540],
        "weather_code": [2, 63],
    },
}


def test_open_meteo() -> None:
    got = openmeteo.OpenMeteo().read(OPEN_METEO)
    check("three hours", len(got.hours), 3)
    first = got.hours[0]
    check("the timestamp is taken as it is", first.dateTime, 1787781600)
    check("metric", first.usUnits, units.METRICWX)
    close("temperature", first.outTemp, 20.1)
    close("wind", first.windSpeed, 3.2)
    check("the weather code", first.code, 2)
    # Metres from them, kilometres in METRICWX. A page showing 24140 km of
    # visibility is the failure this converts away.
    close("visibility in kilometres", first.visibility, 24.14)
    # A null in one column must not shift the others or become a zero.
    ok("a missing temperature is missing", got.hours[2].outTemp is None)
    close("while its neighbours are intact", got.hours[2].rain, 1.4)

    check("two days", len(got.days), 2)
    # This is the one. Their daily stamp is local midnight written as UTC, so
    # the offset comes off to get the actual instant. Without it a "day" in
    # Berlin starts at 02:00 and every daily figure is keyed to the wrong
    # date for two hours -- which flips at the daylight-saving boundary.
    check("the day starts at local midnight",
          got.days[0].dateTime, 1787788800 - 7200)
    close("the maximum", got.days[0].tempMax, 31.5)
    # Sunrise and sunset are instants, not dates: they are already right.
    check("sunrise is left alone", got.days[0].sunrise, 1787806920)


def test_open_meteo_asks_for_what_it_reads() -> None:
    """Every field the reader knows has to be in the request.

    A variable dropped from the query is a column that is silently always
    absent, and nothing else notices: the page just never shows wind gusts.
    """
    path = openmeteo.OpenMeteo().path(Place(latitude=48.4, longitude=11.7))
    for theirs, _ours in openmeteo.HOURLY:
        ok(f"the request asks for {theirs}", theirs in path)
    for theirs, _ours in openmeteo.DAILY:
        ok(f"the request asks for daily {theirs}", theirs in path)
    ok("in unix time", "timeformat=unixtime" in path)
    # Still needed with unix time: it decides where a day starts.
    ok("with a timezone, which decides where a day starts",
       "timezone=auto" in path)
    ok("metric wind", "wind_speed_unit=ms" in path)


# ---------------------------------------------------------------------------
# MOSMIX.
# ---------------------------------------------------------------------------

MOSMIX = """<?xml version="1.0" encoding="ISO-8859-1"?>
<kml:kml xmlns:dwd="https://opendata.dwd.de/weather/lib/pointforecast_dwd_extension_V1_0.xsd"
         xmlns:kml="http://www.opengis.net/kml/2.2">
  <kml:Document>
    <kml:ExtendedData>
      <dwd:ProductDefinition>
        <dwd:IssueTime>2026-08-27T03:00:00.000Z</dwd:IssueTime>
        <dwd:ForecastTimeSteps>
          <dwd:TimeStep>2026-08-27T04:00:00.000Z</dwd:TimeStep>
          <dwd:TimeStep>2026-08-27T05:00:00.000Z</dwd:TimeStep>
          <dwd:TimeStep>2026-08-27T06:00:00.000Z</dwd:TimeStep>
        </dwd:ForecastTimeSteps>
      </dwd:ProductDefinition>
    </kml:ExtendedData>
    <kml:Placemark>
      <kml:name>10870</kml:name>
      <kml:description>MUENCHEN-FL.</kml:description>
      <kml:ExtendedData>
        <dwd:Forecast dwd:elementName="TTT">
          <dwd:value>      287.35     288.45          -</dwd:value>
        </dwd:Forecast>
        <dwd:Forecast dwd:elementName="Td">
          <dwd:value>      281.15     281.35     281.55</dwd:value>
        </dwd:Forecast>
        <dwd:Forecast dwd:elementName="PPPP">
          <dwd:value>   101580.00  101550.00  101520.00</dwd:value>
        </dwd:Forecast>
        <dwd:Forecast dwd:elementName="FF">
          <dwd:value>        3.20       2.80       2.10</dwd:value>
        </dwd:Forecast>
        <dwd:Forecast dwd:elementName="DD">
          <dwd:value>      245.00     250.00     255.00</dwd:value>
        </dwd:Forecast>
        <dwd:Forecast dwd:elementName="Rad1h">
          <dwd:value>        0.00     360.00    1800.00</dwd:value>
        </dwd:Forecast>
        <dwd:Forecast dwd:elementName="VV">
          <dwd:value>    24140.00   18000.00    9000.00</dwd:value>
        </dwd:Forecast>
        <dwd:Forecast dwd:elementName="ww">
          <dwd:value>        2.00      61.00      63.00</dwd:value>
        </dwd:Forecast>
      </kml:ExtendedData>
    </kml:Placemark>
  </kml:Document>
</kml:kml>
"""


def test_mosmix() -> None:
    got = dwd.Mosmix(station="10870").read(MOSMIX)
    check("three hours", len(got.hours), 3)
    check("the issue time is the model run, not now", got.issued,
          meteoalarm.parse_time("2026-08-27T03:00:00.000Z"))
    check("named", got.note, "Muenchen-Fl.")

    first = got.hours[0]
    # The one that matters. 287.35 K is 14.2 C. Read as Celsius it is a
    # forecast of 287 degrees; converted the wrong way it is -259.
    close("Kelvin becomes Celsius", first.outTemp, 14.2)
    close("and so does the dew point", first.dewpoint, 8.0)
    # Pascals to millibars. 101580 Pa read as millibars is a page showing a
    # pressure a hundred times too high.
    close("pascals become millibars", first.barometer, 1015.8)
    close("wind is already metres per second", first.windSpeed, 3.2)
    # 360 kJ/m2 over an hour is 100 W/m2.
    close("kJ per hour becomes watts", got.hours[1].radiation, 100.0)
    close("metres become kilometres", first.visibility, 24.14)
    check("the weather code is an integer", first.code, 2)
    # A dash in a MOSMIX column means the model has no value there. It must
    # not become a zero and must not shift the column.
    ok("a dash is nothing", got.hours[2].outTemp is None)
    close("while the same hour's other columns stand",
          got.hours[2].windSpeed, 2.1)


def test_mosmix_without_a_station() -> None:
    try:
        dwd.Mosmix().fetch(Place(latitude=48.4, longitude=11.7))
    except ForecastError as exc:
        ok("MOSMIX says it needs a station id", "station id" in str(exc))
        ok("and that asking again will not help", exc.permanent)
    else:
        FAILURES.append("MOSMIX accepted a fetch with no station")


# ---------------------------------------------------------------------------
# MeteoAlarm.
# ---------------------------------------------------------------------------

METEOALARM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:cap="urn:oasis:names:tc:emergency:cap:1.2">
  <title>MeteoAlarm</title>
  <entry>
    <cap:geocode><valueName>EMMA_ID</valueName><value>DE037</value></cap:geocode>
    <cap:areaDesc>Kreis Ploen - Kueste</cap:areaDesc>
    <cap:event>wind gusts</cap:event>
    <cap:sent>2026-08-27T06:00:00+00:00</cap:sent>
    <cap:expires>2026-08-27T19:00:00+00:00</cap:expires>
    <cap:onset>2026-08-27T09:00:00+00:00</cap:onset>
    <cap:certainty>Likely</cap:certainty>
    <cap:severity>Minor</cap:severity>
    <cap:urgency>Immediate</cap:urgency>
    <cap:identifier>2.49.0.0.276.0.DWD.PVW.1787810400000.abc.MUL</cap:identifier>
    <title>Yellow Wind Warning issued for Germany - Kreis Ploen</title>
  </entry>
  <entry>
    <cap:geocode><valueName>EMMA_ID</valueName><value>DE121</value></cap:geocode>
    <cap:areaDesc>Kreis Freising</cap:areaDesc>
    <cap:event>thunderstorms</cap:event>
    <cap:sent>2026-08-27T06:00:00Z</cap:sent>
    <cap:expires>2026-08-27T22:00:00Z</cap:expires>
    <cap:onset>2026-08-27T14:00:00Z</cap:onset>
    <cap:severity>Severe</cap:severity>
    <cap:urgency>Expected</cap:urgency>
    <cap:identifier>2.49.0.0.276.0.DWD.PVW.1787810400000.def.MUL</cap:identifier>
    <title>Orange Thunderstorm Warning</title>
  </entry>
</feed>
"""


def test_meteoalarm() -> None:
    source = meteoalarm.MeteoAlarm(country="germany")
    everything = source.entries(METEOALARM)
    check("two warnings", len(everything), 2)
    first = everything[0]
    check("the event", first.event, "wind gusts")
    check("the severity", first.severity, "Minor")
    check("the area", first.area, "Kreis Ploen - Kueste")
    check("the region id is kept", first.kind, "DE037")
    check("onset", first.starts,
          meteoalarm.parse_time("2026-08-27T09:00:00+00:00"))
    # A `Z` and a `+00:00` are the same instant, and different producers use
    # each. Both have to parse.
    check("a Z suffix parses the same as an offset",
          everything[1].issued,
          meteoalarm.parse_time("2026-08-27T06:00:00+00:00"))
    # The identifier carries the area, or two districts under one alert
    # collapse into one row and a station sees somebody else's warning.
    ok("the identifier includes the area", first.identifier.endswith(":DE037"))


def test_meteoalarm_filters() -> None:
    """A country feed is not a place. Filtering is the whole usability story."""
    by_id = meteoalarm.MeteoAlarm(country="germany", region="DE121")
    kept = [w for w in by_id.entries(METEOALARM) if by_id._wanted(w)]
    check("by region id", [w.event for w in kept], ["thunderstorms"])

    # By name, because `DE121` is not something anybody knows and
    # "Freising" is.
    by_name = meteoalarm.MeteoAlarm(country="germany", region="freising")
    kept = [w for w in by_name.entries(METEOALARM) if by_name._wanted(w)]
    check("by part of the area name", [w.event for w in kept], ["thunderstorms"])

    both = meteoalarm.MeteoAlarm(country="germany", region="DE121, Ploen")
    kept = [w for w in both.entries(METEOALARM) if both._wanted(w)]
    check("several at once", len(kept), 2)

    severe = meteoalarm.MeteoAlarm(country="germany", minimum="Severe")
    kept = [w for w in severe.entries(METEOALARM) if severe._wanted(w)]
    check("by severity", [w.event for w in kept], ["thunderstorms"])

    # No region keeps everything: loud rather than silent. Somebody notices a
    # page covered in warnings for the whole country; nobody notices a
    # missing one.
    none = meteoalarm.MeteoAlarm(country="germany")
    kept = [w for w in none.entries(METEOALARM) if none._wanted(w)]
    check("no region keeps everything", len(kept), 2)


def test_meteoalarm_needs_a_country() -> None:
    try:
        meteoalarm.MeteoAlarm()
    except ValueError as exc:
        ok("it says so", "country" in str(exc))
    else:
        FAILURES.append("MeteoAlarm accepted no country")


# ---------------------------------------------------------------------------
# The NWS.
# ---------------------------------------------------------------------------

NWS_ALERTS = {
    "features": [
        {"properties": {
            "id": "urn:oid:2.49.0.1.840.0.abc.001.1",
            "event": "Small Craft Advisory", "severity": "Minor",
            "urgency": "Expected", "certainty": "Likely",
            "onset": "2026-08-26T17:00:00-08:00",
            "effective": "2026-08-26T16:03:00-08:00",
            "expires": "2026-08-27T04:30:00-08:00",
            "ends": "2026-08-27T05:00:00-08:00",
            "sent": "2026-08-26T16:03:00-08:00",
            "headline": "Small Craft Advisory issued August 26",
            "description": "Winds 20 to 25 kt.",
            "instruction": "Inexperienced mariners should avoid navigating.",
            "areaDesc": "West of Barren Islands", "messageType": "Alert",
            "category": "Met", "language": "en-US"}},
        {"properties": {
            "id": "urn:oid:2.49.0.1.840.0.def.002.1",
            "event": "Flood Warning", "severity": "Severe",
            "sent": "2026-08-26T16:03:00-08:00",
            "areaDesc": "Somewhere", "messageType": "Cancel"}},
    ]
}


def test_nws_alerts() -> None:
    source = nws.NationalWeatherService()
    got = source.read_alerts(NWS_ALERTS)
    # A cancellation is not a warning. Keeping it puts "Flood Warning" on a
    # page for something that has just ended.
    check("a cancellation is not kept", [w.event for w in got],
          ["Small Craft Advisory"])
    first = got[0]
    check("severity", first.severity, "Minor")
    check("area", first.area, "West of Barren Islands")
    ok("the instruction is kept", "Inexperienced" in first.instruction)
    # `ends` is when the weather stops and `expires` is when the message goes
    # stale. They differ by half an hour here, and a page wants the first.
    check("ends is preferred over expires", first.ends,
          meteoalarm.parse_time("2026-08-27T05:00:00-08:00"))

    severe = nws.NationalWeatherService(minimum="Severe")
    check("filtered by severity", len(severe.read_alerts(NWS_ALERTS)), 0)


def test_nws_prose() -> None:
    """The NWS writes for people: '10 mph' and 'Mostly Cloudy'."""
    close("a plain speed", nws.speed("10 mph"), 4.4704)
    # A range is a warning about its upper end. Taking the lower one would be
    # the friendlier number and the wrong one.
    close("a range takes the top", nws.speed("5 to 10 mph"), 4.4704)
    ok("nothing at all is nothing", nws.speed("") is None)

    check("clear", nws.code_for("Sunny"), 0)
    check("cloud", nws.code_for("Mostly Cloudy"), 3)
    # Longest match wins, or "Chance Rain Showers" becomes plain rain.
    check("showers beat rain", nws.code_for("Chance Rain Showers"), 81)
    check("thunder wins outright",
          nws.code_for("Chance Showers And Thunderstorms"), 95)
    ok("a phrase about nothing says nothing", nws.code_for("Breezy") is None)
    check("a bearing", nws.BEARINGS["NNW"], 337.5)


# ---------------------------------------------------------------------------
# The store.
# ---------------------------------------------------------------------------

def test_store_replaces(tmp: Path) -> None:
    store = ForecastStore(tmp / "forecast.sdb")
    first = openmeteo.OpenMeteo().read(OPEN_METEO)
    first.source = "open-meteo"
    store.store(first, fetched=1787781600)
    check("the hours are there", len(store.hours("open-meteo")), 3)
    check("and the days", len(store.days("open-meteo")), 2)

    # A new run replaces the old one rather than adding to it. Nobody wants
    # yesterday's forecast for today, and keeping it makes the file grow
    # without ever gaining a reader.
    again = openmeteo.OpenMeteo().read(OPEN_METEO)
    again.source = "open-meteo"
    store.store(again, fetched=1787785200)
    check("a second run does not double them",
          len(store.hours("open-meteo")), 3)

    run = store.run("open-meteo")
    check("the run is recorded", run["hours"], 3)
    check("with when it was fetched", run["fetched"], 1787785200)

    # Two sources side by side, each answering for itself.
    other = dwd.Mosmix(station="10870").read(MOSMIX)
    store.store(other, fetched=1787785200)
    check("the other source is separate", len(store.hours("dwd")), 3)
    check("and the first is untouched", len(store.hours("open-meteo")), 3)
    check("everything together", len(store.hours()), 6)
    check("both are listed", store.sources(), ["dwd", "open-meteo"])
    store.close()


def test_store_warnings(tmp: Path) -> None:
    store = ForecastStore(tmp / "warnings.sdb")
    source = meteoalarm.MeteoAlarm(country="germany")
    reading = Reading(source="meteoalarm",
                      warnings=source.entries(METEOALARM))
    store.store(reading, fetched=1787810400)
    got = store.warnings("meteoalarm")
    check("both stored", len(got), 2)
    # Most severe first: that is the order a page wants, and doing it in the
    # store means every reader gets it right.
    check("most severe first", got[0].event, "thunderstorms")

    active = store.warnings("meteoalarm",
                            active_at=meteoalarm.parse_time(
                                "2026-08-27T10:00:00Z"))
    check("only what covers that moment", [w.event for w in active],
          ["wind gusts"])

    # This is the one that matters. An empty feed means the warnings have
    # ended, and leaving an expired storm warning on a page is the failure
    # this whole package is meant to avoid.
    store.store(Reading(source="meteoalarm"), fetched=1787814000)
    check("an empty feed clears them", len(store.warnings("meteoalarm")), 0)
    store.close()


def test_a_failure_keeps_the_forecast(tmp: Path) -> None:
    """A network hiccup must not turn into a blank page."""
    store = ForecastStore(tmp / "keep.sdb")
    good = openmeteo.OpenMeteo().read(OPEN_METEO)
    good.source = "open-meteo"
    store.store(good, fetched=1787781600)

    class Broken:
        every = 3600

        def fetch(self, place):
            raise ForecastError("the host is not answering")

    entry = Scheduled("open-meteo", Broken(),
                      Place(latitude=48.4, longitude=11.7), store)
    entry.run()
    check("the failure was counted", entry.failures, 1)
    ok("and not treated as permanent", not entry.blocked)
    check("but the forecast is still there",
          len(store.hours("open-meteo")), 3)

    class Refused:
        every = 3600

        def fetch(self, place):
            raise ForecastError("no such station", permanent=True)

    entry = Scheduled("dwd", Refused(), Place(latitude=48.4, longitude=11.7),
                      store)
    entry.run()
    ok("a permanent refusal switches the source off", bool(entry.blocked))
    ok("so it is not asked again", not entry.due(time.monotonic() + 99999))
    store.close()


def test_prune(tmp: Path) -> None:
    store = ForecastStore(tmp / "prune.sdb")
    reading = openmeteo.OpenMeteo().read(OPEN_METEO)
    reading.source = "open-meteo"
    reading.warnings = [Warning(identifier="old", event="gone",
                                starts=1, ends=1787781000)]
    store.store(reading, fetched=1787781600)
    dropped = store.prune(1787785200)
    ok("something was dropped", dropped >= 1)
    check("the hour that has passed is gone",
          [m.dateTime for m in store.hours("open-meteo")],
          [1787785200, 1787788800])
    check("and the warning that ended", len(store.warnings("open-meteo")), 0)
    store.close()


# ---------------------------------------------------------------------------
# Codes.
# ---------------------------------------------------------------------------

def test_codes() -> None:
    check("clear", codes.text(0), "Clear sky")
    check("rain", codes.text(61), "Light rain")
    # DWD publishes the full WMO table; Open-Meteo's reduced set has gaps.
    # Falling back to the nearest lower code in the same ten is how a real
    # code becomes a real word rather than an empty string.
    check("a code only DWD uses falls back", codes.text(62), "Light rain")
    check("a night symbol", codes.symbol(0, night=True), "clear-night")
    check("and one that has no night variant",
          codes.symbol(63, night=True), "rain")
    ok("rain is wet", codes.is_wet(61))
    ok("cloud is not", not codes.is_wet(3))
    ok("thunder is severe", codes.is_severe(95))
    ok("freezing rain is severe", codes.is_severe(67))
    ok("ordinary rain is not", not codes.is_severe(63))
    check("nothing at all", codes.text(None), "")


def test_zip_handling() -> None:
    """MOSMIX arrives as a ZIP of one ISO-8859-1 file."""
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("MOSMIX_L_2026082703_10870.kml",
                         MOSMIX.encode("iso-8859-1"))
    raw = buffer.getvalue()
    with zipfile.ZipFile(BytesIO(raw)) as archive:
        text = archive.read(archive.namelist()[0]).decode("iso-8859-1")
    got = dwd.Mosmix(station="10870").read(text)
    check("it survives the round trip", len(got.hours), 3)
    close("with the temperature intact", got.hours[0].outTemp, 14.2)


# ---------------------------------------------------------------------------
# What a template sees.
# ---------------------------------------------------------------------------

def test_tags(tmp: Path) -> None:
    """A forecast temperature has to behave like a measured one.

    That is the point of the tag layer: a template formats both the same way
    and `units.Target` converts both, so a page written in Fahrenheit shows a
    metric forecast in Fahrenheit without knowing there are two systems
    underneath.
    """
    from weewx_evo.forecast import tags as forecast_tags

    store = ForecastStore(tmp / "tags.sdb")
    # Hours around "now", so `$forecast.now` has something to find.
    now = int(time.time())
    reading = Reading(source="ahead")
    for offset, temp, code in ((-1800, 18.0, 2), (1800, 19.5, 61),
                               (5400, 21.0, 63)):
        reading.hours.append(Moment(dateTime=now + offset,
                                    usUnits=units.METRICWX,
                                    outTemp=temp, code=code, windSpeed=3.0))
    midnight = time.mktime(time.localtime(now)[:3] + (0, 0, 0, 0, 0, -1))
    reading.days.append(Day(dateTime=int(midnight), usUnits=units.METRICWX,
                            tempMax=24.0, tempMin=12.0, code=61,
                            sunrise=now - 20000, sunset=now + 20000))
    reading.warnings.append(Warning(
        identifier="a", event="wind gusts", severity="Minor",
        starts=now - 600, ends=now + 3600, area="Kreis Freising"))
    reading.warnings.append(Warning(
        identifier="b", event="thunderstorms", severity="Severe",
        starts=now + 7200, ends=now + 14400, area="Kreis Freising"))
    store.store(reading, fetched=now)

    metric = units.Target(units.METRICWX)
    tag = forecast_tags.SourceTag(store, "", metric)

    ok("the forecast is there", bool(tag))
    check("three hours", len(tag.hours), 3)
    # The hour we are in, not the nearest one: at twenty-nine minutes past,
    # the nearest is the next hour, and showing its rain as current would be
    # wrong in the way nobody checks.
    check("now is the hour we are in", tag.now.item.dateTime, now - 1800)
    check("its temperature", str(tag.now.outTemp), "18.0\u00b0C")
    check("said in words", tag.now.text, "Partly cloudy")
    check("and as a symbol name", tag.now.symbol in
          ("partly-cloudy", "partly-cloudy-night"), True)
    ok("partly cloudy is not wet", not tag.now.wet)
    ok("but the next hour is", tag.hours[1].wet)

    check("today", str(tag.today.tempMax), "24.0\u00b0C")
    check("sunrise is a time, not a number",
          ":" in str(tag.today.sunrise), True)

    # The conversion is the whole point. Same store, a page in Fahrenheit.
    imperial = forecast_tags.SourceTag(store, "", units.Target(units.US))
    check("the same forecast in Fahrenheit", str(imperial.now.outTemp),
          "64.4\u00b0F")
    check("and the daily maximum too", str(imperial.today.tempMax), "75.2\u00b0F")

    # Warnings, worst first, and `active` is a question rather than a filter:
    # "storm tonight" is the point of a warning.
    check("two warnings", len(tag.warnings), 2)
    check("worst first", tag.warning.event, "thunderstorms")
    ok("the severe one has not started yet", not tag.warning.active)
    ok("the minor one has", tag.warnings[1].active)
    check("only one is active now", len(tag.active_warnings), 1)
    check("the area came through", tag.warning.area, "Kreis Freising")

    # A named source, which is what makes two of them usable at once.
    named = tag.ahead
    check("a named source answers", str(named.now.outTemp), "18.0\u00b0C")
    # An unknown name is a miss, not an exception: `#if $forecast.nothing`
    # must not break a page.
    unknown = tag.nothing
    check("an unknown source prints as unknown", str(unknown), "?'forecast.nothing'?")

    check("it knows when it was fetched", tag.updated.raw, now)
    store.close()


def test_tags_with_nothing(tmp: Path) -> None:
    """A station that started a minute ago still has to render."""
    from weewx_evo.forecast import tags as forecast_tags

    store = ForecastStore(tmp / "empty.sdb")
    tag = forecast_tags.SourceTag(store, "", units.Target(units.METRICWX))
    ok("there is no forecast", not bool(tag))
    check("no hours", tag.hours, [])
    check("no days", tag.days, [])
    check("no warnings", tag.warnings, [])
    # Unknown rather than an exception, so a template renders around it.
    check("now prints as unknown", str(tag.now), "?'forecast.now'?")
    check("and so does the worst warning", str(tag.warning),
          "?'forecast.warning'?")
    ok("asking twice does not raise", str(tag.today) == "?'forecast.today'?")
    store.close()


def main() -> int:
    test_open_meteo()
    test_open_meteo_asks_for_what_it_reads()
    test_mosmix()
    test_mosmix_without_a_station()
    test_meteoalarm()
    test_meteoalarm_filters()
    test_meteoalarm_needs_a_country()
    test_nws_alerts()
    test_nws_prose()
    test_codes()
    test_zip_handling()
    with tempfile.TemporaryDirectory() as tmp:
        test_store_replaces(Path(tmp))
        test_store_warnings(Path(tmp))
        test_a_failure_keeps_the_forecast(Path(tmp))
        test_prune(Path(tmp))
        test_tags(Path(tmp))
        test_tags_with_nothing(Path(tmp))

    print()
    for failure in FAILURES:
        print("FAIL", failure)
    print(f"{CHECKS} checks, {len(FAILURES)} failed")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
