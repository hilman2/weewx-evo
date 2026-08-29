#!/usr/bin/env python3
"""Placing a reading, with the one number that makes it safe.

A reading put in a column that already holds another sensor's history mixes
two series, and nothing afterwards can separate them: they are the same
number in the same row. So the decision needs the count, and the count is
what a log line cannot give you.

What this checks, and the third one is the reason it exists:

    the column exists                      or the row offers to make it
    the column already holds readings      and says how many
    another station of the same archive    fills it, and says which
    another station of a *different* one   does not, because that is two
                                           places rather than a collision

The last two are the same query one archive apart, and getting them the same
way round would either cry wolf on every second site or say nothing on the
one arrangement that can ruin a series.

    python tools/adminfields_test.py
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from weewx_evo import adminfields  # noqa: E402
from weewx_evo.admin import Admin  # noqa: E402
from weewx_evo.cli import all_schemas  # noqa: E402
from weewx_evo.db.archive import ArchiveStore  # noqa: E402

failures = 0
TOKEN = "abcdefghij123456"


def a_workspace():
    """A temporary directory that does not fail the run while emptying itself.

    Windows keeps a database file locked for a moment after SQLite has closed
    it, so the cleanup raises where the same code on Linux does not. Ignoring
    that would also hide a connection genuinely left open -- which is the bug
    that once put 477 of them on the VPS -- so the run ends by counting the
    open connections instead. That measures the property directly rather than
    inferring it from whether a directory could be removed.
    """
    return tempfile.TemporaryDirectory(ignore_cleanup_errors=True)


def check(what: str, got: object, want: object) -> bool:
    global failures
    ok = got == want
    tail = "" if ok else f"  (wanted {want!r})"
    print(f"  {'ok  ' if ok else 'FAIL'} {what}: {got!r}{tail}")
    failures += 0 if ok else 1
    return ok


def an_installation(work: Path, *, two_archives: bool = False,
                    stations: str = "") -> Admin:
    (work / "data").mkdir(exist_ok=True)
    (work / "evo.toml").write_text(
        f'token = "{TOKEN}"\n'
        f'archive_db = "{(work / "data" / "weewx.sdb").as_posix()}"\n'
        f'live_db = "{(work / "data" / "live.sdb").as_posix()}"\n',
        encoding="utf-8")
    if two_archives:
        (work / "archives.toml").write_text(
            "[archives.default]\n"
            f'file = "{(work / "data" / "weewx.sdb").as_posix()}"\n\n'
            "[archives.nordfeld]\n"
            f'file = "{(work / "data" / "nord.sdb").as_posix()}"\n',
            encoding="utf-8")
    (work / "stations.toml").write_text(stations or (
        '[stations.kirchdorf]\ndriver = "ecowitt"\n'
        'identity = "AAAA"\narchive = "default"\n'), encoding="utf-8")
    path = work / "evo.toml"
    return Admin(path, lambda: all_schemas(path), TOKEN)


def an_archive(path: Path, filled: dict[str, int] | None = None,
               ended: float = 0.0) -> None:
    """An archive with some columns holding some number of readings.

    `ended` is how many hours before the newest record those columns stop.
    Zero means they run right up to it, which is what a working sensor looks
    like; anything past an hour is history somebody has to decide about
    before writing a second sensor into the same column.

    There is always a record at `now`, whatever `ended` says. Without one the
    two ends of the comparison are the same row and every column looks
    current -- which is exactly the case this distinction exists to separate.
    """
    store = ArchiveStore(path)
    try:
        now = int(time.time())
        store.conn.execute(
            "INSERT OR REPLACE INTO archive (dateTime, usUnits, `interval`, "
            "outTemp) VALUES (?, ?, ?, ?)", (now, 1, 5, 19.0))
        stop = now - int(ended * 3600)
        for field, count in (filled or {}).items():
            if not store.schema.has_column(field):
                store.add_column(field)
            for n in range(count):
                store.conn.execute(
                    f"INSERT OR REPLACE INTO archive (dateTime, usUnits, "
                    f"`interval`, {field}) VALUES (?, ?, ?, ?)",
                    (stop - n * 300, 1, 5, 20.0 + n))
        store.conn.commit()
    finally:
        store.close()


def a_field_with_nowhere_to_go() -> None:
    print("\na reading the archive has no column for")
    with a_workspace() as raw:
        work = Path(raw)
        admin = an_installation(work)
        an_archive(work / "data" / "weewx.sdb")
        station = next(iter(
            __import__("weewx_evo.stations", fromlist=["load"]).load(
                work / "stations.toml")))

        rows = adminfields.placements(
            admin, station, {"tf_ch1": 65.5},
            catalog={"tf_ch1": "extraTemp9"})
        one = rows[0]
        check("it is placed by the catalog", one.field, "extraTemp9")
        check("but the archive has no column", one.column, False)
        check("which is what the row says", one.state, "nocolumn")
        check("and the value is there to judge it by", one.value, 65.5)


def a_column_that_already_holds_something() -> None:
    """The number that makes the decision safe -- and whose readings they are.

    Both halves, and the second is why this is worth a test of its own. The
    first version warned about every column holding anything, so a station
    that had been recording for a year had thirty-four orange rows, and the
    one where a placement would have destroyed a series read exactly like the
    thirty-three where it would not.
    """
    print("\na column whose history stopped two days ago")
    with a_workspace() as raw:
        work = Path(raw)
        admin = an_installation(work)
        an_archive(work / "data" / "weewx.sdb", {"extraTemp9": 300},
                   ended=48.0)
        station = next(iter(
            __import__("weewx_evo.stations", fromlist=["load"]).load(
                work / "stations.toml")))

        rows = adminfields.placements(admin, station, {"tf_ch1": 65.5},
                                      catalog={"tf_ch1": "extraTemp9"})
        one = rows[0]
        check("the column is there", one.column, True)
        check("and it says how much is in it", one.holds, 300)
        check("which is a warning, not a green light", one.state, "occupied")
        check("with the date that makes it actionable", bool(one.last), True)

        # An empty column of the same archive is the other answer.
        rows = adminfields.placements(admin, station, {"tf_ch2": 66.0},
                                      catalog={"tf_ch2": "extraTemp10"})
        check("an unused one says so", rows[0].state, "nocolumn")


def a_column_being_written_right_now() -> None:
    """The ordinary case, which must not read as a warning.

    The same 300 readings as above. The only difference is that they run up
    to the newest record in the file, and that is the whole distinction: two
    facts out of one database, never a wall clock, so a station that has been
    offline for a week compares the same way as one uploading this minute.
    """
    print("\nthe same column, still being filled")
    with a_workspace() as raw:
        work = Path(raw)
        admin = an_installation(work)
        an_archive(work / "data" / "weewx.sdb", {"extraTemp9": 300})
        station = next(iter(
            __import__("weewx_evo.stations", fromlist=["load"]).load(
                work / "stations.toml")))

        rows = adminfields.placements(admin, station, {"tf_ch1": 65.5},
                                      catalog={"tf_ch1": "extraTemp9"})
        one = rows[0]
        check("the history in it is this station's own", one.mine, True)
        check("so it is not a warning", one.state, "mine")
        check("and the count is still there to be read", one.holds, 300)


def another_station_of_the_same_archive() -> None:
    print("\ntwo stations of one archive on one column")
    with a_workspace() as raw:
        work = Path(raw)
        admin = an_installation(work, stations=(
            '[stations.kirchdorf]\ndriver = "ecowitt"\n'
            'identity = "AAAA"\narchive = "default"\n'
            '[stations.kirchdorf.field_map]\ntf_ch1 = "soilTemp1"\n\n'
            '[stations.garten]\ndriver = "ecowitt"\n'
            'identity = "BBBB"\narchive = "default"\n'))
        an_archive(work / "data" / "weewx.sdb", {"soilTemp1": 40})
        from weewx_evo.stations import load

        garten = load(work / "stations.toml").by_name("garten")
        rows = adminfields.placements(admin, garten, {"tf_ch2": 12.0},
                                      catalog={"tf_ch2": "soilTemp1"})
        one = rows[0]
        check("the other station is named", one.holder, "kirchdorf/tf_ch1")
        check("and that is what the row is about", one.state, "taken")

        # The station that owns it is not warned about itself.
        kirchdorf = load(work / "stations.toml").by_name("kirchdorf")
        mine = adminfields.placements(admin, kirchdorf, {"tf_ch1": 20.0})
        check("its own placement is not a collision", mine[0].holder, "")
        check("it is the column it is filling", mine[0].state, "mine")


def another_station_of_a_different_archive() -> None:
    """The case upstream cannot have, and the one our layer adds.

    Two stations writing `soilTemp1` into two different files are two places.
    Warning about it would be crying wolf on the arrangement archives exist
    for.
    """
    print("\ntwo stations, two archives, one field name")
    with a_workspace() as raw:
        work = Path(raw)
        admin = an_installation(work, two_archives=True, stations=(
            '[stations.kirchdorf]\ndriver = "ecowitt"\n'
            'identity = "AAAA"\narchive = "default"\n'
            '[stations.kirchdorf.field_map]\ntf_ch1 = "soilTemp1"\n\n'
            '[stations.nordhof]\ndriver = "ecowitt"\n'
            'identity = "BBBB"\narchive = "nordfeld"\n'))
        an_archive(work / "data" / "weewx.sdb", {"soilTemp1": 40})
        an_archive(work / "data" / "nord.sdb")
        from weewx_evo.stations import load

        nordhof = load(work / "stations.toml").by_name("nordhof")
        rows = adminfields.placements(admin, nordhof, {"tf_ch1": 12.0},
                                      catalog={"tf_ch1": "soilTemp1"})
        one = rows[0]
        check("nobody is said to hold it", one.holder, "")
        # Its own archive has the column -- a fresh file gets the standard
        # schema -- and nothing has written to it. That is `ready`, and it
        # is the whole point: the same field name in another file is not a
        # collision, it is another place.
        check("and its own archive's column is empty", one.holds, 0)
        check("so the row is clear", one.state, "ready")

        # While the station that does hold it sees its own history.
        kirchdorf = load(work / "stations.toml").by_name("kirchdorf")
        mine = adminfields.placements(admin, kirchdorf, {"tf_ch1": 20.0})
        check("in the other archive, the same name has 40 values",
              mine[0].holds, 40)


def placing_and_making_the_column() -> None:
    print("\nsaving a placement, and creating what it needs")
    with a_workspace() as raw:
        work = Path(raw)
        admin = an_installation(work)
        an_archive(work / "data" / "weewx.sdb")
        from weewx_evo.stations import load

        error = adminfields.place(admin, "kirchdorf", "tf_ch1", "extraTemp9")
        check("it saves", error, "")
        again = load(work / "stations.toml").by_name("kirchdorf")
        check("into the station's own field map",
              again.field_map.get("tf_ch1"), "extraTemp9")

        error = adminfields.add_column(admin, again, "extraTemp9")
        check("and the column can be made from here", error, "")
        rows = adminfields.placements(admin, again, {"tf_ch1": 65.5})
        check("after which the row is ready", rows[0].state, "ready")

        # Twice is not an error worth stopping for, but it is worth saying.
        again2 = adminfields.add_column(admin, again, "extraTemp9")
        check("a second time says so", "already has" in again2, True)


def a_placement_reaches_the_driver() -> None:
    """The half nothing checked, and it was not working.

    Every test here stopped at `stations.toml`: the page wrote the file, the
    file read back, and each of them passed. What none of them asked was
    whether the driver ever sees it -- and it did not. The core hands the
    stations over keyed by the name somebody typed, the lookup is made with
    what the protocol read off the upload, and a PASSKEY is not a name. The
    dictionary never matched.

    It was invisible because the same two decisions were also sitting in the
    driver's own `field_map_extensions`, put there by hand before the page
    existed. So the readings landed in the right columns and the page said
    "saved", and both were true, and the page had done nothing.
    """
    print("\na placement made on the page reaches the driver")
    from weewx_evo.ingest.plugins.push import driver as push
    from weewx_evo.ingest.plugins.push import protocols as protocol_defs

    protocol = next(p for p in protocol_defs.registry()
                    if p.name == "ecowitt")
    upload = {"PASSKEY": "AAAA", "tf_ch1": "59.9", "tempf": "68.2"}
    dialect = protocol.dialect(upload)
    readings = protocol.readings(push._Request(body=b""), upload)

    # Contested on purpose: two drivers disagree about where `tf_ch1` goes,
    # so nothing is written until somebody decides. That makes it the field
    # that shows whether the decision arrived.
    bare = push.driver_class(protocol)()
    packet, _ = bare._mapper_for(dialect, "AAAA").to_packet(readings)
    check("without a decision it is not written",
          "extraTemp9" in packet, False)

    # Keyed by name, exactly as `cli.station_field_maps` hands it over.
    told = push.driver_class(protocol)(stations={"kirchdorf": {
        "passkey": "AAAA",
        "field_map_extensions": {"tf_ch1": "extraTemp9"}}})
    packet, _ = told._mapper_for(dialect, "AAAA").to_packet(readings)
    check("with one it goes where the page said", packet.get("extraTemp9"),
          59.9)
    # Consoles upper-case what is typed into them.
    packet, _ = told._mapper_for(dialect, "aaaa").to_packet(readings)
    check("whatever case the console shouts it in",
          packet.get("extraTemp9"), 59.9)

    # And the clock, which is a property of the box rather than of the six
    # protocols it might be speaking.
    clocks = push.driver_class(protocol)(max_behind=3600, stations={
        "drifty": {"passkey": "BBBB", "max_behind": 1800.0}})
    check("a console can be given its own tolerance",
          clocks._mapper_for(dialect, "BBBB").max_behind, 1800.0)
    check("and the rest keep the configured one",
          clocks._mapper_for(dialect, "CCCC").max_behind, 3600)


def a_protocol_has_nothing_to_configure() -> None:
    """Six protocols arrived at once; six settings pages did not follow.

    Each carried the same three fields, and all three describe either a
    policy of the installation or a property of a console.
    """
    print("\nthe six protocols have no settings page")
    from weewx_evo.cli import all_schemas

    kinds = [s.name for s in all_schemas(None) if s.kind == "driver"]
    check("none of them", kinds, [])

    from weewx_evo import options as option_defs

    core = [o.name for g in option_defs.core_options() for o in g.options]
    for moved in ("infer_unknown", "max_behind", "max_ahead"):
        check(f"{moved} is asked once, in the core", moved in core, True)


def nowhere_is_a_decision() -> None:
    """The other half of resolving a collision."""
    print("\nplacing a reading nowhere, on purpose")
    with a_workspace() as raw:
        work = Path(raw)
        admin = an_installation(work)
        an_archive(work / "data" / "weewx.sdb")
        from weewx_evo.stations import load

        adminfields.place(admin, "kirchdorf", "tf_ch1", adminfields.NOWHERE)
        station = load(work / "stations.toml").by_name("kirchdorf")
        rows = adminfields.placements(admin, station, {"tf_ch1": 65.5},
                                      catalog={"tf_ch1": "extraTemp9"})
        check("the catalog does not get it back", rows[0].field, "")
        check("and it is marked as meant", rows[0].state, "nowhere")

        # Clearing it is not the same as choosing nowhere.
        adminfields.place(admin, "kirchdorf", "tf_ch1", "")
        station = load(work / "stations.toml").by_name("kirchdorf")
        rows = adminfields.placements(admin, station, {"tf_ch1": 65.5},
                                      catalog={"tf_ch1": "extraTemp9"})
        check("cleared, the catalog decides again", rows[0].field,
              "extraTemp9")


def the_chooser_offers_past_the_schema() -> None:
    """`extraTemp12` on a database whose schema stops at eight."""
    print("\nwhat the chooser offers")
    with a_workspace() as raw:
        work = Path(raw)
        admin = an_installation(work)
        an_archive(work / "data" / "weewx.sdb")
        from weewx_evo.stations import load

        station = load(work / "stations.toml").by_name("kirchdorf")
        offered = adminfields.candidates(admin, station)["offered"]
        check("the schema's own columns are there",
              "extraTemp8" in offered, True)
        check("and the next of the family, which has no column yet",
              "extraTemp9" in offered, True)
        check("up to the limit", f"extraTemp{adminfields.UPTO}" in offered,
              True)
        check("but not past it",
              f"extraTemp{adminfields.UPTO + 1}" in offered, False)
        # Not everything that ends in a digit is a family.
        check("pm2_5 is not offered as pm2_6", "pm2_6" in offered, False)


def the_rows_are_raw_names_not_mapped_ones() -> None:
    """What the hardware calls it, not what it was turned into.

    The first version read the stored packet, which holds the mapping's
    *output* -- `barometer`, `extraTemp9`. Every row then offered to place a
    field that had just been written, and said "not written" about it,
    because no catalog has a raw field called `extraTemp9`.

    A placement is a decision about `baromrelin` and `tf_ch1`. Those are in
    the kept upload, which is why it is kept.
    """
    print("\nthe rows are what the hardware sends")
    from weewx_evo.adminstations import what_it_sends
    from weewx_evo.db.live import LiveStore, Packet
    from weewx_evo.stations import load

    with a_workspace() as raw:
        work = Path(raw)
        admin = an_installation(work)
        an_archive(work / "data" / "weewx.sdb")

        upload = ("PASSKEY=X&stationtype=GW2000A&dateutc=now"
                  "&baromrelin=29.923&tf_ch1=68.2&tempf=64.9")
        live = LiveStore(work / "data" / "live.sdb", interval_seconds=300)
        live.add(Packet(dateTime=int(time.time()), usUnits=1,
                        source="kirchdorf", raw=upload,
                        data={"barometer": 29.923, "extraTemp9": 68.2,
                              "outTemp": 64.9}))
        live.close()

        found = what_it_sends(admin, load(work / "stations.toml")
                              .by_name("kirchdorf"))
        names = sorted(found.get("values") or {})
        check("the raw names are what is offered",
              names, ["baromrelin", "tempf", "tf_ch1"])
        check("and not the mapped ones",
              "extraTemp9" in names or "barometer" in names, False)
        check("nor what names the device",
              [n for n in ("PASSKEY", "stationtype", "dateutc")
               if n in names], [])


def nothing_is_left_open() -> None:
    """Every store this page opens is closed again.

    The failure this guards against does not look like a leak. It looks like
    three unrelated errors at once -- a settings file that cannot be read, a
    skin directory that is not there, an upload that fails -- because the
    process has run out of file descriptors and the next open of anything is
    the one that reports it.
    """
    import gc
    import sqlite3

    print("\nnothing is left holding a database open")
    gc.collect()
    open_ones = 0
    for one in [o for o in gc.get_objects() if isinstance(o, sqlite3.Connection)]:
        try:
            one.execute("SELECT 1")
            open_ones += 1
        except sqlite3.ProgrammingError:
            pass
    check("connections still open", open_ones, 0)


def main() -> int:
    a_field_with_nowhere_to_go()
    a_column_that_already_holds_something()
    a_column_being_written_right_now()
    another_station_of_the_same_archive()
    another_station_of_a_different_archive()
    placing_and_making_the_column()
    a_placement_reaches_the_driver()
    a_protocol_has_nothing_to_configure()
    nowhere_is_a_decision()
    the_chooser_offers_past_the_schema()
    the_rows_are_raw_names_not_mapped_ones()
    nothing_is_left_open()

    print()
    if failures:
        print(f"{failures} check(s) failed")
        return 1
    print("a reading can be placed, and the page says what is already there")
    return 0


if __name__ == "__main__":
    sys.exit(main())
