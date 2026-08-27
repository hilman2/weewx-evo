#!/usr/bin/env python3
"""The Weather Underground protocol, received.

The check that earns its place here is the round trip: `uploads/ambient.py` is
the *sending* half of this exact protocol, so every field it can post has to
be readable by the driver that receives it. Two weewx-evo instances have to be
able to talk to each other through a protocol both of them speak.

That is not a hypothetical. Run against `weewx-interceptor`, the same
comparison finds three fields WeeWX sends and it silently drops -- `rainin`,
`soilmoisture` and `leafwetness2`. The last two are the plain first sensor,
which is what a station with one soil probe sends and nothing else.

    python tools/wunderground_test.py
"""

from __future__ import annotations

import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from weewx_evo.db.live import LiveStore  # noqa: E402
from weewx_evo.ingest import drivers  # noqa: E402
from weewx_evo.ingest.listener import HttpListener, Ingest  # noqa: E402
from weewx_evo.ingest.plugins.wunderground.driver import (  # noqa: E402
    WundergroundDriver,
)
from weewx_evo.ingest.plugins.wunderground.fields import (  # noqa: E402
    FIELDS,
    IGNORED,
)
from weewx_evo.units import US  # noqa: E402

TOKEN = "w" * 32
failures = 0


def check(what: str, got: object, want: object) -> bool:
    global failures
    ok = got == want
    tail = "" if ok else f"  (wanted {want!r})"
    print(f"  {'ok  ' if ok else 'FAIL'} {what}: {got!r}{tail}")
    failures += 0 if ok else 1
    return ok


def everything_we_send_we_can_read() -> None:
    """The round trip. Our own upload is the specification here."""
    print("\nevery field our own WU upload posts, this driver reads")
    from weewx_evo.uploads.ambient import FIELDS as SENT
    from weewx_evo.uploads.ambient import INDOOR_FIELDS

    missing = []
    for _obs, name, _unit, _fmt in SENT + INDOOR_FIELDS:
        if name not in FIELDS and name not in IGNORED:
            missing.append(name)
    check("fields we post but could not read back", missing, [])

    # And the names have to mean the same thing on both sides, or a round
    # trip silently moves a reading into the neighbouring column.
    wrong = []
    for obs, name, _unit, _fmt in SENT + INDOOR_FIELDS:
        ours = FIELDS.get(name)
        if ours is not None and ours != obs:
            wrong.append(f"{name}: we send {obs}, we read {ours}")
    check("and every one comes back under the name it went out as", wrong, [])


def the_three_the_interceptor_drops() -> None:
    """Named individually, because they are why this driver exists."""
    print("\nthe three weewx-interceptor loses")
    for their, ours in (("rainin", "hourRain"),
                        ("soilmoisture", "soilMoist1"),
                        ("leafwetness2", "leafWet2")):
        check(f"{their} -> {ours}", FIELDS.get(their), ours)


def what_a_station_sends() -> None:
    print("\na real upload")
    driver = WundergroundDriver()
    body = (b"ID=KTEST5&PASSWORD=secret&action=updateraw&realtime=1&rtfreq=2.5"
            b"&dateutc=2026-08-27+18:30:00&softwaretype=EasyWeatherPro"
            b"&tempf=68.4&humidity=55&dewptf=51.8&baromin=29.92"
            b"&windspeedmph=3.1&winddir=180&windgustmph=7.2"
            b"&rainin=0.04&dailyrainin=0.28&solarradiation=412.5&UV=3"
            b"&indoortempf=70.1&indoorhumidity=48")
    made = driver.packets(body, {"received": 1787800000})
    check("one packet", len(made), 1)
    packet = made[0]
    check("US units, because the protocol has no other", packet.usUnits, US)
    check("the station names itself", packet.source, "KTEST5")
    check("outTemp", packet.data.get("outTemp"), 68.4)
    check("barometer", packet.data.get("barometer"), 29.92)
    check("hourRain", packet.data.get("hourRain"), 0.04)
    check("dayRain, which derive.py turns into rain",
          packet.data.get("dayRain"), 0.28)
    check("indoor readings", packet.data.get("inTemp"), 70.1)
    # 2026-08-27 18:30:00 UTC
    check("its own timestamp, read as UTC", packet.dateTime, 1787855400)
    check("housekeeping is not a reading",
          [n for n in ("ID", "PASSWORD", "action", "realtime", "softwaretype")
           if n in packet.data], [])
    check("nothing unknown in a standard upload",
          sorted(driver.unknown), [])


