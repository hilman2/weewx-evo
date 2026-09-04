#!/usr/bin/env python3
"""Which console a live reading comes from, when a site has more than one.

An archive record is worked out from every packet in the interval, with
`sources.py` deciding field by field which station supplies which reading.
A live reading is one packet, so that machinery has nothing to work with --
something has to say which console.

Until this existed the answer was "whichever reported last", and on a site
with a garden console and a shed sensor that makes a page flicker between
two temperatures every few seconds, both of them true.

    python tools/livesource_test.py

No service and no network: the question is which row comes back out of a
table, and that is answerable with a table.
"""

from __future__ import annotations

import json
import sqlite3
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


def table(work: Path, rows: list[tuple]) -> Path:
    """A live table holding those packets.

    Written column by column rather than positionally. A row here is a
    console's own reading under its own name, keyed by the (driver,
    identity) pair the real table records -- the station name each one
    answers to is a lookup, and `Live` makes it through the register.
    """
    from weewx_evo.db.live import sender_id

    db = work / "live.sdb"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE packet (dateTime INTEGER, seq INTEGER, "
                 "driver TEXT, identity TEXT, sender TEXT, dialect TEXT, "
                 "usUnits INTEGER, interval INTEGER, data TEXT)")
    conn.executemany(
        "INSERT INTO packet (dateTime, seq, driver, identity, sender, dialect,"
        " usUnits, interval, data) VALUES (?,?,'json',?,?,NULL,?,?,?)",
        [(when, seq, source, sender_id("json", source), units, gap, data)
         for when, seq, source, units, gap, data in rows])
    conn.commit()
    conn.close()
    return db


def _placer(sources, placements=None):
    """The live DB's sender directory with a display label for each console.

    The names in `sources` are what a site's configuration lists. The table
    is keyed on (driver, identity), so something has to turn one into the
    other, and that something is the same live-side directory the archiver
    uses -- no station configuration or driver is involved.
    """
    from weewx_evo import placement
    from weewx_evo.db.live import SenderIdentity, sender_id

    directory = [SenderIdentity(sender=sender_id("json", name), driver="json",
                                identity=name, label=name)
                 for name in sources]
    return placement.Placer("default", placements or placement.Placements(),
                            directory)


def reading(db: Path, pick: str, sources=("garten", "schuppen"),
            main=("garten",), policy=None, placer=None) -> dict:
    from weewx_evo.uploads.records import Live

    selected = None if sources is None else list(sources)
    live = Live(db, sources=selected, pick=pick, main=list(main), policy=policy,
                placer=placer or _placer(sources or ()))
    try:
        got = live.after(0, 1)
        return got[0] if got else {}
    finally:
        live.close()


def both_reporting() -> None:
    """Two consoles, both fresh, the shed newer."""
    print("\ntwo consoles, both reporting")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        now = int(time.time())
        # The garden is a minute old and the shed ten seconds. Both well
        # inside the staleness window, so `main-or-extra` must not switch.
        db = table(Path(raw), [
            (now - 60, 1, "garten", 16, None,
             json.dumps({"outTemp": 20.0, "outHumidity": 50.0,
                         "windDir": 350.0, "barometer": 1013.0})),
            (now - 10, 2, "schuppen", 16, None,
             json.dumps({"outTemp": 10.0, "outHumidity": 80.0,
                         "windDir": 10.0})),
        ])

        check("main is the station's own reading",
              reading(db, "main").get("outTemp"), 20.0)
        check("newest is whichever spoke last",
              reading(db, "newest").get("outTemp"), 10.0)
        check("extra is the other one",
              reading(db, "extra").get("outTemp"), 10.0)
        # Both are fresh, so this is the main one -- the whole point of the
        # setting being "or" and not "and".
        check("main-or-extra keeps the main one while it is talking",
              reading(db, "main-or-extra").get("outTemp"), 20.0)

        averaged = reading(db, "average")
        check("average is the mean", averaged.get("outTemp"), 15.0)
        check("of every field", averaged.get("outHumidity"), 65.0)
        # A direction is circular: 350 and 10 meet at north, not at the
        # arithmetic mean of 180 degrees.
        check("directions use their circular mean", averaged.get("windDir"), 0.0)
        # A field only one console reports is that console's value. The mean
        # of one number is that number, and leaving it out would lose a
        # reading nothing else has.
        check("a reading only one of them has still comes through",
              averaged.get("barometer"), 1013.0)


