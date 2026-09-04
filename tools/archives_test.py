#!/usr/bin/env python3
"""Two places, one listener, and two series that never touch each other.

The case: one weewx-evo on a VPS collecting from two fields. Each is its own
measurement series -- its own file, its own altitude, its own sunrise -- and
mixing them into one file would not be a mess, it would be wrong readings
that look right.

WeeWX answers this by running two of everything: two configuration files, two
databases, two report directories, two units. That solves `station.altitude`
by duplicating it. Here the isolation boundary is the archive rather than the
process, so the altitude has to stop being global instead.

What is checked, in the order it can go wrong:

    the register     one archive and several use the same file
    the pending      two readers of one live table, neither clearing the
                     other's work -- the failure that loses a whole series
    the packets      the north field's readings do not reach the south file
    the place        the altitude used is the one belonging to the file
                     being written, which is the entire point
    end to end       a real serve process, two consoles, two files

The last one is why this is slow. Everything above it can pass against
wiring that was never connected.

    python tools/archives_test.py
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from weewx_evo import archives, stations  # noqa: E402
from weewx_evo.archiver import Archiver  # noqa: E402
from weewx_evo.db.archive import ArchiveStore  # noqa: E402
from weewx_evo.db.live import LiveStore, Packet, sender_id  # noqa: E402

failures = 0

INTERVAL = 60
TOKEN = "abcdefghij123456"

#: Two places far enough apart that a formula using the wrong one is obvious.
#: Kirchdorf is where the reference data comes from; the second is 600 m
#: higher, which moves the pressure reduction by tens of millibars.
NORTH = {"latitude": 48.4012, "longitude": 11.6301, "altitude": 452.0}
SOUTH = {"latitude": 47.4200, "longitude": 10.9850, "altitude": 1040.0}


def check(what: str, got: object, want: object) -> bool:
    global failures
    ok = got == want
    tail = "" if ok else f"  (wanted {want!r})"
    print(f"  {'ok  ' if ok else 'FAIL'} {what}: {got!r}{tail}")
    failures += 0 if ok else 1
    return ok


class Fake:
    """Enough of Settings for the register to read. Nothing more."""

    def __init__(self, **values: object) -> None:
        self.values = values
        #: `derive.from_settings` reads its policy out of here.
        self.config: dict = {}

    def get(self, name: str, default: object = None) -> object:
        return self.values.get(name, default)


# -- the register ------------------------------------------------------


def the_settings_become_the_file() -> None:
    """An installation from before places had a file of their own.

    The values have to survive the move and they have to survive it *once*:
    written down, not worked out again from settings that no longer describe
    a place. `station.*` is gone from the schema, so a second start reading
    an empty `cfg` has to find the altitude in the file or lose it.
    """
    print("\nwith no archives.toml, the settings are migrated into one")
    cfg = Fake(**{"archive_db": "data/weewx.sdb",
                  "station.name": "Kirchdorf",
                  "station.latitude": 48.4012,
                  "station.longitude": 11.6301,
                  "station.altitude": 440.0})
    with tempfile.TemporaryDirectory() as raw:
        where = Path(raw) / "archives.toml"
        register = archives.Register.load(where, cfg)
        check("there is exactly one", register.names(), ["default"])
        check("it is the file the settings name",
              register.get("default").file, "data/weewx.sdb")
        check("with the settings' altitude",
              register.get("default").altitude, 440.0)
        check("and nothing has to be told apart", register.several(), False)

        # The point of the whole move: it was written down, so the next
        # process does not have to be handed the settings to find the place.
        check("the file is on disk now", where.exists(), True)
        again = archives.Register.load(where, Fake())
        check("and it reads back without the settings",
              again.get("default").altitude, 440.0)
        check("with the label the settings held",
              again.get("default").label, "Kirchdorf")
        check("and its coordinates", again.get("default").longitude, 11.6301)
        check("and its broad legacy selection", again.get("default").stations,
              None)

        # The old values remain in evo.toml for compatibility, but they are
        # never a live fallback once the archive file exists.
        changed = archives.Register.load(where, Fake(**{
            "archive_db": "data/wrong.sdb", "station.name": "Wrong place",
            "station.altitude": 9999.0}))
        check("later central settings do not replace the file",
              (changed.get("default").file,
               changed.get("default").altitude),
              ("data/weewx.sdb", 440.0))
        check("and the atomic temporary file is gone",
              where.with_suffix(".toml.tmp").exists(), False)


def the_second_one_brings_the_first_with_it() -> None:
    """The trap this avoids: a file naming only the new one.

    The default would become a fallback nobody can edit, while the series
    with a year of readings in it sits behind settings the page has stopped
    showing.
    """
    print("\nadding a second archive writes both")
    cfg = Fake(**{"archive_db": "data/weewx.sdb", "station.name": "Kirchdorf",
                  "station.latitude": 48.4012, "station.altitude": 440.0})
    with tempfile.TemporaryDirectory() as raw:
        where = Path(raw) / "archives.toml"
        register = archives.Register.load(where, cfg)
        register.add(archives.Archive(name="nordfeld",
                                      file="data/nordfeld.sdb",
                                      label="Nordfeld", **NORTH))
        register.save()

        again = archives.Register.load(where, Fake())
        check("both are in the file", again.names(), ["default", "nordfeld"])
        check("the first kept its file",
              again.get("default").file, "data/weewx.sdb")
        check("and its altitude", again.get("default").altitude, 440.0)
        check("the second has its own", again.get("nordfeld").altitude, 452.0)
        check("and there is something to tell apart", again.several(), True)


def an_unknown_name_is_refused() -> None:
    """A typo must never publish another place's readings."""
    print("\nan archive name that is absent")
    only = archives.Register([archives.Archive("north", "north.sdb")])
    check("one archive is an unambiguous omitted selection",
          only.get(None).name, "north")
    try:
        only.get("gone")
    except KeyError as exc:
        check("an unknown explicit name is refused", "gone" in str(exc), True)
    else:
        check("an unknown explicit name is refused", False, True)

    ambiguous = archives.Register([
        archives.Archive("north", "north.sdb"),
        archives.Archive("south", "south.sdb")])
    try:
        ambiguous.get(None)
    except LookupError:
        check("several without an explicit default require a name", True, True)
    else:
        check("several without an explicit default require a name", False, True)


