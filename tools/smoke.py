"""Drive the whole thing once, end to end, against a throwaway database.

Starts a listener, posts real Ecowitt uploads at it, lets the archiver work the
intervals out, and checks what landed. This is the test that catches the
mistakes the unit-level ones cannot: a parser whose field names do not match
the schema, an archiver that writes a record with no `interval`, a listener
that answers before it has stored anything.

    python tools/smoke.py

Nothing outside a temporary directory is touched.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from weewx_evo.archiver import Archiver
from weewx_evo.db.archive import ArchiveStore
from weewx_evo.db.live import LiveStore
from weewx_evo.ingest.listener import HttpListener, Ingest

TOKEN = "smoke-token"
INTERVAL = 60

# A real upload from the Kirchdorf HP2561AE Pro, trimmed to the fields that
# matter here. Hand-written test data would agree with the parser by
# construction; this does not.
UPLOAD = (
    "PASSKEY=3178AB6B42A759F51A5A4AD72E37F8DE&stationtype=EasyWeatherPro_V5.1.6"
    "&dateutc=now&tempinf={intemp}&humidityin=60&baromrelin=30.032&baromabsin=28.538"
    "&tempf={temp}&humidity=82&winddir={dir}&windspeedmph={wind}&windgustmph={gust}"
    "&maxdailygust=3.36&solarradiation=196.84&uv=1&rainratein=0.0&eventrainin=0.091"
    "&hourlyrainin=0.0&dailyrainin=0.012&weeklyrainin=0.091&monthlyrainin=0.091"
    "&soilmoisture1=32&soilad1=953&tf_ch1=65.5&tf_ch2=75.7&lightning_num=0"
)


def post(url: str, body: str) -> tuple[str, str]:
    """Returns (body, content type). Both matter: the gateway checks them."""
    request = urllib.request.Request(url, data=body.encode(),
                                     headers={"Content-Type":
                                              "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.read().decode().strip(), response.headers.get("Content-Type", "")


def check(label: str, got: object, want: object) -> bool:
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: {got!r}" + ("" if ok else f" != {want!r}"))
    return ok


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="weewx-evo-smoke-"))
    failures = 0
    try:
        from weewx_evo.ingest import drivers
        print(f"drivers available: {', '.join(drivers.names())}")
        if not drivers.known("ecowitt"):
            print("  the ecowitt driver is not loaded. Point WEEWX_EVO_ECOWITT at a"
                  " weewx-ecowitt checkout; this test needs it.")
            return 2

        # The ecowitt driver remembers which consoles it has heard, and
        # without a path it remembers them in /var/tmp -- outside this test's
        # directory, so a real console heard on this machine once makes the
        # test's own upload an unknown one and every packet is dropped. Every
        # test here keeps its state where it can delete it.
        drivers.DEFAULT.load()
        drivers.DEFAULT.configure("ecowitt",
                                  {"console_file": str(tmp / "consoles.txt"),
                                   "report_file": str(tmp / "report.txt")})

        live = LiveStore(tmp / "live.sdb", interval_seconds=INTERVAL)
        archive = ArchiveStore(tmp / "weewx.sdb")
        archiver = Archiver(live, archive, interval_seconds=INTERVAL)
        ingest = Ingest(live, token=TOKEN)
        http = HttpListener(ingest, "127.0.0.1", 0)
        http.start()
        base = f"http://127.0.0.1:{http.port}"
        print(f"listener on {base}, databases in {tmp}")

        print("\na fresh database looks like WeeWX made it")
        failures += not check("archive columns", len(archive.schema.columns), 115)
        failures += not check("daily tables", len(archive.schema.day_types), 113)
        failures += not check("wind is a vector", archive.schema.day_types["wind"], "vector")
        failures += not check("summary version", archive.schema.version, "4.0")

        print("\nuploads without the token are refused")
        try:
            post(f"{base}/data/report/", UPLOAD.format(temp=71.2, intemp=74.7,
                                                       dir=245, wind=1.12, gust=2.24))
            failures += not check("no token", "accepted", "404")
        except urllib.error.HTTPError as exc:
            failures += not check("no token", exc.code, 404)
        failures += not check("nothing stored", live.count(), 0)

        print("\nuploads with the token are stored")
        url = f"{base}/{TOKEN}/ecowitt/"
        for i in range(6):
            body = UPLOAD.format(temp=70.0 + i, intemp=74.0 + i * 0.1,
                                 dir=240 + i * 2, wind=1.0 + i * 0.2, gust=2.0 + i * 0.3)
            answer, content_type = post(url, body)
            failures += not check(f"upload {i + 1}", answer,
                                  '{"errcode":"0","errmsg":"ok"}')
            failures += not check(f"  as {content_type}", content_type,
                                  "application/json")
            time.sleep(0.05)
        failures += not check("packets held", live.count(), 6)

        print("\nthe same upload twice is one packet")
        same = UPLOAD.format(temp=99.9, intemp=74.7, dir=245, wind=1.12, gust=2.24)
        post(url, same)
        before = live.count()
        post(url, same)
        failures += not check("no duplicate", live.count(), before)
        failures += not check("duplicate counted", ingest.duplicates >= 1, True)

        print("\nthe archiver works the interval out")
        # The packets are stamped 'now', so their interval closes in the
        # future. Ask for it directly rather than waiting a minute.
        stop, seconds = live.due(now=time.time() + INTERVAL * 2, grace=0)[0]
        built = archiver.build(stop, seconds)
        failures += not check("interval built", built is not None, True)
        assert built is not None
        failures += not check("packets in interval", built.packets, 7)
        failures += not check("interval in minutes", built.record["interval"], INTERVAL / 60)
        failures += not check("outTemp averaged",
                              round(built.record["outTemp"], 4),
                              round((70 + 71 + 72 + 73 + 74 + 75 + 99.9) / 7, 4))
        failures += not check("windDir is a bearing",
                              0 <= built.record["windDir"] <= 360, True)
        failures += not check("rain is a sum, not a mean", "dayRain" in built.record, True)

        print("\nand stores it")
        archiver.process_due(now=time.time() + INTERVAL * 2, grace=0)
        failures += not check("archive records", archive.count(), 1)
        failures += not check("nothing left pending", live.due(now=time.time() + 9999), [])
        record = archive.record(stop)
        assert record is not None
        failures += not check("stored outTemp",
                              round(record["outTemp"], 4),
                              round(built.record["outTemp"], 4))

        print("\nthe daily summary followed")
        from weewx_evo.aggregate import start_of_archive_day
        from weewx_evo.db.daily import read_day
        sod = start_of_archive_day(stop)
        stats = read_day(archive.conn, archive.schema, "outTemp", sod)
        failures += not check("day row written", stats is not None, True)
        assert stats is not None
        failures += not check("day count", stats[5], 1)
        # The LOOP packets sharpened the extremes past what the record holds.
        failures += not check("day max is the LOOP high, not the mean",
                              round(stats[2], 1), 99.9)

        print("\nrunning it again changes nothing")
        archiver.process_due(now=time.time() + 9999, grace=0)
        failures += not check("still one record", archive.count(), 1)
        again = read_day(archive.conn, archive.schema, "outTemp", sod)
        failures += not check("day unchanged", again, stats)

        print("\nstatus reports what happened")
        status = ingest.status()
        failures += not check("accepted", status["accepted"], 7)
        failures += not check("rejected", status["rejected"], 1)

        print("\nthe live page is behind the token")
        def fetch(path: str) -> tuple[int, str, str]:
            try:
                with urllib.request.urlopen(f"{base}{path}", timeout=5) as r:
                    return (r.status, r.read().decode("utf-8", "replace"),
                            r.headers.get("Content-Type", ""))
            except urllib.error.HTTPError as exc:
                return exc.code, "", ""

        for path in ("/live", "/recent", "/status", f"/{TOKEN}x/live"):
            code, _, _ = fetch(path)
            failures += not check(f"without the token {path}", code, 404)

        code, page, ctype = fetch(f"/{TOKEN}/live")
        failures += not check("with the token", code, 200)
        failures += not check("is HTML", ctype.startswith("text/html"), True)
        failures += not check("the token is not in the page", TOKEN in page, False)
        failures += not check("no request goes anywhere else",
                              "http://" in page.replace("http://127.0.0.1", ""), False)

        code, bare, _ = fetch(f"/{TOKEN}/")
        failures += not check("the bare token path is the page too",
                              code == 200 and "<!doctype html>" in bare.lower(), True)

        print("\nand it says what is arriving")
        code, raw, ctype = fetch(f"/{TOKEN}/recent")
        failures += not check("recent is JSON", ctype, "application/json")
        data = json.loads(raw)
        failures += not check("packets listed", len(data["packets"]) > 0, True)
        failures += not check("newest first",
                              data["packets"][0]["dateTime"]
                              >= data["packets"][-1]["dateTime"], True)
        failures += not check("headline has the temperature",
                              any(h["key"] == "outTemp" for h in data["headline"]), True)
        failures += not check("a rate is worked out", data["rate_per_min"] is not None,
                              True)
        # The station is identified by its PASSKEY, which is what somebody
        # would need to forge its readings.
        shown = {p["source"] for p in data["packets"]}
        failures += not check("the PASSKEY is shortened",
                              any(len(s) <= 12 for s in shown), True)

        print("\nthe raw upload is there, with the PASSKEY taken out")
        # This is the point of keeping it: a field the driver could not place
        # is by definition absent from the parsed packet, so only the body can
        # show it. That makes it what an issue about a new sensor needs.
        raw = data["packets"][0]["raw"]
        failures += not check("kept", raw is not None, True)
        failures += not check("it is the upload", "stationtype=EasyWeatherPro" in raw,
                              True)
        failures += not check("with a field the driver did place",
                              "tempf=" in raw, True)
        failures += not check("and one it would not",
                              "tf_ch1=" in raw, True)
        failures += not check("PASSKEY redacted by the driver",
                              "3178AB6B42A759F51A5A4AD72E37F8DE" in raw, False)
        failures += not check("the key is still named", "PASSKEY=" in raw, True)

        print("\nand it is forgotten on its own")
        failures += not check("forgetting is per packet, not per retention",
                              live.forget_raw(time.time() + 1) > 0, True)
        after = json.loads(fetch(f"/{TOKEN}/recent")[1])
        failures += not check("gone", after["packets"][0]["raw"], None)
        failures += not check("the packet itself stays",
                              after["packets"][0]["fields"],
                              data["packets"][0]["fields"])

        http.stop()
        live.close()
        archive.close()
        print("\nwhat the driver calls its own fields reaches the core")
        # The core's table is the standard schema and nothing else. A station
        # with a soil probe, a lightning sensor and four extra thermometers
        # has a hundred columns that are not in it, and only the driver knows
        # what they measure.
        #
        # This was declared and never asked for: `unit_groups()` existed on
        # the driver, `group_of` took an `extra`, and the ten places that
        # format a value never got one. Every such column came out bare -- the
        # right number, in whatever the console sent, on a page where
        # everything beside it was converted.
        from weewx_evo import units
        from weewx_evo.cli import install_driver_groups

        before = units.unit_of("extraTemp9", units.METRICWX)
        failures += not check("the core does not know extraTemp9 on its own",
                              before, (None, None))

        install_driver_groups()

        stored, group = units.unit_of("extraTemp9", units.US)
        failures += not check("the driver says it is a temperature", group,
                              "group_temperature")
        failures += not check("so a US archive holds it in Fahrenheit",
                              stored, "degree_F")
        failures += not check("and a metric page asks for Celsius",
                              units.unit_of("extraTemp9", units.METRICWX)[0],
                              "degree_C")

        # Groups WeeWX has no unit for at all. Without one the value is typed
        # and still printed bare, which is the same failure one step later.
        for reading, wanted in (("soilEC1", "microsiemens_per_centimeter"),
                                ("vpd", "kPa"),
                                ("wh65_rssi", "dBm")):
            failures += not check(f"{reading} has a unit",
                                  units.unit_of(reading, units.METRICWX)[0],
                                  wanted)
        failures += not check("and something to print after it",
                              units.label("microsiemens_per_centimeter"),
                              " \u00b5S/cm")

        # The standard schema still wins where it has an answer, and the
        # merged view is what a WeeWX skin extension reads.
        failures += not check("outTemp is still what it always was",
                              units.group_of("outTemp"), "group_temperature")
        everything = units.all_groups()
        failures += not check("both tables are in the merged view",
                              ("outTemp" in everything
                               and "extraTemp9" in everything), True)

        # A call that hands its own table still wins: a feed may know better
        # than the driver about its own columns.
        failures += not check("a caller's own table beats both",
                              units.group_of("extraTemp9",
                                             extra={"extraTemp9": "group_percent"}),
                              "group_percent")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + ("FAIL" if failures else "PASS") + f" ({failures} failure(s))")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