def the_sensor_that_did_not_report() -> None:
    print("\n-9999 is not a temperature")
    driver = WundergroundDriver()
    body = (b"ID=K&action=updateraw&dateutc=now&tempf=-9999&humidity=55"
            b"&dewptf=&baromin=N/A&windspeedmph=0.0")
    packet = driver.packets(body, {"received": 1787800000})[0]
    check("-9999 is dropped, not stored as -9999 F",
          "outTemp" in packet.data, False)
    check("an empty value is dropped", "dewpoint" in packet.data, False)
    check("'N/A' is dropped", "barometer" in packet.data, False)
    check("a real zero is kept", packet.data.get("windSpeed"), 0.0)
    check("and the good reading survives", packet.data.get("outHumidity"), 55.0)


def who_claims_it() -> None:
    """The path named no driver, so the drivers are asked."""
    print("\nwhich driver recognises which upload")
    registry = drivers.DEFAULT
    registry.load()
    wu = b"ID=K&PASSWORD=x&action=updateraw&tempf=68.4"
    eco = b"PASSKEY=ABC&stationtype=GW2000A_V3.1.2&tempf=68.4&baromrelin=29.92"

    check("a WU upload goes to the WU driver",
          registry.claimant(wu, {}), "wunderground")
    check("an Ecowitt upload goes to the Ecowitt driver",
          registry.claimant(eco, {}), "ecowitt")
    # PASSKEY beats everything: an Ecowitt console also sends tempf and
    # humidity, so without this the two would compete on every upload.
    check("the WU driver stands down for a PASSKEY",
          WundergroundDriver().claims(eco, {}), 0.0)
    check("something unrecognisable claims nothing",
          registry.claimant(b"hello=world", {}), None)


def the_whole_way() -> None:
    """Over a real listener, with the token where such a console can put it."""
    print("\nover the wire, with the token in PASSWORD")
    with tempfile.TemporaryDirectory() as raw:
        live = LiveStore(Path(raw) / "live.sdb", interval_seconds=300)
        listener = HttpListener(Ingest(live, token=TOKEN), "127.0.0.1", 0)
        listener.start()
        base = f"http://127.0.0.1:{listener.port}"
        # The path a console with no path field sends. No token in it, and no
        # driver name either -- both have to come out of the query string.
        path = "/weatherstation/updateweatherstation.php"
        try:
            def post(query: str) -> int:
                with urllib.request.urlopen(f"{base}{path}?{query}",
                                            timeout=5) as answer:
                    return answer.status

            good = (f"ID=KTEST5&PASSWORD={TOKEN}&action=updateraw&dateutc=now"
                    f"&tempf=68.4&humidity=55&baromin=29.92")
            check("accepted", post(good), 200)
            stored = list(live.packets(0, 2_000_000_000))
            check("stored", len(stored), 1)
            check("read by the WU driver, not the default one",
                  stored[0].data.get("barometer"), 29.92)
            check("under the station's own name", stored[0].source, "KTEST5")

            # A wrong password is a wrong token, and gets what one gets.
            try:
                post("ID=K&PASSWORD=wrong&action=updateraw&tempf=1")
                check("a wrong password is refused", "accepted", "404")
            except urllib.error.HTTPError as exc:
                check("a wrong password is refused", exc.code, 404)
            check("and nothing more was stored",
                  len(list(live.packets(0, 2_000_000_000))), 1)

            # The token is the one thing that must not sit in the database.
            kept = live.raw_of(1)
            if kept and kept[1]:
                check("the token is redacted in the kept upload",
                      TOKEN in kept[1], False)
        finally:
            listener.stop()
            live.close()


def main() -> int:
    everything_we_send_we_can_read()
    the_three_the_interceptor_drops()
    what_a_station_sends()
    the_sensor_that_did_not_report()
    who_claims_it()
    the_whole_way()

    print()
    if failures:
        print(f"{failures} check(s) failed")
        return 1
    print(f"the WU protocol reads, {len(FIELDS)} fields known")
    return 0


if __name__ == "__main__":
    sys.exit(main())
