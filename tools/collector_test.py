#!/usr/bin/env python3
"""A collector gives its packets a distinct canonical sender identity.

The point of naming a collector. A WeeWX driver used to deliver at
`/<token>/json/`, so the listener recorded its packets as driver `json` --
and `stations.by_identity(driver, identity)` matches on **both**. Two
collectors were therefore one driver with two identities. The listener must
store both unchanged; a Place then selects their canonical IDs and applies
its relationship policy.

So a configured collector claims its own endpoint, and this measures that it
really is one -- not that the code path exists, but that a packet sent by a
collector reaches the live journal under the right canonical sender and is
interpreted only by the Place.

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
    from weewx_evo import collectors, placement
    from weewx_evo import stations as station_defs
    from weewx_evo.archives import Archive, MemberPolicy
    from weewx_evo.db.live import LiveStore, Packet, sender_id
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

        # -- display metadata, one sender per collector ----------------
        # Both consoles are a WH1080 and both report themselves as one --
        # `hardware_name` is the model, not a serial. Which collector they
        # came through is the only thing telling them apart.
        (work / "stations.toml").write_text("""
[stations.Shed]
driver = "shed"
identity = "WH1080 (USB)"

[stations.Roof]
driver = "roof"
identity = "WH1080 (USB)"
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
                                identity="WH1080 (USB)", kind="loop",
                                interval=None)),
                ("roof", Packet(dateTime=now, usUnits=16,
                                data={"outTemp": 18.4, "inTemp": 24.0,
                                      "outHumidity": 55.0},
                                identity="WH1080 (USB)", kind="loop",
                                interval=None))):
            push([packet], host="127.0.0.1", port=port, as_driver=name)

        time.sleep(0.4)
        arrived = list(store.packets(now - 60, now + 60))

        # Stored under the pair the console uploads with, not under a name.
        # Both are a `WH1080 (USB)`; the collector is the whole difference,
        # and it is what makes the register's answer two stations rather
        # than one with two readings a second apart.
        check("two packets, told apart by their collector",
              sorted((p.driver, p.identity) for p in arrived),
              [("roof", "WH1080 (USB)"), ("shed", "WH1080 (USB)")])

        # And nothing was left out on the way in -- which is the point of the
        # table. The Place applies the archive relationship only when a record
        # is built, so it is rebuildable rather than lost at ingest.
        from_shed = [p.data for p in arrived if p.driver == "shed"]
        check("the shed's indoor reading is in the table",
              (from_shed[0] if from_shed else {}).get("inTemp"), 21.3)

        shed_id = sender_id("shed", "WH1080 (USB)")
        roof_id = sender_id("roof", "WH1080 (USB)")
        place = Archive(
            name="default", file=str(work / "archive.sdb"),
            stations=(shed_id, roof_id),
            members={
                shed_id: MemberPolicy(indoor=False),
                roof_id: MemberPolicy(role="extra", channel=3),
            })
        placer = placement.Placer(
            place, placement.Placements(), directory=book, registry=registry)
        placed = {p.sender_id: p for p in
                  (placer.place(one) for one in arrived) if p is not None}
        print(f"  placed as: {sorted(placed)}")
        check("two canonical senders, once placed", sorted(placed),
              sorted([roof_id, shed_id]))

        shed = placed.get(shed_id)
        roof = placed.get(roof_id)

        # This Place excludes the shed sender's indoor readings.
        check("the shed's indoor reading is not in the record",
              "inTemp" in (shed.data if shed else {}), False)
        check("its outdoor reading was kept",
              (shed.data if shed else {}).get("outTemp"), 15.2)

        # This Place uses the roof sender as an additional sensor on channel 3.
        check("the roof's outTemp moved to extraTemp3",
              (roof.data if roof else {}).get("extraTemp3"), 18.4)
        check("and outTemp is not in its record",
              "outTemp" in (roof.data if roof else {}), False)
        check("its humidity moved too",
              (roof.data if roof else {}).get("extraHumid3"), 55.0)

        listener.stop()
        thread.join(timeout=2)
        store.close()

        # -- what the running loop watches -----------------------------
        # The endpoints above are claimed once, in `configure_drivers` at
        # startup. So a collector created on the settings page delivered to
        # a name nothing answered to and was refused with a 404 -- the same
        # one a wrong token gets -- until somebody restarted the service,
        # and nothing said so: a collector is a named section, and
        # `needs_restart` only ever answers about the core options.
        #
        # `serve` compares this list every time the file changes and
        # restarts itself when it moves. What has to hold is that it is the
        # same list `register_names` works from -- the candidates, not the
        # winners. A name that was declined is in here on purpose: renaming
        # it is the fix, and the fix has to take effect.
        from weewx_evo.cli import _collector_shape

        print("\nwhat a running process has to restart for")
        watched = _collector_shape(config)
        check("every configured collector is watched, declined ones too",
              watched, sorted(set(claimed) | {"json"}))

        config["collectors"]["barn"] = {"kind": "weewx-driver"}
        check("a collector added to the file changes it",
              _collector_shape(config) != watched, True)

        # Settings are read by the collector's own process when it starts,
        # so changing one is none of this process's business. Restarting for
        # it would take the station off the air to no purpose.
        config["collectors"].pop("barn")
        config["collectors"]["shed"]["conf"] = "/etc/weewx/elsewhere.conf"
        check("but changing one's settings does not",
              _collector_shape(config), watched)

        # A kind nothing can run claims no endpoint, so it is not a reason
        # to restart either. `register_names` skips it for the same reason.
        config["collectors"]["ghost"] = {"kind": "something-else"}
        check("and neither does a kind nothing recognises",
              _collector_shape(config), watched)

    print()
    if failures:
        print(f"{failures} check(s) failed")
        return 1
    print("a collector writes one distinct sender; the Place owns its rules")
    return 0


if __name__ == "__main__":
    sys.exit(main())