def station_selections_survive_the_file() -> None:
    """Broad, empty and canonical IDs survive one Place-owned file."""
    print("\narchive sender selections round trip")
    shared = sender_id("weather/underground", "Shared / Süd")
    north = sender_id("ecowitt", "AA:BB:CC")
    with tempfile.TemporaryDirectory() as raw:
        where = Path(raw) / "archives.toml"
        register = archives.Register([
            archives.Archive("default", "default.sdb", stations=None),
            archives.Archive("empty", "empty.sdb", stations=()),
            archives.Archive("north", "north.sdb",
                             stations=(shared, north),
                             members={
                                 shared: archives.MemberPolicy(
                                     role="extra", channel=2, indoor=False),
                             }),
            archives.Archive("mirror", "mirror.sdb", stations=(shared,)),
        ], where)
        register.save()
        again = archives.Register.load(where, Fake(**{
            "archive_db": "wrong.sdb", "station.name": "Wrong"}))
        check("None stays explicit", again.get("default").stations, None)
        check("empty stays explicit", again.get("empty").stations, ())
        check("several names keep their order",
              again.get("north").senders, (shared, north))
        check("one sender can feed two places",
              [one.name for one in again.all()
               if shared in (one.senders or ())], ["north", "mirror"])
        check("a selected sender keeps its place-specific policy",
              again.get("north").policy_for(shared),
              archives.MemberPolicy(role="extra", channel=2, indoor=False))
        check("an unspecified member has the safe ordinary defaults",
              again.get("north").policy_for(north),
              archives.MemberPolicy())
        written = where.read_text(encoding="utf-8")
        check("the broad selection is written distinctly",
              'senders = "*"' in written, True)
        check("the empty selection is written",
              "[archives.empty]\nfile = \"empty.sdb\"\nsenders = []" in written,
              True)
        check("sender IDs are quoted as one TOML key",
              f'[archives.north.members."{shared}"]' in written, True)


def member_policy_values_are_checked_per_archive() -> None:
    print("\nmember policy validation")

    for what, values in (
        ("unknown role", {"role": "secondary", "channel": 0}),
        ("extra without channel", {"role": "extra", "channel": 0}),
        ("main with a channel", {"role": "main", "channel": 2}),
        ("quoted indoor flag", {"indoor": "false"}),
    ):
        try:
            archives.MemberPolicy.from_dict(values)
        except ValueError:
            check(what + " is refused", True, True)
        else:
            check(what + " is refused", False, True)

    one = sender_id("push", "one")
    two = sender_id("push", "two")
    dormant = {
        one: archives.MemberPolicy(role="extra", channel=1),
        two: archives.MemberPolicy(role="extra", channel=1),
    }
    made = archives.Archive("north", "north.sdb", stations=(one,),
                            members=dormant)
    check("unselected policies are not a second authority",
          sorted(made.members), [one])
    try:
        archives.Archive("north", "north.sdb", stations=(one, two),
                         members=dormant)
    except ValueError as exc:
        check("selected extras may not share a channel",
              "channel 1" in str(exc), True)
    else:
        check("selected extras may not share a channel", False, True)

    with tempfile.TemporaryDirectory() as raw:
        where = Path(raw) / "archives.toml"
        where.write_text(
            f"member_policy_version = {archives.MEMBER_POLICY_VERSION + 1}\n"
            '[archives.north]\nfile = "north.sdb"\nsenders = []\n',
            encoding="utf-8")
        try:
            archives.Register.load(where, Fake())
        except ValueError as exc:
            check("a newer policy format is not silently downgraded",
                  "newer" in str(exc), True)
        else:
            check("a newer policy format is not silently downgraded",
                  False, True)


def legacy_station_destinations_move_once() -> None:
    """Old Station.archive pointers become archive-owned lists atomically."""
    print("\nlegacy station destinations move into archives.toml")
    cfg = Fake(**{"archive_db": "data/south.sdb",
                  "station.name": "South", "station.altitude": 440.0})
    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        where = work / "archives.toml"
        # Old files commonly named only the added archive; Register supplied
        # the central default at runtime.
        where.write_text(
            '[archives.north]\nfile = "data/north.sdb"\n', encoding="utf-8")
        (work / "stations.toml").write_text(
            '[stations.south-console]\n'
            'driver = "wunderground"\nidentity = "south"\n\n'
            '[stations.north-console]\n'
            'driver = "wunderground"\nidentity = "north"\n'
            'archive = "north"\n', encoding="utf-8")

        check("the explicit migration changed the file",
              archives.migrate_station_ownership(
                  where, cfg, work / "stations.toml"), True)
        migrated = archives.Register.load(where, cfg)
        check("the implicit central archive is written into the file",
              migrated.names(), ["default", "north"])
        check("an old implicit destination becomes default's list",
              migrated.get("default").senders,
              (sender_id("wunderground", "south"),))
        check("an old named destination becomes north's list",
              migrated.get("north").senders,
              (sender_id("wunderground", "north"),))
        check("all migrated selections are explicit",
              where.read_text(encoding="utf-8").count("members."), 2)

        # The old pointer is no longer consulted after the canonical file was
        # written, even if somebody leaves or changes it.
        (work / "stations.toml").write_text(
            '[stations.south-console]\n'
            'driver = "wunderground"\nidentity = "south"\n'
            'archive = "north"\n', encoding="utf-8")
        again = archives.Register.load(where, Fake(archive_db="data/wrong.sdb"))
        check("later station pointers do not change routing",
              again.get("default").senders,
              (sender_id("wunderground", "south"),))


def legacy_member_policies_move_once() -> None:
    """Old global roles move once to the selected sender relationship."""
    print("\nlegacy station roles move into selected Place members once")
    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        where = work / "archives.toml"
        where.write_text(
            '[archives.south]\nfile = "south.sdb"\n'
            'stations = ["shared"]\n\n'
            '[archives.south.members.shared]\n'
            'role = "main"\nchannel = 0\nindoor = true\n\n'
            '[archives.north]\nfile = "north.sdb"\n'
            'stations = ["shared"]\n',
            encoding="utf-8")
        stations_path = work / "stations.toml"
        stations_path.write_text(
            '[stations.shared]\n'
            'driver = "wunderground"\nidentity = "shared"\n'
            'role = "extra"\nchannel = 3\nindoor = false\n\n'
            '[stations.later]\n'
            'driver = "ecowitt"\nidentity = "later"\n'
            'role = "extra"\nchannel = 4\nindoor = false\n',
            encoding="utf-8")

        archives.migrate_station_ownership(where, Fake(), stations_path)
        migrated = archives.Register.load(where, Fake())
        shared = sender_id("wunderground", "shared")
        later = sender_id("ecowitt", "later")
        check("an explicit new policy beats the legacy station value",
              migrated.get("south").policy_for(shared),
              archives.MemberPolicy())
        check("the legacy policy reaches another place",
              migrated.get("north").policy_for(shared),
              archives.MemberPolicy(role="extra", channel=3, indoor=False))
        check("an unselected station creates no dormant authority",
              later in migrated.get("south").members, False)
        text = where.read_text(encoding="utf-8")
        check("the completed migration is marked",
              f"member_policy_version = {archives.MEMBER_POLICY_VERSION}" in text,
              True)
        check("the canonical sender is one quoted TOML key",
              f'[archives.north.members."{shared}"]' in text, True)
        check("the obsolete station-owned policy was removed after commit",
              stations.legacy_member_settings(stations_path), {})

        # Even if an obsolete writer adds the keys again, the marker makes
        # them cease to be authority. A later edit there must not overwrite
        # the copied relationship values.
        stations_path.write_text(
            stations_path.read_text(encoding="utf-8").replace(
                'identity = "shared"',
                'identity = "shared"\nrole = "extra"\nchannel = 8\n'
                'indoor = true'), encoding="utf-8")
        check("the versioned migration is not repeated",
              archives.migrate_station_ownership(
                  where, Fake(), stations_path), False)
        again = archives.Register.load(where, Fake())
        check("later legacy edits cannot replace the migrated policy",
              again.get("north").policy_for(shared),
              archives.MemberPolicy(role="extra", channel=3, indoor=False))


