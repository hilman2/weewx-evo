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

import dataclasses
import io
import logging
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from weewx_evo_push_common import protocols  # noqa: E402
from weewx_evo_push_common.driver import PushDriver  # noqa: E402
from weewx_evo_push_common.transport import METADATA  # noqa: E402
from weewx_evo_wunderground.catalogs import (  # noqa: E402
    wunderground as catalog,
)

from weewx_evo import placement  # noqa: E402
from weewx_evo.db.live import LiveStore, sender_id  # noqa: E402
from weewx_evo.ingest import drivers  # noqa: E402
from weewx_evo.ingest.listener import HttpListener, Ingest  # noqa: E402
from weewx_evo.units import US  # noqa: E402

# The catalog is upstream's now, so the two names this file used come from
# it: FIELDS is the imperial dialect, and what used to be a hand-kept IGNORED
# is the shared metadata list plus the catalog's own.
FIELDS = catalog.FIELDS
IGNORED = set(METADATA) | set(getattr(catalog, "METADATA", ()))


def WundergroundDriver(**options):  # noqa: N802
    """The Weather Underground protocol, as a driver.

    A function rather than the class, because the six protocols are one
    driver class now and this test predates that.
    """
    return PushDriver(protocols.by_name("wunderground"), **options)


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
    #
    # One exception, and it is deliberate. A station's own dewpoint, wind
    # chill and heat index are *its* arithmetic, and a receiving server
    # computes its own from temperature and humidity. Reading them into
    # `dewpoint` would overwrite a value this program derives with one it
    # cannot check, so the catalog keeps them beside it under their own
    # names. We send ours out under the field the protocol names; we read
    # somebody else's back as theirs.
    COMPUTED = {"dewptf", "windchillf", "heatindexf", "feelslikef"}

    wrong = []
    for obs, name, _unit, _fmt in SENT + INDOOR_FIELDS:
        if name in COMPUTED:
            continue
        ours = FIELDS.get(name)
        if ours is not None and ours != obs:
            wrong.append(f"{name}: we send {obs}, we read {ours}")
    check("and every one comes back under the name it went out as", wrong, [])

    # The exception, checked rather than merely excluded: each of them has to
    # land somewhere of its own, not nowhere and not on the derived column.
    aside = []
    for name in sorted(COMPUTED):
        target = FIELDS.get(name)
        if not target or target in ("dewpoint", "windchill", "heatindex"):
            aside.append(f"{name} -> {target}")
    check("a station's own arithmetic is kept beside ours, not over it",
          aside, [])


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
    # Relative to now, not a date written into the file. A console's own
    # timestamp is only used when it is within an hour of ours, so a fixed
    # one in the past passes on the day it is written and fails for ever
    # after -- which is what this line used to do.
    when = time.gmtime(time.time() - 120)
    stamp = time.strftime("%Y-%m-%d+%H:%M:%S", when)
    body = (b"ID=KTEST5&PASSWORD=secret&action=updateraw&realtime=1&rtfreq=2.5"
            + f"&dateutc={stamp}".encode()
            + b"&softwaretype=EasyWeatherPro"
            b"&tempf=68.4&humidity=55&dewptf=51.8&baromin=29.92"
            b"&windspeedmph=3.1&winddir=180&windgustmph=7.2"
            b"&rainin=0.04&dailyrainin=0.28&solarradiation=412.5&UV=3"
            b"&indoortempf=70.1&indoorhumidity=48")
    # The arrival time, not a fixed one in the past. A console's own stamp is
    # only believed when it is close to ours, and "ours" is the moment the
    # upload landed -- so a stale `received` makes every stamp look an hour
    # ahead and the test measures the fallback instead of the parse.
    arrived = int(time.time())
    made = driver.packets(body, {"received": arrived})
    check("one packet", len(made), 1)
    packet = made[0]
    check("US units, because the protocol has no other", packet.usUnits, US)
    check("the station names itself", packet.identity, "KTEST5")
    check("its own timestamp, read as UTC",
          packet.dateTime, int(time.mktime(when) - time.timezone))

    # The journal holds what the console sent, under the console's own names.
    check("the raw names are what is stored",
          [n for n in ("tempf", "baromin", "rainin") if n in packet.data],
          ["tempf", "baromin", "rainin"])
    check("and what names the station is not",
          [n for n in ("ID", "PASSWORD") if n in packet.data], [])
    # `action`, `realtime` and `softwaretype` stay: they say what firmware
    # this is and are worth having on the settings page. They are metadata to
    # the catalog, so `numbers()` keeps them out of a record on the way out --
    # which is checked below rather than assumed.

    placed = drivers.place_with(driver, packet.data, packet.dialect, {})
    record = placed.record
    check("outTemp", record.get("outTemp"), 68.4)
    check("barometer", record.get("barometer"), 29.92)
    check("hourRain", record.get("hourRain"), 0.04)
    check("dayRain, which derive.py turns into rain",
          record.get("dayRain"), 0.28)
    check("indoor readings", record.get("inTemp"), 70.1)
    check("housekeeping never becomes a reading",
          [n for n in ("ID", "PASSWORD", "action", "realtime", "softwaretype")
           if n in record], [])
    check("nothing unknown in a standard upload",
          sorted(placed.proposals), [])


