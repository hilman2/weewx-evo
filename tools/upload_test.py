#!/usr/bin/env python3
"""What goes out to a weather service, checked against WeeWX byte for byte.

Two halves.

**Without WeeWX**, always: the edge cases each protocol has, which are the
ones that never come up on a summer afternoon and are wrong for a year
afterwards. A temperature below zero Fahrenheit in a three-character field.
100 % humidity written as `h00`. Solar radiation over 1000 W/m2 changing which
letter it uses. A station with no rain gauge, where the difference between
"absent" and "0.00" is the difference between no data and a drought.

**With WeeWX importable**, the part that matters most: the same record through
both implementations, compared parameter by parameter. The Ambient query and
the CWOP packet are transcriptions, and a transcription is either identical or
it is a bug. A rainfall total that arrives with two decimals instead of three
is a different number.

    python tools/upload_test.py

    wsl -d Ubuntu -- bash -lc 'source ~/venvs/weewx/bin/activate && \\
      cd /mnt/d/Git/weewx-evo && PYTHONPATH=/mnt/d/Git/weewx/src:src \\
      python3 tools/upload_test.py'

Nothing here touches the network. Every check builds a request and looks at it.
"""

from __future__ import annotations

import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from weewx_evo.uploads import ambient, cwop, weathercloud, windy
from weewx_evo.uploads.progress import Progress

FAILURES: list[str] = []
CHECKS = 0


def check(what: str, got: object, want: object) -> None:
    global CHECKS
    CHECKS += 1
    if got != want:
        FAILURES.append(f"{what}\n    got  {got!r}\n    want {want!r}")


def params(query: str) -> dict[str, str]:
    """A query string as a dictionary, so a comparison names the field."""
    return dict(urllib.parse.parse_qsl(query.split("?", 1)[-1], keep_blank_values=True))


# A record in metric: the archive holds Celsius and every one of these
# services wants something else. That is the ordinary case here -- a console
# in Germany and a page in Fahrenheit, or the reverse -- and it is the one
# that exercises the conversion rather than skipping it.
METRIC = {
    "dateTime": 1756308600,          # 2025-08-27 15:30:00 UTC
    "usUnits": 17,                   # METRICWX
    "outTemp": 23.4, "outHumidity": 61.0, "dewpoint": 15.6,
    "barometer": 1013.2, "altimeter": 1012.8,
    "windSpeed": 3.2, "windDir": 245.0, "windGust": 7.1, "windGustDir": 250.0,
    "hourRain": 1.4, "rain24": 3.2, "dayRain": 2.6,
    "radiation": 512.0, "UV": 4.2,
    "inTemp": 21.1, "inHumidity": 48.0, "rainRate": 2.4,
}


# ---------------------------------------------------------------------------
# The edge cases.
# ---------------------------------------------------------------------------

def test_absent_is_absent() -> None:
    """A station without a rain gauge sends no rain, not zero rain.

    This is the one that matters most and is invisible in normal running: a
    station posting `rainin=0.00` every five minutes looks exactly like one in
    a drought, and Weather Underground keeps it forever.
    """
    bare = {"dateTime": METRIC["dateTime"], "usUnits": 17, "outTemp": 12.0}
    sent = params(ambient.WundergroundUpload(station="X", password="y")._query(bare))
    check("WU leaves out rain a station does not report", "rainin" in sent, False)
    check("WU leaves out humidity a station does not report",
          "humidity" in sent, False)
    check("WU still sends the temperature it has", sent.get("tempf"), "53.6")

    observation = windy.WindyUpload(api_key="k")._observation(bare)
    check("Windy leaves out what is absent", "precip" in observation, False)

    query = weathercloud.WeathercloudUpload(wid="a", key="b")._query(bare)
    check("Weathercloud leaves out what is absent", "rain" in params(query), False)

    packet = cwop.CwopUpload(station="DW1", latitude=48.0,
                             longitude=11.0).packet(bare)
    # CWOP has no way to omit a field: it is positional, so absent is dots of
    # the same width. Sending zeros there would be a claim.
    check("CWOP writes absent rain as dots", "r...p...P..." in packet, True)
    check("CWOP writes absent humidity as dots", "h.." in packet, True)
    check("CWOP writes absent wind as dots", "_.../...g..." in packet, True)