def a_sender_is_addressed_either_way() -> None:
    """Selected by its canonical id, and by the pair that id decodes to.

    Both reach the same rows, because both are in the table. A place holds
    the id; a caller with a (driver, identity) pair in hand -- the status
    page, a diagnostic -- should not have to build one to ask.
    """
    print("\na console addressed by id and by pair")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        from weewx_evo.db.live import sender_id

        now = int(time.time())
        db = table(Path(raw), [
            (now - 20, 1, "garten", 16, None,
             json.dumps({"outTemp": 20.0})),
            (now - 10, 2, "schuppen", 16, None,
             json.dumps({"outTemp": 10.0})),
        ])
        senders = (sender_id("json", "garten"),
                   sender_id("json", "schuppen"))
        check("by canonical id",
              reading(db, "average", sources=senders, main=(senders[0],),
                      placer=_placer(("garten", "schuppen"))).get("outTemp"),
              15.0)
        check("and by the name the directory resolves",
              reading(db, "main").get("outTemp"), 20.0)


def averaging_normalises_each_packet() -> None:
    """Placement, quality and units all happen before arithmetic."""
    print("\nnormalising packets before averaging")
    from weewx_evo import placement, quality, units
    from weewx_evo.db.live import sender_id

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        now = int(time.time())
        db = table(Path(raw), [
            # 68 F and 20 C are the same temperature. The unknown field is
            # deliberately different: with no unit group it must not be mixed
            # across systems and merely relabelled as metric.
            (now - 20, 1, "garten", units.US, None,
             json.dumps({"outTemp": 68.0, "mystery": 100.0})),
            (now - 10, 2, "schuppen", units.METRIC, None,
             json.dumps({"outTemp": 20.0, "mystery": 10.0})),
        ])
        averaged = reading(db, "average")
        check("equal temperatures in different systems stay equal",
              averaged.get("outTemp"), 20.0)
        check("the result names the common system", averaged.get("usUnits"),
              units.METRIC)
        check("an unknown mixed-unit field is not falsely averaged",
              averaged.get("mystery"), 10.0)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        now = int(time.time())
        db = table(Path(raw), [
            (now - 20, 1, "garten", units.METRIC, None,
             json.dumps({"rawTemp": 10.0})),
            (now - 10, 2, "schuppen", units.METRIC, None,
             json.dumps({"rawTemp": 20.0})),
        ])
        placements = placement.Placements(takes=[
            placement.Takes(archive="default",
                            station=sender_id("json", "garten"),
                            fields={"rawTemp": "outTemp"}),
            placement.Takes(archive="default",
                            station=sender_id("json", "schuppen"),
                            fields={"rawTemp": "outTemp"}),
        ])
        placer = _placer(("garten", "schuppen"), placements)
        policy = quality.Policy(calibration={
            sender_id("json", "garten"): {
                "outTemp": quality.Adjust(offset=2.0)},
            sender_id("json", "schuppen"): {
                "outTemp": quality.Adjust(offset=4.0)},
        })
        averaged = reading(db, "average", policy=policy, placer=placer)
        check("placement precedes station calibration and averaging",
              averaged.get("outTemp"), 18.0)
        check("the raw name does not leak through", "rawTemp" in averaged, False)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        now = int(time.time())
        db = table(Path(raw), [
            (now - 20, 1, "garten", units.METRIC, None,
             json.dumps({"outTemp": 20.0})),
            (now - 10, 2, "schuppen", units.METRIC, None,
             json.dumps({"outTemp": 100.0})),
        ])
        policy = quality.Policy(
            limits={"outTemp": quality.Rule(maximum=50.0)},
            system=units.METRIC)
        averaged = reading(db, "average", policy=policy)
        check("a rejected packet cannot contaminate the average",
              averaged.get("outTemp"), 20.0)


def the_main_one_goes_quiet() -> None:
    """The garden console stops. `main-or-extra` is what this is for."""
    print("\nthe main console goes quiet")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        now = int(time.time())
        db = table(Path(raw), [
            (now - 4000, 1, "garten", 16, None,
             json.dumps({"outTemp": 20.0})),
            (now - 10, 2, "schuppen", 16, None,
             json.dumps({"outTemp": 10.0})),
        ])

        check("main still says the main one, silent or not",
              reading(db, "main").get("outTemp"), 20.0)
        check("main-or-extra falls back",
              reading(db, "main-or-extra").get("outTemp"), 10.0)