# -- the pending table -------------------------------------------------


def two_archives_do_not_clear_each_others_work() -> None:
    """The one that loses a whole series, silently.

    `pending` was keyed on the interval alone. Whichever archiver got there
    first deleted the row, and the second never saw the interval at all --
    so one site archives and the other stops, with nothing in the log.
    """
    print("\ntwo readers of one live table")
    with tempfile.TemporaryDirectory() as raw:
        live = LiveStore(Path(raw) / "live.sdb", interval_seconds=INTERVAL)
        live.archives = ["default", "nordfeld"]
        when = 1787800000
        live.add(Packet(dateTime=when, usUnits=1, data={"outTemp": 20.0},
                        identity="south"))

        later = when + INTERVAL * 2
        check("the default has an interval waiting",
              len(live.due(now=later, archive="default")), 1)
        check("and so does the other",
              len(live.due(now=later, archive="nordfeld")), 1)

        stop = live.due(now=later, archive="default")[0][0]
        live.clear_pending(stop, "default")
        check("one finishing leaves the other's work alone",
              len(live.due(now=later, archive="nordfeld")), 1)
        check("and does clear its own",
              len(live.due(now=later, archive="default")), 0)
        live.close()


def an_old_database_gains_the_column() -> None:
    """Rows in `pending` are intervals no archive has taken yet."""
    print("\na live database made before archives existed")
    with tempfile.TemporaryDirectory() as raw:
        path = Path(raw) / "live.sdb"
        # The old table, exactly as it was.
        old = sqlite3.connect(path)
        old.executescript("""
            CREATE TABLE pending (
                stop    INTEGER NOT NULL PRIMARY KEY,
                seconds INTEGER NOT NULL
            );
            INSERT INTO pending (stop, seconds) VALUES (1787800060, 60);
        """)
        old.commit()
        old.close()

        live = LiveStore(path, interval_seconds=INTERVAL)
        columns = {row[1] for row in
                   live.conn.execute("PRAGMA table_info(pending)")}
        check("the column is there now", "archive" in columns, True)
        check("and the waiting interval survived the rebuild",
              live.due(now=1787900000, archive="default"), [(1787800060, 60)])
        live.close()


# -- the packets -------------------------------------------------------


def each_series_takes_only_its_own() -> None:
    print("\ntwo consoles, two archives, one live table")
    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        live = LiveStore(work / "live.sdb", interval_seconds=INTERVAL)
        live.archives = ["default", "nordfeld"]
        when = 1787800000
        live.add(Packet(dateTime=when, usUnits=1, data={"outTemp": 20.0},
                        identity="south-console"))
        live.add(Packet(dateTime=when, usUnits=1, data={"outTemp": 2.0},
                        identity="north-console"))

        south_store = ArchiveStore(work / "south.sdb")
        north_store = ArchiveStore(work / "north.sdb")
        south = Archiver(live, south_store, interval_seconds=INTERVAL,
                         # The pair the table is keyed on. A name is a
                         # lookup and this is the thing looked up.
                         name="default",
                         stations=[("unknown", "south-console")])
        north = Archiver(live, north_store, interval_seconds=INTERVAL,
                         name="nordfeld",
                         stations=[("unknown", "north-console")])

        sql: list[str] = []
        south_store.conn.set_trace_callback(sql.append)
        later = when + INTERVAL * 2
        check("the south archived its interval",
              south.process_due(now=later, grace=0), 1)
        check("and the north its own",
              north.process_due(now=later, grace=0), 1)

        depth = 0
        daily_outside_transaction = []
        for statement in sql:
            command = statement.lstrip().upper()
            if command.startswith("BEGIN"):
                depth += 1
            elif command.startswith(("COMMIT", "ROLLBACK")):
                depth = max(0, depth - 1)
            elif ("INSERT OR REPLACE INTO ARCHIVE_DAY_" in command
                  and depth == 0):
                daily_outside_transaction.append(statement)
        check("all daily rows were written inside transactions",
              len(daily_outside_transaction), 0)

        def temp_in(store: ArchiveStore) -> float | None:
            row = store.conn.execute(
                "SELECT outTemp FROM archive ORDER BY dateTime").fetchone()
            return None if row is None else row[0]

        check("the south has only the south reading", temp_in(south_store), 20.0)
        check("and the north only the north one", temp_in(north_store), 2.0)

        # The half that matters more: neither averaged the two. 11.0 is what
        # a single archive taking everything would have written.
        check("nobody wrote the average of two places",
              temp_in(south_store) != 11.0, True)
        south_store.close()
        north_store.close()
        live.close()


def an_archive_with_no_stations_writes_nothing() -> None:
    """Rather than quietly taking everybody else's readings."""
    print("\nan archive nobody writes into")
    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        live = LiveStore(work / "live.sdb", interval_seconds=INTERVAL)
        live.add(Packet(dateTime=1787800000, usUnits=1, data={"outTemp": 20.0},
                        identity="somebody"))
        store = ArchiveStore(work / "empty.sdb")
        empty = Archiver(live, store, interval_seconds=INTERVAL,
                         name="empty", stations=[])
        check("it archives nothing",
              empty.process_due(now=1787800200, grace=0), 0)
        check("and the file has no records",
              store.conn.execute("SELECT count(*) FROM archive").fetchone()[0], 0)
        store.close()
        live.close()


def a_broad_archive_selection_takes_everything() -> None:
    """None is the migrated archive's explicit broad selection.

    An unannounced sensor has been reaching the series for a year. It must go
    on reaching it, but because the archive says so -- not because there is
    only one archive or because a station points at a default.
    """
    print("\nwith a broad archive selection, an unannounced source gets in")
    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        live = LiveStore(work / "live.sdb", interval_seconds=INTERVAL)
        live.add(Packet(dateTime=1787800000, usUnits=1, data={"outTemp": 20.0},
                        identity="a-console-nobody-announced"))
        store = ArchiveStore(work / "weewx.sdb")
        only = Archiver(live, store, interval_seconds=INTERVAL,
                        name="default", stations=None)
        check("it is archived", only.process_due(now=1787800200, grace=0), 1)
        store.close()
        live.close()


# -- the place ---------------------------------------------------------


