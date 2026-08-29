#!/usr/bin/env python3
"""A collector is a station like any other.

The point of naming a collector. A WeeWX driver used to deliver at
`/<token>/json/`, so the listener recorded its packets as driver `json` --
and `stations.by_identity(driver, identity)` matches on **both**. Two
collectors were therefore one driver with two identities, and everything
that hangs off a station came apart with them:

    the archive it writes into          two places in one series
    its role                            a second console not moved aside
    whether its indoor readings count   a shed recorded as a living room
    its field map                       tf_ch1 on the wrong thermometer

So a configured collector claims its own endpoint, and this measures that it
really is one -- not that the code path exists, but that a packet sent by a
collector comes out under the station announced for it, with the station's
rules applied.

    python tools/collector_test.py

No hardware and no WeeWX: the collector's side is `listener.push`, which is
the same three lines a driver in Go would send.
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

failures = 0


def check(what: str, got: object, want: object) -> bool:
    global failures
    ok = got == want
    tail = "" if ok else f"  (wanted {want!r})"
    print(f"  {'ok  ' if ok else 'FAIL'} {what}: {got!r}{tail}")
    failures += 0 if ok else 1
    return ok


def main() -> int:
    from weewx_evo import collectors
    from weewx_evo import stations as station_defs
    from weewx_evo.db.live import LiveStore, Packet
    from weewx_evo.ingest import drivers
    from weewx_evo.ingest.listener import HttpListener, Ingest, push

    print("a collector, its name, and the station announced for it\n")

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        work = Path(raw)

        # -- two collectors, both WeeWX drivers ------------------------
        config = {
            "collectors": {
                "shed": {"kind": "weewx-driver",
                         "conf": "/etc/weewx/shed.conf"},
                "roof": {"kind": "weewx-driver",
                         "conf": "/etc/weewx/roof.conf"},
                # A name something else already answers to. It must be
                # declined rather than allowed to shadow the endpoint.
                "json": {"kind": "weewx-driver", "conf": "/etc/weewx/x.conf"},
            },
        }

        registry = drivers.Registry()
        from weewx_evo.ingest.envelope import EnvelopeDriver

        registry.register("json", EnvelopeDriver())
        claimed = collectors.register_names(registry, config)

        print("registering their endpoints")
        check("both collectors got their own name", sorted(claimed),
              ["roof", "shed"])
        check("a name already taken was declined", "json" in claimed, False)
        check("the envelope endpoint still answers",
              registry.known("json"), True)

        # -- the stations, one per collector ---------------------------
        # Both consoles are a WH1080 and both report themselves as one --
        # `hardware_name` is the model, not a serial. Which collector they
        # came through is the only thing telling them apart.
        (work / "stations.toml").write_text("""
[stations.Shed]
driver = "shed"
identity = "WH1080 (USB)"
archive = "default"
indoor = false

[stations.Roof]
driver = "roof"
identity = "WH1080 (USB)"
archive = "default"
role = "extra"
channel = 3
""", encoding="utf-8")
        book = station_defs.load(work / "stations.toml")

        print("\ntwo consoles, the same identity, different collectors")
        # This is the whole thing. Both consoles are a WH1080 and both report
        # themselves as one, which is what a driver's `hardware_name` gives.
        # Told apart only by which collector they arrived through.
        check("the shed is found by its collector",
              getattr(book.by_identity("shed", "WH1080 (USB)"), "name", None),
              "Shed")
        check("the roof is a different station",
              getattr(book.by_identity("roof", "WH1080 (USB)"), "name", None),
              "Roof")
        check("and neither answers for `json`",
              book.by_identity("json", "WH1080 (USB)"), None)

        # -- a packet, all the way through -----------------------------
        store = LiveStore(work / "live.sdb", interval_seconds=300)
        ingest = Ingest(store, registry=registry, stations=book, token=None)
        listener = HttpListener(ingest, "127.0.0.1", 0)
        thread = listener.start()
        port = listener.port

        print("\nsending as each collector does")
        now = int(time.time())
        for name, packet in (
                ("shed", Packet(dateTime=now, usUnits=16,
                                data={"outTemp": 15.2, "inTemp": 21.3,
                                      "outHumidity": 61.0},
                                source="WH1080 (USB)", kind="loop",
                                interval=None)),
                ("roof", Packet(dateTime=now, usUnits=16,
                                data={"outTemp": 18.4, "inTemp": 24.0,
                                      "outHumidity": 55.0},
                                source="WH1080 (USB)", kind="loop",
                                interval=None))):
            push([packet], host="127.0.0.1", port=port, as_driver=name)

        time.sleep(0.4)
        arrived = list(store.packets(now - 60, now + 60))
        by_source = {p.source: p for p in arrived}
        print(f"  arrived: {sorted(by_source)}")

        check("two packets, under two station names", sorted(by_source),
              ["Roof", "Shed"])

        shed = by_source.get("Shed")
        roof = by_source.get("Roof")

        # The shed said `indoor = False`, so its inTemp is dropped. A console
        # in a shed measures a shed, and that is not a living room.
        check("the shed's indoor reading was left out",
              "inTemp" in (shed.data if shed else {}), False)
        check("its outdoor reading was kept",
              (shed.data if shed else {}).get("outTemp"), 15.2)

        # The roof is an `extra` station on channel 3, so its readings are
        # moved out of the main station's way rather than taking turns in
        # the same column.
        check("the roof's outTemp moved to extraTemp3",
              (roof.data if roof else {}).get("extraTemp3"), 18.4)
        check("and outTemp is not in its packet",
              "outTemp" in (roof.data if roof else {}), False)
        check("its humidity moved too",
              (roof.data if roof else {}).get("extraHumid3"), 55.0)

        listener.stop()
        thread.join(timeout=2)
        store.close()

    print()
    if failures:
        print(f"{failures} check(s) failed")
        return 1
    print("a collector is a station: its own name, its own rules")
    return 0


if __name__ == "__main__":
    sys.exit(main())