def the_whole_site_is_quiet() -> None:
    """Everything stopped hours ago. Nothing is stale relative to anything.

    Measured against the newest packet in the table rather than the clock,
    so a station switched off for a week does not read as "the main console
    has failed" -- and neither does one whose container has a clock adrift.
    """
    print("\nthe whole site is quiet")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        old = int(time.time()) - 86400
        db = table(Path(raw), [
            (old, 1, "garten", 16, None, json.dumps({"outTemp": 20.0})),
            (old - 30, 2, "schuppen", 16, None, json.dumps({"outTemp": 10.0})),
        ])
        check("main-or-extra stays with the main one",
              reading(db, "main-or-extra").get("outTemp"), 20.0)


def nobody_announced_anything() -> None:
    """No stations announced, which is most installations.

    Every pick has to collapse to "the newest", because there is nothing to
    pick between -- and that is what this did before the setting existed.
    """
    print("\nno stations announced")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        now = int(time.time())
        db = table(Path(raw), [
            (now - 60, 1, "one", 16, None, json.dumps({"outTemp": 20.0})),
            (now - 10, 2, "two", 16, None, json.dumps({"outTemp": 10.0})),
        ])
        for pick in ("main", "main-or-extra", "extra", "newest"):
            check(f"{pick} is the newest packet",
                  reading(db, pick, sources=None, main=()).get("outTemp"), 10.0)


def one_console() -> None:
    """The ordinary station. Every setting has to answer the same."""
    print("\none console, which is nearly every station")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        now = int(time.time())
        db = table(Path(raw), [
            (now - 10, 1, "garten", 16, None, json.dumps({"outTemp": 20.0})),
        ])
        for pick in ("main", "main-or-extra", "newest", "average", "extra"):
            check(f"{pick} gives the one reading there is",
                  reading(db, pick, sources=("garten",),
                          main=("garten",)).get("outTemp"), 20.0)


def an_explicitly_empty_place_reads_nothing() -> None:
    """An empty assignment is not the legacy unfiltered view."""
    print("\nan explicitly empty place")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
        now = int(time.time())
        db = table(Path(raw), [
            (now - 40, 1, "garten", 16, None,
             json.dumps({"outTemp": 20.0})),
            (now - 30, 2, "garten", 16, None,
             json.dumps({"outTemp": 21.0})),
            (now - 20, 3, "garten", 16, None,
             json.dumps({"outTemp": 22.0})),
            (now - 10, 4, "garten", 16, None,
             json.dumps({"outTemp": 23.0})),
        ])

        from weewx_evo.uploads.records import Live

        unbound = Live(db, main=["garten"], placer=_placer(["garten"]))
        try:
            check("None keeps the legacy unfiltered view",
                  unbound.after(0, 1)[0].get("outTemp"), 23.0)
            for pick in Live.PICKS:
                empty = unbound.for_sources([], pick)
                try:
                    check(f"{pick} returns no current reading",
                          empty.after(0, 1), [])
                    check(f"{pick} returns no later reading",
                          empty.after(now - 60, 10), [])
                    check(f"{pick} measures no rhythm",
                          empty.rhythm(now), None)
                finally:
                    empty.close()

            unknown = unbound.for_sources(["unbekannt"], "average")
            try:
                check("an unknown explicit source returns no reading",
                      unknown.after(0, 1), [])
                check("an unknown explicit source measures no rhythm",
                      unknown.rhythm(now), None)
            finally:
                unknown.close()
        finally:
            unbound.close()


def main() -> int:
    print("which console a live reading comes from")
    both_reporting()
    a_sender_is_addressed_either_way()
    averaging_normalises_each_packet()
    the_main_one_goes_quiet()
    the_whole_site_is_quiet()
    nobody_announced_anything()
    one_console()
    an_explicitly_empty_place_reads_nothing()

    print()
    if failures:
        print(f"{failures} check(s) failed")
        return 1
    print("a page shows one console's readings, and says which")
    return 0


if __name__ == "__main__":
    sys.exit(main())