def the_altitude_is_the_archives() -> None:
    """The reason `station.*` had to move, measured rather than asserted.

    Pressure reduced to sea level depends on how far up it was measured. Six
    hundred metres of difference is about 70 mbar, so a reading reduced with
    the wrong site's altitude is not subtly wrong.
    """
    print("\nthe pressure reduction uses the altitude of the file being written")
    from weewx_evo.derive import from_settings as deriver_from

    cfg = Fake(**{"station.latitude": 48.4012, "station.longitude": 11.6301,
                  "station.altitude": 440.0})
    north = archives.Archive("nordfeld", "n.sdb", **NORTH)
    south = archives.Archive("suedfeld", "s.sdb", **SOUTH)

    low = deriver_from(cfg, north)
    high = deriver_from(cfg, south)
    check("each deriver got its own altitude",
          (low.station.altitude_m, high.station.altitude_m), (452.0, 1040.0))

    # A declared place with missing coordinates is not the legacy default
    # place. Borrowing the central values here silently computes plausible
    # derived readings for the wrong location.
    blank = deriver_from(cfg, archives.Archive("blank", "blank.sdb"))
    check("a blank place does not borrow legacy coordinates",
          (blank.station.latitude, blank.station.longitude,
           blank.station.altitude_m),
          (None, None, None))

    record = {"dateTime": 1787800000, "usUnits": 1, "pressure": 28.5,
              "outTemp": 50.0, "outHumidity": 60.0}
    low_out = low.apply(dict(record))
    high_out = high.apply(dict(record))
    moved = abs((high_out.get("barometer") or 0) - (low_out.get("barometer") or 0))
    check("and the reduced pressures differ by the height between them",
          moved > 1.0, True)
    print(f"  --   barometer {low_out.get('barometer'):.3f} at 452 m, "
          f"{high_out.get('barometer'):.3f} at 1040 m inHg")


def a_page_prints_its_own_place() -> None:
    """`Placed` is what saves fifty reads from being rewritten one by one."""
    print("\nthe settings, as one archive sees them")
    cfg = Fake(**{"station.name": "Kirchdorf", "station.latitude": 48.4012,
                  "station.altitude": 440.0, "language": "de",
                  "interval": 300})
    north = archives.Archive("nordfeld", "n.sdb", label="Nordfeld", **NORTH)
    view = archives.Placed(cfg, north)

    check("the name is the archive's", view.get("station.name"), "Nordfeld")
    check("and the altitude too", view.get("station.altitude"), 452.0)
    check("everything else passes through", view.get("language"), "de")
    check("including what was never asked about", view.get("interval"), 300)

    # An archive that says nothing must not borrow another place's position.
    bare = archives.Placed(cfg, archives.Archive("bare", "b.sdb"))
    check("an archive with no coordinates stays without them",
          bare.get("station.latitude"), None)
    check("and a blank label uses its own stable name",
          bare.get("station.name"), "bare")


# -- end to end --------------------------------------------------------


def a_free_port() -> int:
    """One nobody is using, asked of the kernel.

    Not a number picked here. A test that binds 18331 passes until something
    else on the machine has it, and then fails once in a while for a reason
    that has nothing to do with what it checks -- which is worse than failing
    every time.
    """
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def upload(base: str, source: str, temp: float) -> str:
    # No PASSKEY in here. An empty one still reads as Ecowitt to `claims()`,
    # and then the upload is answered by the wrong driver -- which happened
    # the first time this was written and made the stations strangers.
    body = (f"ID={source}&PASSWORD={TOKEN}&action=updateraw&dateutc=now"
            f"&tempf={temp}&humidity=60&baromin=30.032")
    request = urllib.request.Request(
        f"{base}/{TOKEN}/data/report/?{body}",
        headers={"User-Agent": "archives-test"})
    with urllib.request.urlopen(request, timeout=10) as answer:
        return answer.read().decode().strip()


def two_sites_through_a_real_serve() -> None:
    """One process, one port, two consoles, two files.

    Everything above this can pass with the wiring never connected: the
    register is right, the archiver is right, and `cmd_serve` still builds
    one of them out of the settings. This is the branch nothing else walks.
    """
    print("\na real serve, two consoles, two series")
    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        (work / "data").mkdir()
        south_sender = sender_id("wunderground", "suedhof")
        north_sender = sender_id("wunderground", "nordhof")

        (work / "archives.toml").write_text(
            f'member_policy_version = {archives.MEMBER_POLICY_VERSION}\n\n'
            '[archives.default]\n'
            'file = "data/sued.sdb"\n'
            'label = "Suedfeld"\n'
            f'latitude = {SOUTH["latitude"]}\n'
            f'longitude = {SOUTH["longitude"]}\n'
            f'altitude = {SOUTH["altitude"]}\n'
            f'\n[archives.default.members."{south_sender}"]\n'
            'role = "main"\nchannel = 0\nindoor = true\n'
            '\n'
            '[archives.nordfeld]\n'
            'file = "data/nord.sdb"\n'
            'label = "Nordfeld"\n'
            f'latitude = {NORTH["latitude"]}\n'
            f'longitude = {NORTH["longitude"]}\n'
            f'altitude = {NORTH["altitude"]}\n'
            f'\n[archives.nordfeld.members."{north_sender}"]\n'
            'role = "main"\nchannel = 0\nindoor = true\n', encoding="utf-8")

        (work / "stations.toml").write_text(
            '[stations.suedhof]\n'
            'driver = "wunderground"\n'
            'identity = "suedhof"\n'
            'archive = "default"\n'
            '\n'
            '[stations.nordhof]\n'
            'driver = "wunderground"\n'
            'identity = "nordhof"\n'
            'archive = "nordfeld"\n', encoding="utf-8")

        port = a_free_port()
        (work / "evo.toml").write_text(
            f'token = "{TOKEN}"\n'
            f"port = {port}\n"
            "interval = 60\n"
            "grace = 1\n"
            "poll = 1\n"
            "watchdog = false\n"
            'driver = "wunderground"\n'
            f'live_db = "{(work / "data" / "live.sdb").as_posix()}"\n'
            f'archive_db = "{(work / "data" / "sued.sdb").as_posix()}"\n',
            encoding="utf-8")

        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(
            [str(ROOT / "src"), env.get("PYTHONPATH", "")])
        # Do not leave a chatty child connected to an unread PIPE while this
        # process waits for its database writes. Once the OS pipe buffer fills,
        # logging blocks the archiver itself and the test manufactures the
        # failure it is waiting to observe.
        log_path = work / "serve.log"
        log_file = log_path.open("w", encoding="utf-8")
        proc = subprocess.Popen(
            [sys.executable, "-m", "weewx_evo.cli", "serve",
             "--config", str(work / "evo.toml")],
            env=env, stdout=log_file, stderr=subprocess.STDOUT,
            text=True)
        base = f"http://127.0.0.1:{port}"
        try:
            if not _wait_for(base):
                proc.terminate()
                proc.wait(timeout=10)
                log_file.flush()
                out = log_path.read_text(encoding="utf-8", errors="replace")
                check("the listener came up", False, True)
                print("  --   " + "\n  --   ".join(out.splitlines()[-15:]))
                return

            # Two intervals of readings from each console, a minute apart, so
            # there is something to close.
            for n in range(4):
                upload(base, "suedhof", 50.0 + n)
                upload(base, "nordhof", 30.0 + n)
                time.sleep(0.2)

            # An archive interval is a minute here; wait for the boundary
            # rather than sleeping a fixed time and hoping.
            south = work / "data" / "sued.sdb"
            north = work / "data" / "nord.sdb"
            got = _wait_for_records(south, north, seconds=95)
            check("both files were written", got, True)

            if got:
                check("the south has records", _records(south) > 0, True)
                check("and so has the north", _records(north) > 0, True)
                check("the south holds only its own console",
                      _sources_in(work / "data" / "live.sdb", "suedhof") > 0,
                      True)
                check("the two files hold different temperatures",
                      _first_temp(south) != _first_temp(north), True)
                # Without this the whole run passes on a coincidence: an
                # upload nobody announced keeps its own id as the source,
                # and that id happens to equal the station name. Both
                # consoles are announced here, so neither is a sighting.
                check("neither console was taken for a stranger",
                      _sightings(work / "data" / "live.sdb"), [])
                print(f"  --   south {_first_temp(south)}, "
                      f"north {_first_temp(north)}")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            log_file.flush()
            log_file.close()
            out = log_path.read_text(encoding="utf-8", errors="replace")
            if failures:
                print("  --   the log said:")
                for line in out.splitlines()[-25:]:
                    print(f"       {line}")