def the_sensor_that_did_not_report() -> None:
    print("\n-9999 is not a temperature")
    driver = WundergroundDriver()
    body = (b"ID=K&action=updateraw&dateutc=now&tempf=-9999&humidity=55"
            b"&dewptf=&baromin=N/A&windspeedmph=0.0")
    packet = driver.packets(body, {"received": int(time.time())})[0]
    # Through the placer, not the driver alone: a reading the console said
    # it did not take comes back as None, and dropping a None rather than
    # writing it is the core's decision -- a null is a measurement, and a
    # rain gauge reading 0.0 because its value was refused is a dry
    # afternoon that never happened.
    record = placement.Placer("default", placement.Placements(), None,
                              drivers.DEFAULT).place(
        dataclasses.replace(packet, driver="wunderground")).data
    check("-9999 is dropped, not stored as -9999 F",
          "outTemp" in record, False)
    check("an empty value is dropped", "dewpoint" in record, False)
    check("'N/A' is dropped", "barometer" in record, False)
    check("a real zero is kept", record.get("windSpeed"), 0.0)
    check("and the good reading survives", record.get("outHumidity"), 55.0)


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
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        live = LiveStore(Path(raw) / "live.sdb", interval_seconds=300)
        listener = HttpListener(Ingest(live, token=TOKEN), "127.0.0.1", 0)
        heard = io.StringIO()
        handler = logging.StreamHandler(heard)
        logger = logging.getLogger("weewx_evo.ingest.listener")
        before = logger.level
        logger.setLevel(logging.DEBUG)
        logger.addHandler(handler)
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
            # Stored under the console's own names and its own values.
            # A string, because that is what came off the wire: the
            # split into numbers and text happens when a record is
            # built, and doing it here is what used to throw away
            # everything that would not parse as a float.
            check("read by the WU driver, not the default one",
                  stored[0].data.get("baromin"), "29.92")
            check("and it is a number by the time it is a reading",
                  drivers.place_with(
                      drivers.get("wunderground"), stored[0].data,
                      stored[0].dialect, {}).record.get("barometer"),
                  29.92)
            check("and it says which vocabulary that is",
                  stored[0].dialect, "wunderground")
            # Friendly names are listener-owned metadata. Without an
            # announcement, every downstream decision uses the immutable
            # sender id rather than promoting a wire value to configuration.
            check("under its canonical unannounced sender id",
                  placement.Placer("default", placement.Placements(),
                                   None).name_of(stored[0]),
                  sender_id("wunderground", "KTEST5"))

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
            logger.removeHandler(handler)
            logger.setLevel(before)
        check("the request log does not contain the token", TOKEN in heard.getvalue(),
              False)
        check("or a query carrying console credentials",
              "PASSWORD=" in heard.getvalue(), False)


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