def test_cwop_widths() -> None:
    """Every CWOP field is fixed width. A wrong width is a wrong reading."""
    upload = cwop.CwopUpload(station="DW1234", latitude=48.3858,
                             longitude=11.7050)
    body = upload.packet(METRIC).split(":", 1)[1].strip()
    # `@`, not `/`: a position report with a timestamp, which is the byte
    # WeeWX has sent from thousands of stations for fifteen years. See the
    # comment at the line in cwop.py for why the stricter `/` is not used.
    check("CWOP timestamp", body[:8], "@271530z")
    # 48.3858 deg is 48 deg 23.148 min; 11.7050 deg is 11 deg 42.30 min.
    check("CWOP position", body[8:26], "4823.15N/01142.30E")
    # The `_` opens the weather report and belongs to the wind field, not to
    # the position. Every offset below is counted, not guessed: getting one
    # wrong makes a slice test pass on nonsense.
    check("CWOP wind", body[26:39], "_245/007g016t")
    check("CWOP temperature", body[39:42], "074")
    check("CWOP rain", body[42:54], "r006p013P010")
    check("CWOP barometer", body[54:60], "b10128")
    check("CWOP humidity", body[60:63], "h61")
    check("CWOP radiation", body[63:67], "L512")

    # Below zero Fahrenheit the sign takes one of the three characters.
    cold = dict(METRIC, outTemp=-20.0)          # -4 F
    check("CWOP writes a negative temperature in three characters",
          "t-04" in upload.packet(cold), True)
    freezing = dict(METRIC, outTemp=-30.0)      # -22 F
    check("CWOP writes -22 F", "t-22" in upload.packet(freezing), True)

    # 100 % humidity is `h00`. Two digits, and no room for a third.
    check("CWOP writes 100 % humidity as h00",
          "h00" in upload.packet(dict(METRIC, outHumidity=100.0)), True)
    check("CWOP writes 99 % humidity as h99",
          "h99" in upload.packet(dict(METRIC, outHumidity=99.0)), True)

    # Over 1000 W/m2 the letter changes and the thousand is dropped.
    check("CWOP writes 512 W/m2 as L512",
          "L512" in upload.packet(dict(METRIC, radiation=512.0)), True)
    check("CWOP writes 1200 W/m2 as l200",
          "l200" in upload.packet(dict(METRIC, radiation=1200.0)), True)

    # The southern and western hemispheres.
    south = cwop.CwopUpload(station="DW1", latitude=-33.8688, longitude=151.2093)
    check("CWOP position south and east",
          south.packet(METRIC).split(":", 1)[1][8:26], "3352.13S/15112.56E")


def test_cwop_needs_a_position() -> None:
    """The packet is a position report. Without one there is nothing to send."""
    try:
        cwop.CwopUpload(station="DW1234")
    except ValueError as exc:
        check("CWOP says why it needs a position", "latitude" in str(exc), True)
    else:
        FAILURES.append("CWOP accepted a station with no position")


def test_windy_pressure() -> None:
    """Windy wants pascals. Everything else in the world wants hectopascals."""
    observation = windy.WindyUpload(api_key="k")._observation(METRIC)
    check("Windy pressure in pascals", observation["pressure"], 101320)
    check("Windy temperature stays Celsius", observation["temp"], 23.4)


def test_weathercloud_scaling() -> None:
    """Every Weathercloud value is an integer in tenths."""
    sent = params(weathercloud.WeathercloudUpload(wid="a", key="b")._query(METRIC))
    check("Weathercloud temperature", sent["temp"], "234")
    check("Weathercloud humidity is not scaled", sent["hum"], "61")
    check("Weathercloud pressure", sent["bar"], "10132")
    check("Weathercloud date and time are separate",
          (sent["date"], sent["time"]), ("20250827", "15:30"))
    check("Weathercloud leaves the house out by default", "tempin" in sent, False)


def test_indoor_is_off() -> None:
    """What it is like inside somebody's house is not weather."""
    sent = params(ambient.WundergroundUpload(station="X", password="y")._query(METRIC))
    check("WU leaves indoor readings out by default", "indoortempf" in sent, False)
    on = params(ambient.WundergroundUpload(station="X", password="y",
                                           indoor=True)._query(METRIC))
    check("WU sends them when asked", on.get("indoortempf"), "70.0")