def _wait_for(base: str, seconds: float = 20) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"{base}/{TOKEN}/status", timeout=2).read()
            return True
        except urllib.error.HTTPError:
            return True  # answering, which is all this asks
        except Exception:
            time.sleep(0.3)
    return False


def _records(path: Path) -> int:
    if not path.exists():
        return 0
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return conn.execute("SELECT count(*) FROM archive").fetchone()[0]
    except sqlite3.Error:
        return 0
    finally:
        conn.close()


def _first_temp(path: Path) -> float | None:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        row = conn.execute("SELECT outTemp FROM archive"
                           " ORDER BY dateTime").fetchone()
        return None if row is None else row[0]
    finally:
        conn.close()


def _sightings(live_path: Path) -> list:
    """What turned up unannounced, by identity. Empty is the good answer."""
    conn = sqlite3.connect(f"file:{live_path}?mode=ro", uri=True)
    try:
        row = conn.execute(
            "SELECT value FROM live_metadata WHERE name = 'sightings'"
        ).fetchone()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    if not row or not row[0]:
        return []
    try:
        found = json.loads(row[0])
    except ValueError:
        return ["unreadable"]
    return sorted(one.get("identity", "?") for one in found)


def _sources_in(live_path: Path, source: str) -> int:
    conn = sqlite3.connect(f"file:{live_path}?mode=ro", uri=True)
    try:
        # By the identity the console uploads with, which is what the
        # table records. The name it answers to is a lookup, so there
        # is no column to select on.
        return conn.execute(
            "SELECT count(*) FROM packet WHERE identity = ?",
            (source,)).fetchone()[0]
    finally:
        conn.close()


def _wait_for_records(*paths: Path, seconds: float) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if all(_records(one) > 0 for one in paths):
            return True
        time.sleep(1.0)
    return False


def the_page_is_how_the_second_one_appears() -> None:
    """Adding one through the settings page, which is the only way in.

    Checked through the page rather than through the register, because the
    page is what somebody uses -- and the register on its own was right for
    a while in a version where nothing reached it.
    """
    print("\nadding an archive through the settings page")
    from weewx_evo import adminarchives
    from weewx_evo.admin import Admin
    from weewx_evo.cli import all_schemas

    unsafe_swatch = adminarchives._swatch(
        "#fff; background-image: url(javascript:alert(1))", "hand edited")
    check("a hand-edited colour cannot add a CSS declaration",
          ('style="--c: "' in unsafe_swatch
           and "background-image" not in unsafe_swatch), True)

    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        (work / "data").mkdir()
        (work / "evo.toml").write_text(
            'token = "abcdefghij123456"\n'
            '[station]\n'
            'name = "Kirchdorf"\n'
            "latitude = 48.4012\n"
            "longitude = 11.6301\n"
            "altitude = 440.0\n", encoding="utf-8")
        admin = Admin(work / "evo.toml",
                      lambda: all_schemas(work / "evo.toml"),
                      TOKEN)
        shared = sender_id("wunderground", "SHARED / Süd")
        other = sender_id("ecowitt", "AA:BB")
        with LiveStore(work / "data" / "live.sdb") as live:
            live.add(Packet(1700000000, 1, {"outTemp": 12.0},
                            driver="wunderground",
                            identity="SHARED / Süd",
                            mapping={"version": 1,
                                     "fields": {"outTemp": "outTemp"},
                                     "metadata": [], "contested": [],
                                     "absent": []}))
            live.add(Packet(1700000001, 1, {"outTemp": 13.0},
                            driver="ecowitt", identity="AA:BB"))
            live.sync_sender_labels([
                stations.Station("Terrace", "wunderground", "SHARED / Süd")])

        register = adminarchives.load(admin)
        check("the migrated file has one archive",
              register.names(), ["default"])
        check("with the name from the settings",
              register.get("default").title, "Kirchdorf")
        check("and migration wrote the canonical file",
              adminarchives.path_for(admin).exists(), True)

        one_page = adminarchives.overview(admin)
        check("one place uses the master-detail shell",
              ('class="place-shell"' in one_page
               and one_page.count('class="place-choice') == 1
               and one_page.count('class="place-detail"') == 1), True)
        check("the one-place page keeps the Places name",
              "Where you measure" not in one_page
              and "<h2>Places</h2>" in one_page, True)
        check("the canonical edit route is Places",
              'action="./places/default/set"' in one_page, True)

        made, error = adminarchives.create(admin, {
            "name": "nordfeld", "label": "Nordfeld",
            "latitude": "48.4012", "longitude": "11.6301",
            "altitude": "452"})
        check("it was accepted", error, "")
        check("and given a file nobody had to invent",
              made.file, "data/nordfeld.sdb")
        check("and a new place starts with no console selected",
              made.stations, ())
        check("the file now exists",
              adminarchives.path_for(admin).exists(), True)

        again = adminarchives.load(admin)
        check("both are in it", again.names(), ["default", "nordfeld"])
        check("and the first kept the settings' altitude",
              again.get("default").altitude, 440.0)
        check("and the file is what both are read from",
              again.path, adminarchives.path_for(admin))

        two_page = adminarchives.overview(
            admin, form={"_open": "nordfeld"})
        check("two places use the same master-detail shell",
              (two_page.count('class="place-choice') == 2
               and two_page.count('class="place-detail"') == 1), True)
        check("the requested place is the detail",
              ('id="place-detail-nordfeld"' in two_page
               and 'href="./new-place"' in two_page), True)

        # Editing unrelated properties must keep all three selection states;
        # the form can also change the list deliberately.
        error = adminarchives.configure(admin, "default", {
            "label": "Kirchdorf updated"})
        check("editing the migrated place succeeds", error, "")
        check("and keeps its None selection",
              adminarchives.load(admin).get("default").stations, None)

        error = adminarchives.configure(admin, "nordfeld", {
            "label": "North field"})
        check("editing a new empty place succeeds", error, "")
        kept = adminarchives.load(admin).get("nordfeld")
        check("and keeps the empty selection", kept.stations, ())
        check("and keeps a field absent from the compact post",
              kept.file, "data/nordfeld.sdb")

        error = adminarchives.configure(admin, "nordfeld", {
            "_members": "1", f"sender:{shared}": "1",
            f"member-role:{shared}": "main",
            f"member-indoor:{shared}": "1"})
        check("selecting a live sender succeeds", error, "")
        check("and stores its canonical ID",
              adminarchives.load(admin).get("nordfeld").senders,
              (shared,))

        # Role, channel and indoor are answers this place gives about one
        # console. The same console may therefore answer differently in the
        # migrated broad place and in the new, explicitly selected one.
        error = adminarchives.configure(admin, "default", {
            "_members": "1",
            "all-senders": "1",
            f"sender:{shared}": "1",
            f"sender:{other}": "1",
            f"member-role:{shared}": "extra",
            f"member-channel:{shared}": "3",
            f"member-role:{other}": "main",
            f"member-indoor:{other}": "1",
            # An absent checkbox is the deliberate false value.
        })
        check("the first place accepts its member policy", error, "")
        error = adminarchives.configure(admin, "nordfeld", {
            "_members": "1",
            f"sender:{shared}": "1",
            f"member-role:{shared}": "main",
            f"member-indoor:{shared}": "1",
        })
        check("the second place accepts another policy", error, "")

        fields_page = adminarchives.overview(
            admin, form={"_open": "nordfeld"})
        check("field mapping is edited inside the Place detail",
              'action="./places/nordfeld/fields"' in fields_page, True)
        check("the mapping form carries the canonical sender",
              f'name="sender" value="{shared}"' in fields_page, True)
        check("the sender detail remains diagnostic",
              "./stations/" in fields_page, False)

        policies = adminarchives.load(admin)
        check("one console can be extra outside in one place",
              policies.get("default").policy_for(shared),
              archives.MemberPolicy(role="extra", channel=3, indoor=False))
        check("and main with indoor readings in another",
              policies.get("nordfeld").policy_for(shared),
              archives.MemberPolicy())

        # A compact property update has no member marker. It must not rebuild
        # the relationship with defaults just because no policy controls were
        # submitted.
        error = adminarchives.configure(admin, "default", {
            "label": "Kirchdorf renamed", "latitude": "48.5"})
        check("an ordinary place edit succeeds", error, "")
        preserved = adminarchives.load(admin).get("default")
        check("and preserves its member policy",
              preserved.policy_for(shared),
              archives.MemberPolicy(role="extra", channel=3, indoor=False))

        member_form = adminarchives._member_fields(admin, preserved)
        check("the place form owns the role control",
              f'name="member-role:{shared}"' in member_form, True)
        check("and displays the live label, not as its value",
              "<strong>Terrace</strong>" in member_form
              and f'name="sender:{shared}"' in member_form, True)
        check("and shows the stored extra role",
              'value="extra" selected' in member_form, True)
        check("and shows its channel",
              f'name="member-channel:{shared}"' in member_form
              and 'value="3"' in member_form, True)
        check("and names the relationship in user terms",
              ("Primary readings" in member_form
               and "Additional sensor" in member_form
               and "Indoor readings" in member_form), True)
        indoor_name = f'name="member-indoor:{shared}"'
        indoor_control = (member_form.split(indoor_name, 1)[1].split(">", 1)[0]
                          if indoor_name in member_form else "")
        check("and leaves indoor unticked",
              bool(indoor_control) and "checked" not in indoor_control, True)

        north_form = adminarchives._member_fields(
            admin, adminarchives.load(admin).get("nordfeld"))
        other_row = north_form.split(f'name="sender:{other}"', 1)[1]
        other_row = other_row.split("</article>", 1)[0]
        check("an unselected sender has no active policy controls",
              ('data-place-member-policy' in other_row
               and "disabled hidden" in other_row), True)

        error = adminarchives.configure(admin, "nordfeld", {
            "_members": "1", f"sender:{other}": "1"})
        check("a no-script selection receives the relationship default",
              error, "")
        check("including indoor readings by default",
              adminarchives.load(admin).get("nordfeld").policy_for(other),
              archives.MemberPolicy())

        selected, defaults = adminarchives._members_from_form({
            "_members": "1", f"sender:{shared}": "1",
            f"sender:{other}": "1",
        }, (), {}, new=True)
        check("a no-script multi-selection has one primary",
              (selected, defaults[shared]),
              ((shared, other), archives.MemberPolicy()))
        check("and makes the next sender additional",
              defaults[other],
              archives.MemberPolicy(role="extra", channel=1))

        # A name that is taken, and a file that is taken. Both would mix two
        # places into one series without saying so.
        _, error = adminarchives.create(admin, {"name": "nordfeld"})
        check("a second one under the same name is refused",
              "already an archive" in error, True)
        _, error = adminarchives.create(admin, {"name": "other",
                                                "file": "data/nordfeld.sdb"})
        check("and so is a second one in the same file",
              "one series with the readings mixed" in error, True)

        # A station's obsolete archive pointer is not the owner of selection.
        (work / "stations.toml").write_text(
            '[stations.nordhof]\n'
            'driver = "wunderground"\n'
            'identity = "nordhof"\n'
            'archive = "nordfeld"\n', encoding="utf-8")
        error = adminarchives.remove(admin, "nordfeld")
        check("a station.archive pointer does not block removal", error, "")
        check("and the default cannot be removed at all",
              "cannot be removed" in adminarchives.remove(admin, "default"),
              True)


def a_command_can_name_its_series() -> None:
    """`catchup --series nordfeld`, and a clear no for a name that is not.

    Not `--archive`: that already means the path to a database file,
    and one flag with two meanings breaks the day somebody names an
    archive after a directory.
    """
    print("\nthe single-shot commands take an archive")
    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        (work / "data").mkdir()
        (work / "archives.toml").write_text(
            '[archives.default]\nfile = "data/sued.sdb"\n\n'
            '[archives.nordfeld]\nfile = "data/nord.sdb"\n', encoding="utf-8")
        (work / "evo.toml").write_text(
            'token = "abcdefghij123456"\n'
            f'live_db = "{(work / "data" / "live.sdb").as_posix()}"\n'
            f'archive_db = "{(work / "data" / "sued.sdb").as_posix()}"\n',
            encoding="utf-8")

        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(
            [str(ROOT / "src"), env.get("PYTHONPATH", "")])

        def run(*extra: str) -> subprocess.CompletedProcess:
            return subprocess.run(
                [sys.executable, "-m", "weewx_evo.cli", "catchup",
                 "--config", str(work / "evo.toml"), *extra],
                env=env, capture_output=True, text=True, timeout=60,
                check=False)

        named = run("--series", "nordfeld")
        check("naming one that exists works", named.returncode, 0)
        check("and it wrote that file",
              (work / "data" / "nord.sdb").exists(), True)

        missing = run("--series", "westfeld")
        check("naming one that does not is refused", missing.returncode, 2)
        check("and the answer lists the ones there are",
              "nordfeld" in missing.stderr, True)

        # The archiver takes it too, which is how two timezones work: one
        # process per place, each with its own TZ, both reading the one live
        # table. Checked through the refusal because the other branch is a
        # daemon that does not return.
        wrong = subprocess.run(
            [sys.executable, "-m", "weewx_evo.cli", "archive",
             "--config", str(work / "evo.toml"), "--series", "westfeld"],
            env=env, capture_output=True, text=True, timeout=60, check=False)
        check("the archiver refuses an unknown series too", wrong.returncode, 2)
        check("naming what there is", "nordfeld" in wrong.stderr, True)