def test_wow_renames_both_credentials() -> None:
    sent = params(ambient.WowUpload(station="912345", password="123456")._query(METRIC))
    check("WOW calls the station siteid", sent.get("siteid"), "912345")
    check("WOW calls the password siteAuthenticationKey",
          sent.get("siteAuthenticationKey"), "123456")
    check("WOW does not send the Ambient names", "ID" in sent, False)
    # WOW's rain goes to three decimals where WU's goes to two.
    check("WOW daily rain has three decimals", sent.get("dailyrainin"), "0.102")


def test_progress_never_goes_backwards(tmp: Path) -> None:
    """A backfilled record must not rewind the mark and resend the hour."""
    progress = Progress(tmp / "progress.json")
    progress.sent("wu", 2000)
    progress.sent("wu", 1000)
    check("progress keeps the newest", progress.through("wu"), 2000)
    progress.sent("wu", 3000)
    progress.save()
    check("progress survives a reload",
          Progress(tmp / "progress.json").through("wu"), 3000)
    check("an upload nobody has run is at zero", progress.through("windy"), 0)


# ---------------------------------------------------------------------------
# Against WeeWX.
# ---------------------------------------------------------------------------

def against_weewx() -> bool:
    """The same record through both. Returns False if WeeWX is not installed."""
    try:
        import weewx
        import weewx.restx
        import weewx.units
    except ImportError:
        return False

    print(f"comparing against WeeWX {weewx.__version__}")

    # WeeWX builds its URL from a thread; the thread needs a queue and a
    # manager it never uses for this. `object.__new__` skips the constructor
    # and sets only what `format_url` reads -- which is the whole point of
    # comparing the formatter rather than the service.
    theirs = object.__new__(weewx.restx.AmbientThread)
    theirs.station = "IBAYERN123"
    theirs.password = "secret"
    theirs.softwaretype = "weewx-evo"
    theirs.formats = dict(weewx.restx.AmbientThread._FORMATS)
    theirs.force_direction = False
    theirs.last_direction = None
    theirs.server_url = "https://example/x"

    ours = ambient.WundergroundUpload(station="IBAYERN123", password="secret")
    mine = params(ours._query(METRIC))
    yours = params(theirs.format_url(METRIC))

    # WeeWX sends fields we deliberately do not (`realtime`, `rtfreq`, and the
    # `windGust10` family, which only exist for its rapid-fire mode). Compare
    # what both claim to send.
    shared = set(mine) & set(yours)
    check("the two agree on which readings there are",
          sorted(set(yours) - set(mine) - {"realtime", "rtfreq"}), [])
    for name in sorted(shared):
        if name == "softwaretype":
            continue
        check(f"WU {name}", mine[name], yours[name])

    # CWOP: the whole packet, character for character.
    packet = object.__new__(weewx.restx.CWOPThread)
    packet.station = "DW1234"
    packet.latitude = 48.3858
    packet.longitude = 11.7050
    packet.station_type = "evo"
    packet.protocol_name = "CWOP"

    us_record = weewx.units.to_US(METRIC)
    theirs_packet = packet.get_tnc_packet(us_record).strip()
    ours_packet = cwop.CwopUpload(station="DW1234", latitude=48.3858,
                                  longitude=11.7050).packet(METRIC).strip()

    # The path and the equipment field name the software, so they differ on
    # purpose: `APWEE5` is registered to WeeWX and is not ours to send.
    def weather_part(line: str) -> str:
        return line.split(":", 1)[1]

    check("the CWOP weather report is identical",
          weather_part(ours_packet).split(".weewx")[0],
          weather_part(theirs_packet).split(".weewx")[0])
    return True


# ---------------------------------------------------------------------------

def main() -> int:
    import tempfile

    test_absent_is_absent()
    test_cwop_widths()
    test_cwop_needs_a_position()
    test_windy_pressure()
    test_weathercloud_scaling()
    test_indoor_is_off()
    test_wow_renames_both_credentials()
    with tempfile.TemporaryDirectory() as tmp:
        test_progress_never_goes_backwards(Path(tmp))

    compared = against_weewx()
    if not compared:
        print("WeeWX is not importable, so the comparison was skipped.\n"
              "  Run it under WSL with PYTHONPATH=/mnt/d/Git/weewx/src:src "
              "to check the transcription.")

    print()
    for failure in FAILURES:
        print("FAIL", failure)
    print(f"{CHECKS} checks, {len(FAILURES)} failed")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