def a_place_in_another_timezone_is_said_out_loud() -> None:
    """The one thing here that goes wrong without anything failing.

    Readings stay right. Only the day boundary moves, so every daily maximum
    is for a day that ran from ten in the morning to ten in the morning --
    and nothing in the output looks odd. It has to be said, or it is found a
    year later.
    """
    print("\na place whose day does not start when this machine's does")
    here = archives.Archive("here", "h.sdb", latitude=48.4, longitude=11.6)
    far = archives.Archive("far", "f.sdb", latitude=-36.85, longitude=174.76)
    blank = archives.Archive("blank", "b.sdb")

    gap = archives.timezone_gap(here)
    print(f"  --   11.6 deg east is {gap:+.1f} h from this process's clock")
    check("a place under this clock says nothing",
          archives.timezone_concern(here), "")
    said = archives.timezone_concern(far)
    check("one on the other side of the world does", bool(said), True)
    check("and it says what to do about it",
          "TZ" in said and "archiver separately" in said, True)
    check("an archive with no longitude is not guessed at",
          archives.timezone_concern(blank), "")

    register = archives.Register([here, far])
    check("the register collects them by name",
          sorted(register.concerns()), ["far"])


# ---------------------------------------------------------------------------
# Two places on one chart.
# ---------------------------------------------------------------------------

def an_archive_with(path: Path, temperatures: list[float],
                    start: int = 1756308600, every: int = 300,
                    system: int = 17) -> Path:
    """A small archive with one reading in it, so two can be compared.

    `system` is what the file says it holds -- 17 is metricwx, 1 is US. It is
    a parameter because two places in two systems is the ordinary case here,
    not an odd one: one console replaced and one not.
    """
    import sqlite3
    from contextlib import closing

    with closing(sqlite3.connect(path)) as conn:
        conn.execute(
            "CREATE TABLE archive (dateTime INTEGER PRIMARY KEY, "
            "usUnits INTEGER, `interval` INTEGER, outTemp REAL)")
        conn.executemany(
            "INSERT INTO archive VALUES (?, ?, ?, ?)",
            [(start + n * every, system, every // 60, value)
             for n, value in enumerate(temperatures)])
        conn.commit()
    return path


def test_one_chart_draws_two_places() -> None:
    """The question that makes somebody install Grafana, asked of our own
    charts.

    `archives.py` gives n independent series, and until this nothing could
    put two of them on one axis -- so "outTemp at both locations" was a
    question the station's own pages could not answer, whatever they held.
    """
    import sqlite3
    from contextlib import closing

    from weewx_evo import chartdata, units
    from weewx_evo import plots as plot_defs
    from weewx_evo import series as series_module
    from weewx_evo.series import Reader

    where = Path(tempfile.mkdtemp())
    an_archive_with(where / "default.sdb", [10.0, 11.0, 12.0, 13.0])
    an_archive_with(where / "nordfeld.sdb", [4.0, 5.0, 6.0, 7.0])

    charts = plot_defs.from_dict({"plot": [{
        "name": "both", "span": "day", "time_length": 86400,
        "line": [{"obs": "outTemp"},
                 {"obs": "outTemp", "series": "nordfeld",
                  "label": "North field"}],
    }]})
    plot = charts.plots[0]
    check("the second line names a series", plot.lines[1].series, "nordfeld")

    paths = {"nordfeld": where / "nordfeld.sdb"}
    wanted = plot_defs.series_named(charts)
    with (closing(sqlite3.connect(where / "default.sdb")) as conn,
          series_module.opened(paths, wanted) as readers):
        check("only what a plot named was opened", sorted(readers),
              ["nordfeld"])
        # Both files hold metricwx, and the caller says so. Said wrongly,
        # the home line would come back unconverted while the named one was
        # converted from what its own reader holds -- two lines on one axis,
        # in two units, under one label. That asymmetry is what the caller
        # telling the truth prevents, and it is why both feeds now pass
        # `reader.system` rather than a setting.
        chart = chartdata.build(plot, Reader(conn), 1756308600 + 1200,
                                unit_system=units.METRICWX,
                                readers=readers)

    check("both lines are drawn", len(chart.lines), 2)
    check("the first is this archive's",
          [v for v in chart.lines[0].values if v is not None][:2], [10.0, 11.0])
    check("the second is the other's",
          [v for v in chart.lines[1].values if v is not None][:2], [4.0, 5.0])
    check("and it says where it came from", chart.lines[1].series, "nordfeld")
    check("while the first says nothing, as every single-series line does",
          chart.lines[0].series, "")


def test_two_places_in_two_unit_systems() -> None:
    """A console replaced and one not, on one axis.

    Each line is converted from the system *its own archive* holds. Read from
    the chart's instead, a place whose console sends Fahrenheit comes out
    thirty degrees wrong on the one page built to compare it with its
    neighbour -- and every number on that page is internally consistent, so
    nothing about it looks odd.
    """
    import sqlite3
    from contextlib import closing

    from weewx_evo import chartdata, units
    from weewx_evo import plots as plot_defs
    from weewx_evo import series as series_module
    from weewx_evo.series import Reader

    where = Path(tempfile.mkdtemp())
    # 10 C here, and the same weather over there reported as 50 F.
    an_archive_with(where / "default.sdb", [10.0, 11.0], system=17)
    an_archive_with(where / "nordfeld.sdb", [50.0, 51.8], system=1)

    charts = plot_defs.from_dict({"plot": [{
        "name": "both", "span": "day", "time_length": 86400,
        "line": [{"obs": "outTemp"},
                 {"obs": "outTemp", "series": "nordfeld"}],
    }]})
    paths = {"nordfeld": where / "nordfeld.sdb"}
    with (closing(sqlite3.connect(where / "default.sdb")) as conn,
          series_module.opened(paths, {"nordfeld"}) as readers):
        chart = chartdata.build(charts.plots[0], Reader(conn),
                                1756308600 + 600,
                                unit_system=units.METRICWX,
                                readers=readers)

    check("both lines are drawn", len(chart.lines), 2)
    check("and both come out in the same unit", chart.unit, "degree_C")
    check("the Fahrenheit archive was converted, not copied",
          [round(v, 1) for v in chart.lines[1].values if v is not None][:2],
          [10.0, 11.0])
    check("so the two places read the same weather the same way",
          [round(v, 1) for v in chart.lines[0].values if v is not None][:2],
          [round(v, 1) for v in chart.lines[1].values if v is not None][:2])


def test_a_line_naming_an_archive_that_is_not_there_is_left_out() -> None:
    """Not read from the default.

    Silently drawing one location's temperature under another location's
    label is the one outcome worse than a chart with a line missing, and
    nothing on the page could ever show it.
    """
    import sqlite3
    from contextlib import closing

    from weewx_evo import chartdata
    from weewx_evo import plots as plot_defs
    from weewx_evo.series import Reader

    where = Path(tempfile.mkdtemp())
    an_archive_with(where / "default.sdb", [10.0, 11.0, 12.0])

    charts = plot_defs.from_dict({"plot": [{
        "name": "both", "span": "day", "time_length": 86400,
        "line": [{"obs": "outTemp"},
                 {"obs": "outTemp", "series": "gone"}],
    }]})

    with closing(sqlite3.connect(where / "default.sdb")) as conn:
        chart = chartdata.build(charts.plots[0], Reader(conn),
                                1756308600 + 900, readers={})

    check("one line, not two with the same numbers", len(chart.lines), 1)
    check("and it is this archive's", chart.lines[0].series, "")


def test_a_series_survives_the_round_trip_through_the_file() -> None:
    """A chart drawing two places has to still do so after a save.

    `plots.toml` is written and read by the settings page, and a field that
    is read but never written is a setting that vanishes the first time
    somebody edits an unrelated chart.
    """
    from weewx_evo import plots as plot_defs

    where = Path(tempfile.mkdtemp()) / "plots.toml"
    charts = plot_defs.from_dict({"plot": [{
        "name": "both", "span": "day", "time_length": 86400,
        "line": [{"obs": "outTemp"},
                 {"obs": "outTemp", "series": "nordfeld"}],
    }]})
    plot_defs.save(where, charts)

    back = plot_defs.load(where)
    check("the series came back", back.plots[0].lines[1].series, "nordfeld")
    check("and the plain line is still plain",
          back.plots[0].lines[0].series, "")


def test_nothing_is_opened_where_no_plot_names_one() -> None:
    """Every station until somebody writes a series down, which is all of
    them today. It must cost nothing."""
    from weewx_evo import plots as plot_defs
    from weewx_evo import series as series_module

    charts = plot_defs.from_dict({"plot": [{
        "name": "plain", "span": "day", "time_length": 86400,
        "line": [{"obs": "outTemp"}],
    }]})
    check("nothing is named", plot_defs.series_named(charts), set())

    where = Path(tempfile.mkdtemp())
    an_archive_with(where / "other.sdb", [1.0])
    with series_module.opened({"other": where / "other.sdb"},
                              plot_defs.series_named(charts)) as readers:
        check("so nothing is opened", readers, {})


def test_a_line_can_be_pointed_at_another_series_from_the_page() -> None:
    """The picker appears only where there is more than one archive.

    On a single-series station it is a field on every line of every chart
    that a hundred people have to work out is not theirs, and that is the
    ordinary case.
    """
    print("\npointing a chart line at another series")
    from weewx_evo import adminplots
    from weewx_evo.admin import Admin
    from weewx_evo.cli import all_schemas

    with tempfile.TemporaryDirectory() as raw:
        work = Path(raw)
        (work / "evo.toml").write_text(
            'token = "abcdefghij123456"\n'
            'plots_file = "plots.toml"\n'
            '[station]\n'
            'name = "Kirchdorf"\n'
            "latitude = 48.4012\n"
            "longitude = 11.6301\n"
            "altitude = 440.0\n", encoding="utf-8")
        (work / "plots.toml").write_text(
            '[[plot]]\nname = "daytemp"\nspan = "day"\n'
            "time_length = 86400\n"
            '[[plot.line]]\nobs = "outTemp"\n', encoding="utf-8")
        admin = Admin(work / "evo.toml",
                      lambda: all_schemas(work / "evo.toml"), TOKEN)

        check("with one archive nothing is offered",
              adminplots.known_series(admin), set())
        check("so the field is not drawn",
              adminplots._series_field("line0_series", "", admin), "")

        # A second archive, written the way the page writes it.
        (work / "archives.toml").write_text(
            '[archives.default]\nfile = "data/weewx.sdb"\n'
            'label = "Kirchdorf"\n\n'
            '[archives.nordfeld]\nfile = "data/nord.sdb"\n'
            'label = "North field"\n', encoding="utf-8")
        admin.refresh()

        check("now both are offered", adminplots.known_series(admin),
              {"default", "nordfeld"})
        field = adminplots._series_field("line0_series", "nordfeld", admin)
        check("the field is drawn", "<select" in field, True)
        check("with the one chosen selected",
              'value="nordfeld" selected' in field, True)

        # And a name nobody configured is refused rather than warned about.
        errors = adminplots.save(admin, "daytemp", {
            "line0_obs": "outTemp", "line0_series": "atlantis",
            "time_length": "86400", "span": "day"}, {"outTemp"})
        check("a series that does not exist is refused",
              "line0_series" in errors, True)
        check("and the answer says what there is",
              "nordfeld" in errors.get("line0_series", ""), True)

        # The right one saves, and comes back out of the file.
        errors = adminplots.save(admin, "daytemp", {
            "line0_obs": "outTemp", "line0_series": "nordfeld",
            "time_length": "86400", "span": "day"}, {"outTemp"})
        check("the right one saves", [k for k in errors if k != ""], [])
        back = adminplots.load(admin).get("daytemp")
        check("and it is in the file", back.lines[0].series, "nordfeld")


def main() -> int:
    the_settings_become_the_file()
    the_second_one_brings_the_first_with_it()
    an_unknown_name_is_refused()
    station_selections_survive_the_file()
    member_policy_values_are_checked_per_archive()
    legacy_station_destinations_move_once()
    legacy_member_policies_move_once()
    a_place_in_another_timezone_is_said_out_loud()
    two_archives_do_not_clear_each_others_work()
    an_old_database_gains_the_column()
    each_series_takes_only_its_own()
    an_archive_with_no_stations_writes_nothing()
    a_broad_archive_selection_takes_everything()
    the_altitude_is_the_archives()
    a_page_prints_its_own_place()
    the_page_is_how_the_second_one_appears()
    a_command_can_name_its_series()
    two_sites_through_a_real_serve()

    # Two places on one chart, which is what n archives were missing.
    test_one_chart_draws_two_places()
    test_two_places_in_two_unit_systems()
    test_a_line_naming_an_archive_that_is_not_there_is_left_out()
    test_a_series_survives_the_round_trip_through_the_file()
    test_nothing_is_opened_where_no_plot_names_one()
    test_a_line_can_be_pointed_at_another_series_from_the_page()

    print()
    if failures:
        print(f"{failures} check(s) failed")
        return 1
    print("two places, two series, and neither one is the other's")
    return 0


if __name__ == "__main__":
    sys.exit(main())
